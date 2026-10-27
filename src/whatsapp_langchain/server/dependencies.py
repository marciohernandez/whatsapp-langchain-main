"""FastAPI dependencies para validação e rate limiting.

Dependencies são injetadas automaticamente nas rotas via Depends().
Centralizar aqui mantém as rotas limpas e focadas na lógica de negócio.

Uso:
    from whatsapp_langchain.server.dependencies import check_rate_limit

    @router.post("/webhook/waha")
    async def webhook(rate_limit: None = Depends(check_rate_limit)):
        ...
"""

import hashlib
import hmac
import time
from collections import defaultdict

import structlog
from fastapi import HTTPException, Request

from whatsapp_langchain.shared.config import settings

logger = structlog.get_logger()

# Sliding window de requisições por telefone: {phone: [timestamps]}
request_history: dict[str, list[float]] = defaultdict(list)


async def verify_waha_webhook(request: Request) -> None:
    """Autentica o webhook do WAHA.

    Dois mecanismos, ambos opcionais e cumulativos quando configurados:
    - HMAC (WAHA_WEBHOOK_HMAC_KEY): o WAHA assina o body e envia o hex em
      X-Webhook-Hmac (algoritmo em X-Webhook-Hmac-Algorithm, default sha512).
    - Token (WAHA_WEBHOOK_TOKEN): header X-Webhook-Token, configurado em
      customHeaders do webhook no WAHA.

    Sem nenhum configurado o webhook fica aberto (somente dev local).

    Raises:
        HTTPException 403: Se a assinatura/token é ausente ou inválido.
    """
    hmac_key = settings.waha_webhook_hmac_key
    token = settings.waha_webhook_token

    if token is not None:
        received = request.headers.get("X-Webhook-Token", "")
        if not hmac.compare_digest(received, token.get_secret_value()):
            logger.warning("waha_token_invalid")
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    if hmac_key is not None:
        received = request.headers.get("X-Webhook-Hmac", "")
        algorithm = request.headers.get("X-Webhook-Hmac-Algorithm", "sha512").lower()
        if algorithm not in ("sha256", "sha512"):
            logger.warning("waha_hmac_algorithm_unsupported", algorithm=algorithm)
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        body = await request.body()
        expected = hmac.new(
            hmac_key.get_secret_value().encode(), body, getattr(hashlib, algorithm)
        ).hexdigest()
        if not hmac.compare_digest(received, expected):
            logger.warning("waha_hmac_invalid")
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    if token is None and hmac_key is None:
        logger.debug("waha_webhook_unauthenticated")


async def check_rate_limit(phone_number: str) -> None:
    """Verifica rate limit por número de telefone.

    Usa sliding window de 1 hora. Remove timestamps antigos e compara
    a quantidade de requisições com o limite configurado.

    Args:
        phone_number: Número de telefone do remetente.

    Raises:
        HTTPException 429: Se o limite foi atingido.
    """
    now = time.time()
    one_hour_ago = now - 3600

    # Remove timestamps antigos
    timestamps = request_history[phone_number]
    request_history[phone_number] = [t for t in timestamps if t > one_hour_ago]

    if len(request_history[phone_number]) >= settings.rate_limit_per_hour:
        logger.warning(
            "rate_limit_exceeded",
            phone=phone_number,
            count=len(request_history[phone_number]),
            limit=settings.rate_limit_per_hour,
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
        )

    # Registra nova requisição
    request_history[phone_number].append(now)
