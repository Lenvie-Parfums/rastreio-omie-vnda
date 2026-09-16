import os, json, time, logging, requests
from dotenv import load_dotenv
load_dotenv()
log = logging.getLogger(__name__)

VNDA_BASE_URL  = os.getenv("VNDA_BASE_URL", "https://api.vnda.com.br")
VNDA_TOKEN     = os.getenv("VNDA_TOKEN")
VNDA_SHOP_HOST = os.getenv("VNDA_SHOP_HOST", "www.lenvieparfums.com")

# Etapas que indicam que a transportadora confirmou a coleta
ETAPAS_ENVIADO = {"70", "80"}


def _headers():
    return {
        "accept":        "application/json",
        "content-type":  "application/json",
        "authorization": f"Bearer {VNDA_TOKEN}",
        "x-shop-host":   VNDA_SHOP_HOST,
    }


def buscar_package_code(order_code, max_retries=3):
    """
    Busca o package_code do pedido na Vnda.
    Tenta primeiro GET /packages, depois GET /orders/{code} como fallback.
    """
    url = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages"
    for tentativa in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=_headers(), timeout=30)
            if resp.status_code == 200:
                pacotes = resp.json()
                if isinstance(pacotes, list) and pacotes:
                    log.info(f"[{order_code}] Pacote encontrado via /packages: {pacotes[0].get('code')}")
                    return pacotes[0].get("code")
                break  # lista vazia — tenta fallback
            elif resp.status_code == 404:
                log.warning(f"[{order_code}] Pedido não encontrado na Vnda.")
                return None
            else:
                log.warning(f"[{order_code}] Erro {resp.status_code}: {resp.text[:100]}")
        except requests.exceptions.RequestException as e:
            log.warning(f"[{order_code}] Falha (tentativa {tentativa}): {e}")
        time.sleep(5)

    # Fallback via GET /orders/{order_code}
    log.info(f"[{order_code}] Tentando buscar pacote via GET /orders/{order_code}...")
    try:
        resp2 = requests.get(
            f"{VNDA_BASE_URL}/api/v2/orders/{order_code}",
            headers=_headers(), timeout=30)
        log.info(f"[{order_code}] GET order status={resp2.status_code} retorno={resp2.text[:300]}")
        if resp2.status_code == 200:
            pacotes = resp2.json().get("packages", [])
            if pacotes:
                log.info(f"[{order_code}] Pacote encontrado via /orders: {pacotes[0].get('code')}")
                return pacotes[0].get("code")
            log.warning(f"[{order_code}] Nenhum pacote no pedido.")
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro fallback: {e}")

    return None


def ja_tem_rastreio(order_code, package_code):
    """
    Verifica se já há rastreio registrado na Vnda.
    Apenas leitura — não aciona /ship.
    """
    url = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        log.info(f"[{order_code}] GET trackings status={resp.status_code} retorno={resp.text[:200]}")
        if resp.status_code == 200:
            trackings = resp.json()
            if isinstance(trackings, list):
                validos = [t for t in trackings if t.get("code") or t.get("tracking_code")]
                if validos:
                    log.info(f"[{order_code}] Já tem rastreio na Vnda.")
                    return True
        return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro ao verificar rastreio: {e}")
        return False


def marcar_como_enviado(order_code, package_code):
    """
    PATCH /ship — muda status do pedido na Vnda e dispara e-mail ao cliente.
    Só deve ser chamado quando a transportadora confirmou a coleta (etapa 70/80).
    """
    endpoint = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/ship"
    try:
        resp = requests.patch(endpoint, headers=_headers(), timeout=30)
        log.info(f"[{order_code}] PATCH ship status={resp.status_code}")
        if resp.status_code == 204:
            log.info(f"[{order_code}] ✅ Pacote marcado como enviado.")
            return True
        log.warning(f"[{order_code}] ⚠️ ship retornou {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro ao chamar ship: {e}")
        return False


def incluir_rastreio(order_code, package_code, codigo, url="", company=""):
    """
    POST tracking na Vnda.
    Não aciona /ship — quem decide isso é enviar_rastreio() com base na etapa.
    """
    endpoint = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings"
    body = {"code": codigo}
    if url:     body["url"]     = url
    if company: body["company"] = company

    log.info(f"[{order_code}] POST trackings")
    log.info(f"[{order_code}]   URL: {endpoint}")
    log.info(f"[{order_code}]   Body: {json.dumps(body)}")

    try:
        resp = requests.post(endpoint, headers=_headers(), data=json.dumps(body), timeout=30)
        log.info(f"[{order_code}]   Status: {resp.status_code}")
        log.info(f"[{order_code}]   Retorno: {resp.text[:300]}")
        if resp.status_code in (200, 201):
            log.info(f"[{order_code}] ✅ Rastreio incluído com sucesso!")
            return True
        log.warning(f"[{order_code}] ❌ Falha {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro: {e}")
        return False


def enviar_rastreio(order_code, codigo_rastreio, url_rastreio="", transportadora="", etapa=""):
    """
    Orquestra o envio de rastreio e a marcação de enviado na Vnda.

    Regras:
    - Etapa 60: registra rastreio (se tiver URL e ainda não registrou), NÃO marca como enviado.
    - Etapa 70/80: registra rastreio (se ainda não tem) E marca como enviado via /ship.
    - Se já tem rastreio e etapa subiu pra 70/80: só chama /ship.
    - Se etapa 70/80 mas sem URL ainda: marca como enviado mesmo assim.
    """
    codigo = codigo_rastreio or url_rastreio
    deve_marcar_enviado = etapa in ETAPAS_ENVIADO

    package_code = buscar_package_code(order_code)
    if not package_code:
        return False

    tem_rastreio = ja_tem_rastreio(order_code, package_code)

    if not tem_rastreio:
        if codigo:
            sucesso = incluir_rastreio(order_code, package_code, codigo, url_rastreio, transportadora)
            if not sucesso:
                return False
            log.info(f"[{order_code}] Rastreio registrado (etapa {etapa}).")
        else:
            # Sem URL ainda — se a coleta já foi confirmada, marca enviado assim mesmo
            if deve_marcar_enviado:
                log.info(f"[{order_code}] Etapa {etapa} sem URL de rastreio — marcando como enviado.")
                return marcar_como_enviado(order_code, package_code)
            else:
                log.info(f"[{order_code}] Sem URL de rastreio (etapa {etapa}). Aguardando TPL.")
                return False

    # Aciona /ship somente se a coleta foi confirmada (etapa 70/80)
    if deve_marcar_enviado:
        log.info(f"[{order_code}] Etapa {etapa} — acionando /ship.")
        return marcar_como_enviado(order_code, package_code)
    else:
        log.info(f"[{order_code}] Etapa {etapa} — rastreio OK, aguardando coleta para /ship.")
        return True
