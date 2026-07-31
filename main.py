import logging
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


def sincronizar_rastreios():
    pedidos = listar_pedidos_com_rastreio()
    total = len(pedidos)
    log.info(f"Pedidos com rastreio a processar: {total}")

    ok = falhas = sem_order_code = 0

    for pedido in pedidos:
        order_code = str(_order_code_da_vnda(pedido)).strip()
        if not order_code:
            log.warning(f"Pedido {pedido.get('numero_pedido')} sem order_code Vnda. Pulando.")
            sem_order_code += 1
            continue

        log.info(f"Processando pedido Vnda {order_code} "
                 f"(rastreio: {pedido.get('codigo_rastreio') or pedido.get('url_rastreio')})")

        sucesso = enviar_rastreio(
            order_code,
            pedido.get("codigo_rastreio", ""),
            pedido.get("url_rastreio", ""),
            pedido.get("transportadora", ""),
        )
        if sucesso:
            ok += 1
        else:
            falhas += 1

        time.sleep(1)

    log.info("=" * 60)
    log.info("RESUMO (Omie -> Vnda)")
    log.info(f"  Pedidos com rastreio:    {total}")
    log.info(f"  Rastreios enviados:      {ok}")
    log.info(f"  Falhas:                  {falhas}")
    log.info(f"  Sem order_code Vnda:     {sem_order_code}")
    log.info("=" * 60)


if __name__ == "__main__":
    sincronizar_rastreios()
