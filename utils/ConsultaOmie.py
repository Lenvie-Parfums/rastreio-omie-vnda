"""
ConsultaOmie.py
Lista pedidos de venda no Omie e extrai o código/URL de rastreio.

A URL de rastreio é retornada pela TPL para o Omie. Ela normalmente cai
no campo `codigo_rastreio` do cabecalho do pedido, mas pode aparecer na
observação da NF. Este módulo tenta os campos mais prováveis e loga o que
encontrar para ajuste fino na primeira execução.
"""
import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

OMIE_PEDIDOS_URL = "https://app.omie.com.br/api/v1/produtos/pedido/"
APP_KEY    = os.getenv("APP_KEY_OMIE")
APP_SECRET = os.getenv("APP_SECRET")

TZ_SP = ZoneInfo("America/Sao_Paulo")

# Quantos dias para trás buscar pedidos faturados
DIAS_RETROATIVOS = int(os.getenv("DIAS_RETROATIVOS", "3"))


def _post_omie(payload, max_retries=3, retry_delay=10):
    for tentativa in range(1, max_retries + 1):
        try:
            resp = requests.post(
                OMIE_PEDIDOS_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=60
            )
            texto = resp.text
            if "REDUNDANT" in texto or "MISUSE_API" in texto or resp.status_code in (425, 429):
                log.warning(f"Omie limitado. Aguardando 60s... (tentativa {tentativa})")
                time.sleep(60)
                continue
            return resp
        except requests.exceptions.RequestException as e:
            log.warning(f"Falha Omie: {e} (tentativa {tentativa})")
            time.sleep(retry_delay)
    return None


def listar_pedidos_com_rastreio():
    """
    Lista pedidos faturados nos últimos DIAS_RETROATIVOS dias e extrai
    o rastreio de cada um.

    Retorna lista de dicts:
      [{"numero_pedido": ..., "codigo_pedido_integracao": ...,
        "codigo_rastreio": ..., "url_rastreio": ..., "transportadora": ...}]
    """
    hoje = datetime.now(TZ_SP)
    data_de = (hoje - timedelta(days=DIAS_RETROATIVOS)).strftime("%d/%m/%Y")
    data_ate = hoje.strftime("%d/%m/%Y")

    resultados = []
    pagina = 1
    total_paginas = 1
    logou_exemplo = False

    while pagina <= total_paginas:
        payload = {
            "call": "ListarPedidos",
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "param": [{
                "pagina": pagina,
                "registros_por_pagina": 50,
                "apenas_importado_api": "N",
                "filtrar_por_data_de": data_de,
                "filtrar_por_data_ate": data_ate
            }]
        }

        resp = _post_omie(payload)
        if resp is None:
            log.error("Falha definitiva ao listar pedidos.")
            break

        data = resp.json()
        if "faultstring" in data:
            log.error(f"Erro Omie: {data['faultstring']}")
            break

        total_paginas = data.get("total_de_paginas", 1)
        pedidos = data.get("pedido_venda_produto", [])

        for ped in pedidos:
            cab = ped.get("cabecalho", {})
            info = ped.get("informacoes_adicionais", {})
            frete = ped.get("frete", {})

            # Loga a estrutura do primeiro pedido pra ajuste
            if not logou_exemplo:
                log.info(f"Estrutura cabecalho: {json.dumps(list(cab.keys()))}")
                log.info(f"Estrutura frete: {json.dumps(list(frete.keys()))}")
                log.info(f"Exemplo cabecalho: {json.dumps(cab)[:400]}")
                logou_exemplo = True

            numero_pedido = cab.get("numero_pedido", "")
            cod_integracao = cab.get("codigo_pedido_integracao", "")

            # A URL/código de rastreio pode estar em vários lugares — tenta todos
            codigo_rastreio = (
                cab.get("codigo_rastreio")
                or info.get("codigo_rastreio")
                or frete.get("codigo_rastreio")
                or ""
            )
            url_rastreio = (
                frete.get("url_rastreamento")
                or info.get("url_rastreamento")
                or cab.get("url_rastreamento")
                or ""
            )
            transportadora = frete.get("codigo_transportadora", "") or ""

            # Só inclui se tem algum rastreio
            if codigo_rastreio or url_rastreio:
                resultados.append({
                    "numero_pedido": numero_pedido,
                    "codigo_pedido_integracao": cod_integracao,
                    "codigo_rastreio": codigo_rastreio,
                    "url_rastreio": url_rastreio,
                    "transportadora": transportadora,
                })

        log.info(f"Pagina {pagina}/{total_paginas}: {len(pedidos)} pedidos.")
        pagina += 1
        time.sleep(0.5)

    log.info(f"Total de pedidos com rastreio encontrados: {len(resultados)}")
    return resultados
