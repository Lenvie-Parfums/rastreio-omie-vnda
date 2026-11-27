import json
import logging
import os
import time
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger(__name__)

log.info("Iniciando sincronizacao de rastreio Omie -> Vnda...")

try:
    from utils.ConsultaOmie import listar_pedidos_com_rastreio
    from utils.EnviaVnda import enviar_rastreio
    log.info("Modulos importados OK")
except Exception as e:
    log.error(f"Falha ao importar modulos: {e}")
    sys.exit(1)


def _order_code_da_vnda(pedido):
    """
    Descobre o order_code da Vnda a partir do pedido do Omie.
    O número do pedido da Vnda costuma estar no codigo_pedido_integracao.
    """
    return (
        pedido.get("codigo_pedido_integracao")
        or pedido.get("numero_pedido")
        or ""
    )


ARQUIVO_ESTADO = os.getenv("ARQUIVO_ESTADO", "estado_rastreio.json")


def _carregar_estado():
    try:
        with open(ARQUIVO_ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as e:
        log.warning(f"Estado ilegível ({e}); começando do zero.")
        return {}


def _salvar_estado(estado):
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=0, sort_keys=True)


def sincronizar_rastreios():
    pedidos = listar_pedidos_com_rastreio()
    total = len(pedidos)
    log.info(f"Pedidos com rastreio a processar: {total}")

    estado = _carregar_estado()
    log.info(f"Estado carregado: {len(estado)} pedidos já sincronizados.")
    novo_estado = {}

    ok = falhas = sem_order_code = ja_sincronizados = 0

    for pedido in pedidos:
        order_code = str(_order_code_da_vnda(pedido)).strip()
        if not order_code:
            log.warning(f"Pedido {pedido.get('numero_pedido')} sem order_code Vnda. Pulando.")
            sem_order_code += 1
            continue

        etapa = pedido.get("etapa", "")
        assinatura = {"url": pedido.get("url_rastreio", ""), "etapa": etapa}
        if estado.get(order_code) == assinatura:
            novo_estado[order_code] = assinatura
            ja_sincronizados += 1
            continue

        log.info(
            f"Processando pedido Vnda {order_code} | "
            f"etapa={etapa} | "
            f"rastreio={pedido.get('codigo_rastreio') or pedido.get('url_rastreio') or '(sem URL)'}"
        )

        sucesso = enviar_rastreio(
            order_code,
            pedido.get("codigo_rastreio", ""),
            pedido.get("url_rastreio", ""),
            pedido.get("transportadora", ""),
            etapa,  # propaga etapa para controle do /ship
        )
        if sucesso:
            ok += 1
            novo_estado[order_code] = assinatura
        else:
            falhas += 1

        time.sleep(1)

    # só guarda pedidos ainda na janela do Omie, para o arquivo não crescer sem limite
    _salvar_estado(novo_estado)

    log.info("=" * 60)
    log.info("RESUMO (Omie -> Vnda)")
    log.info(f"  Pedidos processados:     {total}")
    log.info(f"  Já sincronizados (pulo): {ja_sincronizados}")
    log.info(f"  Sucesso:                 {ok}")
    log.info(f"  Falhas:                  {falhas}")
    log.info(f"  Sem order_code Vnda:     {sem_order_code}")
    log.info("=" * 60)


if __name__ == "__main__":
    sincronizar_rastreios()
