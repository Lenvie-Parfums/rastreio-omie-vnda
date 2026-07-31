"""
EnviaVnda.py
Insere o código/URL de rastreio em um pedido da Vnda.

Fluxo:
  1. GET /orders/{order_code}/packages → pega o package_code
  2. POST /orders/{order_code}/packages/{package_code}/trackings → insere rastreio

A Vnda dispara o e-mail de rastreio para o cliente automaticamente após a inclusão.
"""
import os
import json
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

VNDA_BASE_URL = os.getenv("VNDA_BASE_URL", "https://api.vnda.com.br")
VNDA_TOKEN    = os.getenv("VNDA_TOKEN")
VNDA_SHOP_HOST = os.getenv("VNDA_SHOP_HOST")  # ex: loja.vnda.com.br


def _headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VNDA_TOKEN}",
        "X-Shop-Host": VNDA_SHOP_HOST,
    }


def buscar_package_code(order_code, max_retries=3):
    """Retorna o package_code do primeiro pacote do pedido."""
    url = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages"
    for tentativa in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=_headers(), timeout=30)
            if resp.status_code == 200:
                pacotes = resp.json()
                if isinstance(pacotes, list) and pacotes:
                    return pacotes[0].get("code")
                log.warning(f"[{order_code}] Nenhum pacote encontrado.")
                return None
            elif resp.status_code == 404:
                log.warning(f"[{order_code}] Pedido nao encontrado na Vnda.")
                return None
            else:
                log.warning(f"[{order_code}] Erro {resp.status_code} ao buscar pacotes.")
        except requests.exceptions.RequestException as e:
            log.warning(f"[{order_code}] Falha ao buscar pacotes: {e}")
        time.sleep(5)
    return None


def incluir_rastreio(order_code, package_code, codigo, url="", company=""):
    """
    Insere o código de rastreio no pacote.
    Retorna True se sucesso.
    """
    endpoint = f"{VNDA_BASE_URL}/api/v2/orders/{order_code}/packages/{package_code}/trackings"

    body = {"code": codigo}
    if url:
        body["url"] = url
    if company:
        body["company"] = company

    try:
        resp = requests.post(endpoint, headers=_headers(), data=json.dumps(body), timeout=30)
        if resp.status_code in (200, 201):
            log.info(f"[{order_code}] Rastreio incluido com sucesso! code={codigo}")
            return True
        else:
            log.warning(f"[{order_code}] Falha ao incluir rastreio ({resp.status_code}): {resp.text[:200]}")
            return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[{order_code}] Erro ao incluir rastreio: {e}")
        return False


def enviar_rastreio(order_code, codigo_rastreio, url_rastreio="", transportadora=""):
    """
    Fluxo completo: busca o pacote e insere o rastreio.
    """
    if not codigo_rastreio and not url_rastreio:
        log.warning(f"[{order_code}] Sem código nem URL de rastreio. Pulando.")
        return False

    # Se não tem código mas tem URL, usa a URL como código também (fallback)
    codigo = codigo_rastreio or url_rastreio

    package_code = buscar_package_code(order_code)
    if not package_code:
        return False

    return incluir_rastreio(order_code, package_code, codigo, url_rastreio, transportadora)
