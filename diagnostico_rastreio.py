"""
diagnostico_rastreio.py - versao 2
Testa a cadeia completa sem gravar nada.
Agora inclui verificacao de trackings existentes com log detalhado.
"""
import os
import json
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger(__name__)

OMIE_URL      = "https://app.omie.com.br/api/v1/produtos/pedido/"
APP_KEY       = os.getenv("APP_KEY_OMIE")
APP_SECRET    = os.getenv("APP_SECRET")
VNDA_BASE_URL  = os.getenv("VNDA_BASE_URL", "https://api.vnda.com.br")
VNDA_TOKEN     = os.getenv("VNDA_TOKEN")
VNDA_SHOP_HOST = os.getenv("VNDA_SHOP_HOST", "www.lenvieparfums.com")
TZ_SP = ZoneInfo("America/Sao_Paulo")
SEP = "=" * 60

def headers():
    return {
        "authorization": f"Bearer {VNDA_TOKEN}",
        "x-shop-host":   VNDA_SHOP_HOST,
        "accept":        "application/json",
        "content-type":  "application/json",
    }

# ============================================================
# PASSO 1 — Auth Vnda
# ============================================================
def testar_auth():
    log.info(SEP)
    log.info("PASSO 1 — Testando autenticacao Vnda")
    resp = requests.get(f"{VNDA_BASE_URL}/api/v2/orders?per_page=1", headers=headers(), timeout=15)
    log.info(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        log.info("  ✅ Auth OK!")
        pedidos = resp.json()
        if isinstance(pedidos, list) and pedidos:
            return pedidos[0].get("code")
        data = resp.json()
        pedidos = data.get("data", [])
        if pedidos:
            return pedidos[0].get("code")
    else:
        log.warning(f"  ❌ Falha: {resp.text[:200]}")
    return None

# ============================================================
# PASSO 2 — Pedidos Omie
# ============================================================
def buscar_pedidos():
    log.info(SEP)
    log.info("PASSO 2 — Buscando pedidos do Omie (ultimos 7 dias)")
    hoje   = datetime.now(TZ_SP)
    data_de  = (hoje - timedelta(days=7)).strftime("%d/%m/%Y")
    data_ate = hoje.strftime("%d/%m/%Y")
    payload = {
        "call": "ListarPedidos",
        "app_key": APP_KEY, "app_secret": APP_SECRET,
        "param": [{"pagina": 1, "registros_por_pagina": 10,
                   "apenas_importado_api": "N",
                   "filtrar_por_data_de": data_de,
                   "filtrar_por_data_ate": data_ate}]
    }
    resp = requests.post(OMIE_URL, headers={"Content-Type": "application/json"},
                         data=json.dumps(payload), timeout=60)
    data = resp.json()
    if "faultstring" in data:
        log.error(f"  Erro Omie: {data['faultstring']}")
        return []

    com_rastreio = []
    for ped in data.get("pedido_venda_produto", []):
        cab   = ped.get("cabecalho", {})
        frete = ped.get("frete", {})
        order_code = cab.get("codigo_pedido_integracao", "").strip()
        numero     = cab.get("numero_pedido", "")
        rastreio   = frete.get("codigo_rastreio", "") or frete.get("link_rastreio", "") or ""
        log.info(f"  Pedido {numero} | integracao={order_code} | rastreio={rastreio or '(vazio)'}")
        if rastreio and order_code:
            com_rastreio.append({"order_code": order_code, "numero": numero, "rastreio": rastreio})

    log.info(f"  Com rastreio + order_code: {len(com_rastreio)}")
    return com_rastreio

# ============================================================
# PASSO 3 — Pacotes + Trackings existentes
# ============================================================
def verificar_pacote_e_trackings(order_code):
    log.info(SEP)
    log.info(f"PASSO 3 — Pacotes + Trackings do pedido: {order_code}")

    # Busca pacotes
    resp = requests.get(f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages",
                        headers=headers(), timeout=15)
    log.info(f"  GET packages status: {resp.status_code}")
    log.info(f"  GET packages retorno: {resp.text[:300]}")

    if resp.status_code != 200:
        return None, None

    pacotes = resp.json()
    if not isinstance(pacotes, list) or not pacotes:
        log.warning("  Nenhum pacote encontrado.")
        return None, None

    package_code = pacotes[0].get("code")
    log.info(f"  Package code: {package_code}")

    # Verifica trackings existentes
    resp2 = requests.get(
        f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings",
        headers=headers(), timeout=15)
    log.info(f"  GET trackings status: {resp2.status_code}")
    log.info(f"  GET trackings retorno: {resp2.text[:300]}")

    return package_code, resp2

# ============================================================
# PASSO 4 — Dry-run
# ============================================================
def dry_run(order_code, package_code, rastreio):
    log.info(SEP)
    log.info("PASSO 4 — Dry-run do POST (nao envia)")
    endpoint = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings"
    body = {"code": rastreio, "url": rastreio, "company": "TPL"}
    log.info(f"  Endpoint: POST {endpoint}")
    log.info(f"  Body: {json.dumps(body)}")
    log.info("  ✅ Dry-run OK. Nada foi enviado.")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    log.info("DIAGNOSTICO RASTREIO OMIE → VNDA v2")
    log.info(SEP)

    testar_auth()
    pedidos = buscar_pedidos()

    if pedidos:
        ped = pedidos[0]
        package_code, resp_trackings = verificar_pacote_e_trackings(ped["order_code"])
        if package_code:
            dry_run(ped["order_code"], package_code, ped["rastreio"])
    else:
        log.info("Nenhum pedido com rastreio encontrado.")

    log.info(SEP)
    log.info("DIAGNOSTICO CONCLUIDO — nenhum dado foi alterado")
