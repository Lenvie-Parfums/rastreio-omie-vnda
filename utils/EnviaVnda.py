import os, json, time, logging, requests
from dotenv import load_dotenv
load_dotenv()
log = logging.getLogger(__name__)

VNDA_BASE_URL  = os.getenv("VNDA_BASE_URL", "https://api.vnda.com.br")
VNDA_TOKEN     = os.getenv("VNDA_TOKEN")
VNDA_SHOP_HOST = os.getenv("VNDA_SHOP_HOST", "www.lenvieparfums.com")

def _headers():
    return {
        "accept":        "application/json",
        "content-type":  "application/json",
        "authorization": f"Bearer {VNDA_TOKEN}",
        "x-shop-host":   VNDA_SHOP_HOST,
    }

def buscar_package_code(order_code, max_retries=3):
    url = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages"
    for tentativa in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=_headers(), timeout=30)
            if resp.status_code == 200:
                pacotes = resp.json()
                if isinstance(pacotes, list) and pacotes:
                    return pacotes[0].get("code")
                return None
            elif resp.status_code == 404:
                log.warning(f"[{order_code}] Pedido nao encontrado na Vnda.")
                return None
            else:
                log.warning(f"[{order_code}] Erro {resp.status_code}: {resp.text[:200]}")
        except requests.exceptions.RequestException as e:
            log.warning(f"[{order_code}] Falha: {e}")
        time.sleep(5)
    return None

def ja_tem_rastreio(order_code, package_code):
    url = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        log.info(f"[{order_code}] GET trackings status={resp.status_code} retorno={resp.text[:200]}")
        if resp.status_code == 200:
            trackings = resp.json()
            if isinstance(trackings, list):
                # Verifica se tem ao menos um tracking com campo 'code' preenchido
                validos = [t for t in trackings if t.get("code") or t.get("tracking_code")]
                if validos:
                    log.info(f"[{order_code}] Ja tem {len(validos)} rastreio(s) valido(s). Pulando.")
                    return True
        return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro ao verificar rastreio: {e}")
        return False

def incluir_rastreio(order_code, package_code, codigo, url="", company=""):
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
            log.info(f"[{order_code}] ✅ Rastreio incluido com sucesso! Status={resp.status_code}")
            return True
        log.warning(f"[{order_code}] ❌ Falha {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro: {e}")
        return False

def enviar_rastreio(order_code, codigo_rastreio, url_rastreio="", transportadora=""):
    codigo = codigo_rastreio or url_rastreio
    if not codigo:
        log.warning(f"[{order_code}] Sem codigo. Pulando.")
        return False

    package_code = buscar_package_code(order_code)
    if not package_code:
        return False

    if ja_tem_rastreio(order_code, package_code):
        return True

    return incluir_rastreio(order_code, package_code, codigo, url_rastreio, transportadora)