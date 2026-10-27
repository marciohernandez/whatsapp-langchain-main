"""Normalização dos eventos de webhook do WAHA.

O WAHA envia todos os eventos (mensagem, ack, status de sessão, grupos...)
para a mesma URL. Esta função extrai só o que o agente precisa e descarta o
resto, em especial as mensagens enviadas pela própria sessão (fromMe), que
senão fariam o agente responder às próprias respostas.

Formato esperado (evento "message"):
    {"event": "message", "session": "default",
     "payload": {"id": "false_5511...@c.us_AAAA", "from": "5511...@c.us",
                 "to": "5599...@c.us", "fromMe": false, "body": "Oi",
                 "hasMedia": false,
                 "media": {"url": "http://waha:3000/api/files/...",
                           "mimetype": "audio/ogg; codecs=opus"}}}
"""

from dataclasses import dataclass


@dataclass
class WahaInbound:
    """Mensagem de entrada já normalizada."""

    message_id: str
    chat_id: str
    phone_number: str
    to_number: str
    body: str
    media_url: str | None = None
    media_type: str | None = None


@dataclass
class WahaIgnored:
    """Evento que deve ser aceito (200) mas não processado."""

    reason: str


def phone_from_chat_id(chat_id: str) -> str:
    """Converte 5511999999999@c.us em +5511999999999.

    IDs @lid (endereçamento anônimo do WhatsApp) não são telefones; são
    mantidos como vieram para servir de identidade estável da conversa.
    """
    user, _, domain = chat_id.partition("@")
    if domain == "c.us":
        return f"+{user}"
    return chat_id


def parse_waha_event(event: dict) -> WahaInbound | WahaIgnored:
    """Extrai a mensagem de um evento do WAHA, ou diz por que ignorar."""
    if event.get("event") != "message":
        return WahaIgnored(f"event:{event.get('event')}")

    payload = event.get("payload")
    if not isinstance(payload, dict):
        return WahaIgnored("no_payload")

    if payload.get("fromMe"):
        return WahaIgnored("from_me")

    chat_id = str(payload.get("from") or "")
    if not chat_id.endswith(("@c.us", "@lid")):
        # Grupos (@g.us), canais (@newsletter), status@broadcast etc.
        return WahaIgnored("unsupported_chat")

    body = str(payload.get("body") or "")
    media_url = None
    media_type = None
    media = payload.get("media")
    if payload.get("hasMedia") and isinstance(media, dict) and media.get("url"):
        media_url = str(media["url"]).strip()
        mimetype = str(media.get("mimetype") or "")
        # "audio/ogg; codecs=opus" -> "audio/ogg"
        media_type = mimetype.split(";")[0].strip() or None

    if not body and not media_url:
        # Mensagem vazia ou mídia sem arquivo (download de mídia desligado no WAHA)
        return WahaIgnored("empty")

    return WahaInbound(
        message_id=str(payload.get("id") or ""),
        chat_id=chat_id,
        phone_number=phone_from_chat_id(chat_id),
        to_number=phone_from_chat_id(str(payload.get("to") or "")),
        body=body,
        media_url=media_url,
        media_type=media_type,
    )
