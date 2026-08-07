import os, json, time, logging, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()
log = logging.getLogger(__name__)

OMIE_PEDIDOS_URL = "https://app.omie.com.br/api/v1/produtos/pedido/"
APP_KEY    = os.getenv("APP_KEY_OMIE")
APP_SECRET = os.getenv("APP_SECRET")
TZ_SP = ZoneInfo("America/Sao_Paulo")
DIAS_RETROATIVOS = int(os.getenv("DIAS_RETROATIVOS", "3"))

def _post_omie(payload, max_retries=3, retry_delay=10):
    for tentativa in range(1, max_retries + 1):
        try:
            resp = requests.post(OMIE_PEDIDOS_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload), timeout=60)
            texto = resp.text
            if "REDUNDANT" in texto or "MISUSE_API" in texto or resp.status_code in (425, 429):
                log.warning(f"Omie limitado. Aguardando 60s...")
                time.sleep(60); continue
            return resp
        except requests.exceptions.RequestException as e:
            log.warning(f"Falha Omie: {e} (tentativa {tentativa})")
            time.sleep(retry_delay)
    return None

def listar_pedidos_com_rastreio():
    hoje     = datetime.now(TZ_SP)
    data_de  = (hoje - timedelta(days=DIAS_RETROATIVOS)).strftime("%d/%m/%Y")
    data_ate = hoje.strftime("%d/%m/%Y")
    resultados = []
    pagina = 1
    total_paginas = 1

    while pagina <= total_paginas:
        payload = {
            "call": "ListarPedidos",
            "app_key": APP_KEY, "app_secret": APP_SECRET,
            "param": [{
                "pagina": pagina, "registros_por_pagina": 50,
                "apenas_importado_api": "N",
                "filtrar_por_data_de": data_de,
                "filtrar_por_data_ate": data_ate
            }]
        }
        resp = _post_omie(payload)
        if resp is None: log.error("Falha definitiva."); break
        data = resp.json()
        if "faultstring" in data: log.error(f"Erro Omie: {data['faultstring']}"); break

        total_paginas = data.get("total_de_paginas", 1)
        for ped in data.get("pedido_venda_produto", []):
            cab   = ped.get("cabecalho", {})
            frete = ped.get("frete", {})
            order_code = cab.get("codigo_pedido_integracao", "").strip()
            numero     = cab.get("numero_pedido", "")
            etapa      = str(cab.get("etapa", "")).strip()
            rastreio   = frete.get("codigo_rastreio", "") or frete.get("link_rastreio", "") or ""
            transp     = str(frete.get("codigo_transportadora", "") or "")

            if rastreio and order_code:
                resultados.append({
                    "numero_pedido":            numero,
                    "codigo_pedido_integracao": order_code,
                    "codigo_rastreio":          rastreio,
                    "url_rastreio":             rastreio,
                    "transportadora":           transp,
                    "etapa":                    etapa,
                })

        log.info(f"Pagina {pagina}/{total_paginas} processada.")
        pagina += 1
        time.sleep(0.5)

    log.info(f"Total pedidos com rastreio e order_code: {len(resultados)}")
    return resultados