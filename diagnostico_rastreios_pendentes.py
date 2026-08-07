"""
diagnostico_rastreios_pendentes.py
Mapeia TODOS os pedidos desde 20/07/2026 com problemas de rastreio:

Cenário A — Omie tem rastreio mas não foi pra Vnda (cliente sem rastreio)
Cenário B — Pedido na Vnda sem rastreio no Omie (TPL não atualizou)

Gera relatório CSV com todos os casos encontrados.
"""
import os
import json
import csv
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger(__name__)

OMIE_URL       = "https://app.omie.com.br/api/v1/produtos/pedido/"
APP_KEY        = os.getenv("APP_KEY_OMIE")
APP_SECRET     = os.getenv("APP_SECRET")
VNDA_BASE_URL  = os.getenv("VNDA_BASE_URL", "https://api.vnda.com.br")
VNDA_TOKEN     = os.getenv("VNDA_TOKEN")
VNDA_SHOP_HOST = os.getenv("VNDA_SHOP_HOST", "www.lenvieparfums.com")
TZ_SP          = ZoneInfo("America/Sao_Paulo")

DATA_INICIO = "20/07/2026"
DATA_FIM    = datetime.now(TZ_SP).strftime("%d/%m/%Y")


def vnda_headers():
    return {
        "authorization": f"Bearer {VNDA_TOKEN}",
        "x-shop-host":   VNDA_SHOP_HOST,
        "accept":        "application/json",
        "content-type":  "application/json",
    }


# ============================================================
# OMIE — Lista todos os pedidos do período
# ============================================================
def listar_todos_pedidos_omie():
    log.info(f"Buscando pedidos Omie de {DATA_INICIO} a {DATA_FIM}...")
    pedidos = []
    pagina = 1
    total_paginas = 1

    while pagina <= total_paginas:
        payload = {
            "call": "ListarPedidos",
            "app_key": APP_KEY, "app_secret": APP_SECRET,
            "param": [{
                "pagina": pagina,
                "registros_por_pagina": 50,
                "apenas_importado_api": "N",
                "filtrar_por_data_de":  DATA_INICIO,
                "filtrar_por_data_ate": DATA_FIM,
            }]
        }
        try:
            resp = requests.post(OMIE_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload), timeout=60)
            data = resp.json()

            if "faultstring" in data:
                if "REDUNDANT" in data["faultstring"] or "bloqueado" in data["faultstring"]:
                    log.warning("Rate limit Omie. Aguardando 60s...")
                    import time; time.sleep(60)
                    continue
                log.error(f"Erro Omie: {data['faultstring']}")
                break

            total_paginas = data.get("total_de_paginas", 1)
            for ped in data.get("pedido_venda_produto", []):
                cab   = ped.get("cabecalho", {})
                frete = ped.get("frete", {})
                info  = ped.get("informacoes_adicionais", {})

                pedidos.append({
                    "numero_pedido":            cab.get("numero_pedido", ""),
                    "order_code_vnda":          cab.get("codigo_pedido_integracao", "").strip(),
                    "origem_pedido":            cab.get("origem_pedido", ""),
                    "etapa":                    cab.get("etapa", ""),
                    "rastreio_omie":            frete.get("codigo_rastreio", "") or frete.get("link_rastreio", "") or "",
                    "transportadora":           str(frete.get("codigo_transportadora", "") or ""),
                    "obs_geral":               info.get("obs_geral", ""),
                    "dados_adicionais":        info.get("dados_adicionais_nf", ""),
                })

            log.info(f"  Página {pagina}/{total_paginas}: {len(data.get('pedido_venda_produto', []))} pedidos")
            pagina += 1
            import time; time.sleep(0.5)

        except Exception as e:
            log.error(f"Erro: {e}")
            break

    log.info(f"Total pedidos Omie: {len(pedidos)}")
    return pedidos


# ============================================================
# VNDA — Verifica se pedido tem rastreio cadastrado
# ============================================================
def verificar_rastreio_vnda(order_code):
    """Retorna (package_code, tem_rastreio, codigo_rastreio_vnda)"""
    try:
        # Busca pacotes
        resp = requests.get(
            f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages",
            headers=vnda_headers(), timeout=15)

        if resp.status_code == 404:
            return None, False, ""
        if resp.status_code != 200:
            return None, False, ""

        pacotes = resp.json()
        if not isinstance(pacotes, list) or not pacotes:
            return None, False, ""

        package_code = pacotes[0].get("code")

        # Verifica trackings
        resp2 = requests.get(
            f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings",
            headers=vnda_headers(), timeout=15)

        if resp2.status_code == 200:
            trackings = resp2.json()
            if isinstance(trackings, list) and trackings:
                codigo = trackings[0].get("code", "") or trackings[0].get("tracking_code", "")
                return package_code, True, codigo
            return package_code, False, ""

        return package_code, False, ""

    except Exception as e:
        log.warning(f"Erro ao verificar Vnda {order_code}: {e}")
        return None, False, ""


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    log.info("=" * 60)
    log.info("DIAGNÓSTICO DE RASTREIOS PENDENTES")
    log.info(f"Período: {DATA_INICIO} a {DATA_FIM}")
    log.info("=" * 60)

    # Busca todos os pedidos do Omie
    pedidos = listar_todos_pedidos_omie()

    # Analisa cada cenário
    cenario_a = []  # Omie tem rastreio, Vnda não tem
    cenario_b = []  # Omie não tem rastreio (TPL não atualizou)
    sem_order_code = []  # Tem rastreio mas sem order_code Vnda
    ok = []

    total = len(pedidos)
    log.info(f"\nVerificando {total} pedidos na Vnda...")

    for i, ped in enumerate(pedidos):
        numero      = ped["numero_pedido"]
        order_code  = ped["order_code_vnda"]
        rastreio    = ped["rastreio_omie"]

        if i % 20 == 0:
            log.info(f"  Progresso: {i}/{total}...")

        # Cenário B — sem rastreio no Omie
        if not rastreio:
            cenario_b.append({**ped, "situacao": "Sem rastreio no Omie"})
            continue

        # Tem rastreio mas sem order_code Vnda
        if not order_code:
            sem_order_code.append({**ped, "situacao": "Rastreio no Omie mas sem order_code Vnda"})
            continue

        # Tem rastreio e order_code — verifica Vnda
        import time; time.sleep(0.3)
        package_code, tem_rastreio_vnda, cod_vnda = verificar_rastreio_vnda(order_code)

        if tem_rastreio_vnda:
            ok.append({**ped, "situacao": "OK - rastreio na Vnda", "rastreio_vnda": cod_vnda})
        else:
            cenario_a.append({**ped, "situacao": "Rastreio no Omie mas NÃO na Vnda",
                               "package_code": package_code or ""})

    # Relatório
    log.info("\n" + "=" * 60)
    log.info("RESUMO")
    log.info(f"  Total pedidos analisados:          {total}")
    log.info(f"  ✅ OK (rastreio na Vnda):          {len(ok)}")
    log.info(f"  🚨 Cenário A (Omie→Vnda pendente): {len(cenario_a)}")
    log.info(f"  ⚠️  Cenário B (sem rastreio Omie):  {len(cenario_b)}")
    log.info(f"  ❓ Sem order_code Vnda:             {len(sem_order_code)}")
    log.info("=" * 60)

    # Gera CSV com pendências
    pendentes = cenario_a + sem_order_code
    if pendentes:
        csv_path = "rastreios_pendentes.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            campos = ["situacao", "numero_pedido", "order_code_vnda",
                      "rastreio_omie", "transportadora", "origem_pedido", "etapa"]
            writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(pendentes)
        log.info(f"\n📄 CSV gerado: {csv_path} ({len(pendentes)} registros)")

    log.info("\nDIAGNÓSTICO CONCLUÍDO")
