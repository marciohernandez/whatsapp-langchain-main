"""Webhook do WAHA — processamento assíncrono via fila.

Recebe os eventos do WAHA, descarta o que não é mensagem de usuário,
deduplica reentregas, aplica rate limit e coloca na fila para o Worker.
Retorna 200 imediatamente.

Fluxo: WAHA -> POST /webhook/waha -> Fila (PostgreSQL) -> Worker -> WAHA

No WAHA, configure o webhook da sessão com o evento "message":
    url:    http://<api>:8000/webhook/waha?agent=rhawk_assistant
    events: ["message"]

Uso:
    curl -X POST ".../webhook/waha?agent=rhawk_assistant" \
         -H "Content-Type: application/json" \
         -d '{"event":"message","payload":{"id":"x","from":"5511...@c.us",
              "fromMe":false,"body":"Olá"}}'
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from whatsapp_langchain.agents.loader import AgentNotFoundError, list_agents
from whatsapp_langchain.server.dependencies import (
    check_rate_limit,
    verify_waha_webhook,
)
from whatsapp_langchain.server.waha_events import WahaIgnored, parse_waha_event
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.queue import (
    enqueue_or_buffer,
    forget_inbound_message,
    register_inbound_message,
)

logger = structlog.get_logger()

router = APIRouter(tags=["webhook"])


@router.post("/webhook/waha")
async def webhook_waha(
    request: Request,
    agent: str = Query(
        description="ID do agente para processar a mensagem",
    ),
    _auth: None = Depends(verify_waha_webhook),
) -> dict[str, str]:
    """Recebe um evento do WAHA e enfileira para processamento.

    Eventos que não são mensagens de usuário (ack, status, grupos, mensagens
    enviadas pela própria sessão) e reentregas são aceitos com 200 e ignorados,
    para o WAHA não tentar reenviá-los.

    Args:
        agent: ID do agente (query param).

    Returns:
        {"status": "queued" | "buffered" | "ignored" | "duplicate" | "rate_limited"}
    """
    if agent not in list_agents():
        raise AgentNotFoundError(agent)

    try:
        event = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    inbound = parse_waha_event(event)
    if isinstance(inbound, WahaIgnored):
        logger.debug("webhook_waha_ignored", reason=inbound.reason)
        return {"status": "ignored", "reason": inbound.reason}

    # Rate limit: responde 200 para o WAHA não reentregar a mensagem descartada
    try:
        await check_rate_limit(inbound.phone_number)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        return {"status": "rate_limited"}

    pool = await get_pool()

    if inbound.message_id and not await register_inbound_message(
        pool, inbound.message_id
    ):
        logger.info("webhook_waha_duplicate", message_id=inbound.message_id)
        return {"status": "duplicate"}

    try:
        result = await enqueue_or_buffer(
            pool=pool,
            phone_number=inbound.phone_number,
            agent_id=agent,
            body=inbound.body,
            media_url=inbound.media_url,
            media_type=inbound.media_type,
            to_number=inbound.to_number,
            message_id=inbound.message_id or None,
            buffer_seconds=settings.message_buffer_seconds,
            chat_id=inbound.chat_id,
        )
    except Exception:
        # Libera o ID para que a reentrega do WAHA não seja tratada como duplicada
        if inbound.message_id:
            await forget_inbound_message(pool, inbound.message_id)
        raise

    logger.info(
        "webhook_waha_received",
        phone=inbound.phone_number,
        agent_id=agent,
        message_id=result.message_id,
        buffered=result.is_buffered,
    )

    return {"status": "buffered" if result.is_buffered else "queued"}
