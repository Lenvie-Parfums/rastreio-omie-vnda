"""
diagnostico_rastreio.py
Testa toda a cadeia sem gravar nada nos clientes:
  1. Autenticacao Vnda
  2. Busca pedidos do Omie com rastreio
  3. Busca pacotes de um pedido na Vnda
  4. Simula o POST de rastreio (dry-run — nao envia de verdade)

Uso: python diagnostico_rastreio.py
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

# Credenciais
OMIE_URL      = "https://app.omie.com.br/api/v1/produtos/pedido/"
APP_KEY       = os.getenv("APP_KEY_OMIE")
APP_SECRET    = os.getenv("APP_SECRET")

VNDA_BASE_URL  = os.getenv("VNDA_BASE_URL", "https://api.vnda.com.br")
VNDA_TOKEN     = os.getenv("VNDA_TOKEN")
VNDA_SHOP_HOST = os.getenv("VNDA_SHOP_HOST")

TZ_SP = ZoneInfo("America/Sao_Paulo")
SEPARADOR = "=" * 60


def vnda_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VNDA_TOKEN}",
        "X-Shop-Host": VNDA_SHOP_HOST,
    }


# ============================================================
# PASSO 1 — Autenticação Vnda
# ============================================================
def testar_autenticacao_vnda():
    log.info(SEPARADOR)
    log.info("PASSO 1 — Testando autenticacao Vnda")
    log.info(f"  Base URL: {VNDA_BASE_URL}")
    log.info(f"  Shop Host: {VNDA_SHOP_HOST}")
    log.info(f"  Token: {VNDA_TOKEN[:10]}...")

    try:
        resp = requests.get(
            f"{VNDA_BASE_URL}/api/v2/orders?per_page=1",
            headers=vnda_headers(),
            timeout=15
        )
        log.info(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            log.info("  ✅ Autenticacao Vnda OK!")
            data = resp.json()
            pedidos = data if isinstance(data, list) else data.get("data", [])
            if pedidos:
                log.info(f"  Exemplo de pedido Vnda: code={pedidos[0].get('code')} | token={pedidos[0].get('token')}")
                return pedidos[0].get("code")
        else:
            log.warning(f"  ❌ Falha: {resp.text[:300]}")
    except Exception as e:
        log.error(f"  ❌ Erro de conexao: {e}")
    return None


# ============================================================
# PASSO 2 — Busca pedidos do Omie com rastreio
# ============================================================
def buscar_pedidos_omie():
    log.info(SEPARADOR)
    log.info("PASSO 2 — Buscando pedidos do Omie (ultimos 7 dias)")

    hoje = datetime.now(TZ_SP)
    data_de  = (hoje - timedelta(days=7)).strftime("%d/%m/%Y")
    data_ate = hoje.strftime("%d/%m/%Y")

    payload = {
        "call": "ListarPedidos",
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [{
            "pagina": 1,
            "registros_por_pagina": 10,
            "apenas_importado_api": "N",
            "filtrar_por_data_de": data_de,
            "filtrar_por_data_ate": data_ate
        }]
    }

    try:
        resp = requests.post(OMIE_URL, headers={"Content-Type": "application/json"},
                             data=json.dumps(payload), timeout=60)
        data = resp.json()

        if "faultstring" in data:
            log.error(f"  ❌ Erro Omie: {data['faultstring']}")
            return []

        pedidos = data.get("pedido_venda_produto", [])
        log.info(f"  Total de pedidos retornados: {data.get('total_de_registros', 0)}")
        log.info(f"  Mostrando primeiros {len(pedidos)}")

        com_rastreio = []
        for ped in pedidos:
            cab   = ped.get("cabecalho", {})
            frete = ped.get("frete", {})
            info  = ped.get("informacoes_adicionais", {})

            num   = cab.get("numero_pedido")
            integ = cab.get("codigo_pedido_integracao", "")
            rastr = cab.get("codigo_rastreio", "") or frete.get("codigo_rastreio", "") or ""
            url   = frete.get("url_rastreamento", "") or info.get("url_rastreamento", "") or ""

            log.info(f"  Pedido {num} | integracao={integ} | rastreio={rastr or '(vazio)'} | url={url or '(vazio)'}")

            # Loga campos disponíveis no 1o pedido pra referência
            if num == pedidos[0].get("cabecalho", {}).get("numero_pedido"):
                log.info(f"    Campos cabecalho: {list(cab.keys())}")
                log.info(f"    Campos frete: {list(frete.keys())}")

            if rastr or url:
                com_rastreio.append({
                    "numero_pedido": num,
                    "codigo_pedido_integracao": integ,
                    "codigo_rastreio": rastr,
                    "url_rastreio": url,
                })

        log.info(f"  Pedidos com rastreio encontrados: {len(com_rastreio)}")
        return com_rastreio

    except Exception as e:
        log.error(f"  ❌ Erro: {e}")
        return []


# ============================================================
# PASSO 3 — Busca pacotes de um pedido na Vnda
# ============================================================
def buscar_pacotes_vnda(order_code):
    log.info(SEPARADOR)
    log.info(f"PASSO 3 — Buscando pacotes do pedido Vnda: {order_code}")

    try:
        resp = requests.get(
            f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages",
            headers=vnda_headers(),
            timeout=15
        )
        log.info(f"  Status: {resp.status_code}")
        log.info(f"  Retorno: {resp.text[:500]}")

        if resp.status_code == 200:
            pacotes = resp.json()
            if isinstance(pacotes, list) and pacotes:
                log.info(f"  ✅ {len(pacotes)} pacote(s) encontrado(s)")
                log.info(f"  Pacote 1: {json.dumps(pacotes[0])[:300]}")
                return pacotes[0].get("code")
            else:
                log.warning("  ⚠️ Nenhum pacote encontrado.")
        elif resp.status_code == 404:
            log.warning(f"  ⚠️ Pedido {order_code} nao encontrado na Vnda.")
    except Exception as e:
        log.error(f"  ❌ Erro: {e}")
    return None


# ============================================================
# PASSO 4 — Simula POST de rastreio (DRY-RUN)
# ============================================================
def simular_rastreio(order_code, package_code, codigo, url=""):
    log.info(SEPARADOR)
    log.info("PASSO 4 — Simulacao do POST de rastreio (DRY-RUN — nao envia)")
    log.info(f"  Endpoint: POST {VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings")
    log.info(f"  Headers: Authorization=Bearer {VNDA_TOKEN[:10]}... | X-Shop-Host={VNDA_SHOP_HOST}")

    body = {"code": codigo}
    if url:
        body["url"] = url

    log.info(f"  Body que seria enviado: {json.dumps(body)}")
    log.info("  ✅ Dry-run concluido. Nenhum dado foi enviado.")
    log.info("  Para enviar de verdade, rode o main.py")


# ============================================================
# EXECUCAO
# ============================================================
if __name__ == "__main__":
    log.info("DIAGNOSTICO RASTREIO OMIE → VNDA")
    log.info(SEPARADOR)

    # Passo 1 — testa Vnda
    order_code_vnda = testar_autenticacao_vnda()

    # Passo 2 — busca pedidos Omie
    pedidos_com_rastreio = buscar_pedidos_omie()

    # Passo 3 — testa busca de pacotes na Vnda
    # Usa o order_code do Omie (codigo_pedido_integracao) ou o da Vnda
    order_para_teste = None
    if pedidos_com_rastreio:
        order_para_teste = (
            pedidos_com_rastreio[0].get("codigo_pedido_integracao")
            or pedidos_com_rastreio[0].get("numero_pedido")
        )
    elif order_code_vnda:
        order_para_teste = order_code_vnda

    package_code = None
    if order_para_teste:
        package_code = buscar_pacotes_vnda(str(order_para_teste))

    # Passo 4 — dry-run do rastreio
    if pedidos_com_rastreio and package_code:
        ped = pedidos_com_rastreio[0]
        simular_rastreio(
            order_para_teste,
            package_code,
            ped.get("codigo_rastreio", "TESTE123"),
            ped.get("url_rastreio", ""),
        )
    else:
        log.info(SEPARADOR)
        log.info("PASSO 4 — Dry-run nao executado (sem pedido + pacote para testar)")
        log.info("  Isso pode acontecer se:")
        log.info("  - Nenhum pedido Omie tem rastreio nos ultimos 7 dias")
        log.info("  - O order_code Vnda nao foi encontrado")
        log.info("  Verifique os logs dos passos anteriores.")

    log.info(SEPARADOR)
    log.info("DIAGNOSTICO CONCLUIDO — nenhum dado foi alterado")
