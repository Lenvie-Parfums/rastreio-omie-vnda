import os, json, time, logging, requests
import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

OMIE_PEDIDOS_URL = "https://app.omie.com.br/api/v1/produtos/pedido/"
APP_KEY    = os.getenv("APP_KEY_OMIE")
APP_SECRET = os.getenv("APP_SECRET")
ETAPAS     = ["60", "70"]

# filtrar_por_data_de/ate no Omie considera data de inclusão OU de alteração do pedido
DIAS_RETROATIVOS = int(os.getenv("DIAS_RETROATIVOS") or 7)
_agora = datetime.datetime.now(ZoneInfo("America/Sao_Paulo"))
DATA_INICIO = (_agora - datetime.timedelta(days=DIAS_RETROATIVOS)).strftime("%d/%m/%Y")
DATA_FIM    = _agora.strftime("%d/%m/%Y")

SEM_REGISTROS = "Não existem registros"
FALHAS_TEMPORARIAS = ("Já existe uma requisição", "Broken response", "SOAP-ERROR")
MAX_TENTATIVAS_PAGINA = 4


def _post_omie(payload, max_retries=3, retry_delay=10):
    for tentativa in range(1, max_retries + 1):
        try:
            resp = requests.post(OMIE_PEDIDOS_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload), timeout=60)
            texto = resp.text
            if "REDUNDANT" in texto or "MISUSE_API" in texto or resp.status_code in (425, 429):
                log.warning("Omie limitado. Aguardando 60s...")
                time.sleep(60); continue
            return resp
        except requests.exceptions.RequestException as e:
            log.warning(f"Falha Omie: {e} (tentativa {tentativa})")
            time.sleep(retry_delay)
    return None


def _buscar_pagina(etapa, pagina):
    """Retorna o JSON da página, {} quando não há registros, ou None em falha definitiva."""
    payload = {
        "call": "ListarPedidos",
        "app_key": APP_KEY, "app_secret": APP_SECRET,
        "param": [{
            "pagina": pagina,
            "registros_por_pagina": 100,
            "apenas_importado_api": "N",
            "etapa": etapa,
            "filtrar_por_data_de":  DATA_INICIO,
            "filtrar_por_data_ate": DATA_FIM,
        }]
    }
    for tentativa in range(1, MAX_TENTATIVAS_PAGINA + 1):
        resp = _post_omie(payload)
        if resp is None:
            return None
        try:
            data = resp.json()
        except ValueError:
            data = {"faultstring": f"resposta inválida (HTTP {resp.status_code}): {resp.text[:150]}"}

        fault = data.get("faultstring")
        if not fault:
            return data
        if SEM_REGISTROS in fault:
            return {}
        espera = 30 * tentativa
        if any(f in fault for f in FALHAS_TEMPORARIAS) or "resposta inválida" in fault:
            log.warning(f"Omie etapa {etapa} pág {pagina}: {fault} — nova tentativa em {espera}s "
                        f"({tentativa}/{MAX_TENTATIVAS_PAGINA})")
            time.sleep(espera)
            continue
        log.error(f"Erro Omie etapa {etapa} pág {pagina}: {fault}")
        return None
    log.error(f"Omie etapa {etapa} pág {pagina}: desistindo após {MAX_TENTATIVAS_PAGINA} tentativas.")
    return None


def listar_pedidos_com_rastreio():
    por_numero = {}
    sem_rastreio, sem_order_code = [], []

    for etapa in ETAPAS:
        log.info(f"Buscando pedidos na etapa {etapa} desde {DATA_INICIO}...")
        pagina = 1
        total_paginas = 1

        while pagina <= total_paginas:
            data = _buscar_pagina(etapa, pagina)
            if data is None:
                log.error(f"Listagem da etapa {etapa} incompleta (parou na página {pagina}/{total_paginas}).")
                break
            if not data:
                log.info(f"  Etapa {etapa}: nenhum pedido no período.")
                break

            total_paginas = data.get("total_de_paginas", 1)
            pedidos       = data.get("pedido_venda_produto", [])

            for ped in pedidos:
                cab        = ped.get("cabecalho", {})
                frete      = ped.get("frete", {})
                order_code = (cab.get("codigo_pedido_integracao") or "").strip()
                numero     = cab.get("numero_pedido", "")
                rastreio   = frete.get("codigo_rastreio", "") or frete.get("link_rastreio", "") or ""
                transp     = str(frete.get("codigo_transportadora", "") or "")

                if not rastreio:
                    sem_rastreio.append(order_code or f"omie:{numero}")
                    continue
                if not order_code:
                    sem_order_code.append(str(numero))
                    continue
                # um pedido pode aparecer em mais de uma etapa: vale a mais avançada
                anterior = por_numero.get(numero)
                if anterior and int(anterior["etapa"]) >= int(etapa):
                    continue
                por_numero[numero] = {
                    "numero_pedido":            numero,
                    "codigo_pedido_integracao": order_code,
                    "codigo_rastreio":          rastreio,
                    "url_rastreio":             rastreio,
                    "transportadora":           transp,
                    "etapa":                    etapa,
                }

            log.info(f"  Etapa {etapa} | Pagina {pagina}/{total_paginas}: {len(pedidos)} pedidos")
            pagina += 1
            time.sleep(0.5)

    if sem_rastreio:
        log.info(f"Sem rastreio no Omie ({len(sem_rastreio)}): {', '.join(sem_rastreio)}")
    if sem_order_code:
        log.warning(f"Com rastreio mas sem codigo_pedido_integracao ({len(sem_order_code)}) "
                    f"— nº Omie: {', '.join(sem_order_code)}")

    resultados = list(por_numero.values())
    log.info(f"Total pedidos com rastreio e order_code: {len(resultados)}")
    return resultados
