"""Entry point do Worker — loop de processamento de mensagens.

Inicia o Worker que consome mensagens da fila PostgreSQL em loop.
Cada mensagem é processada pelo agente configurado.

Uso:
    python -m whatsapp_langchain.worker.main
"""

import asyncio

import structlog

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import (
    close_pool,
    get_pool,
    open_checkpointer,
    open_store,
    run_migrations,
)
from whatsapp_langchain.shared.observability import setup_logging
from whatsapp_langchain.worker.consumer import claim_next_message
from whatsapp_langchain.worker.processor import process_message
from whatsapp_langchain.worker.waha_client import WahaClient

logger = structlog.get_logger()


async def main() -> None:
    """Loop principal do Worker.

    1. Configura logging e banco de dados
    2. Aplica migrações pendentes
    3. Entra em loop infinito buscando mensagens na fila
    4. Processa cada mensagem com o agente apropriado
    """
    setup_logging(log_level=settings.log_level, json_output=settings.log_json)
    logger.info("worker_starting")

    pool = await get_pool()
    await run_migrations(pool)
    checkpointer_stack, checkpointer = await open_checkpointer()
    await checkpointer.setup()

    store_stack, store = await open_store()
    if store:
        await store.setup()

    # WAHA outbound: obrigatório — fail-fast se a URL não estiver configurada.
    if not settings.waha_base_url:
        logger.error("waha_config_missing", missing=["WAHA_BASE_URL"])
        raise SystemExit("WAHA obrigatório. Variável ausente: WAHA_BASE_URL")

    waha = WahaClient(
        base_url=settings.waha_base_url,
        api_key=settings.waha_api_key.get_secret_value()
        if settings.waha_api_key
        else "",
        session=settings.waha_session,
    )
    logger.info(
        "waha_client_ready",
        base_url=settings.waha_base_url,
        session=settings.waha_session,
    )

    logger.info(
        "worker_ready",
        poll_interval=settings.poll_interval_seconds,
        memory_enabled=store is not None,
    )

    try:
        while True:
            message = await claim_next_message(pool, settings.lease_seconds)

            if message is None:
                await asyncio.sleep(settings.poll_interval_seconds)
                continue

            await process_message(
                message,
                pool,
                checkpointer=checkpointer,
                store=store,
                waha=waha,
            )

    except KeyboardInterrupt:
        logger.info("worker_interrupted")
    finally:
        if store_stack is not None:
            await store_stack.aclose()
        await checkpointer_stack.aclose()
        await close_pool()
        logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
