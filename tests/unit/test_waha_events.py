"""Testes da normalização de eventos do WAHA."""

from whatsapp_langchain.server.waha_events import (
    WahaIgnored,
    WahaInbound,
    parse_waha_event,
    phone_from_chat_id,
)


def _event(**payload_overrides):
    payload = {
        "id": "false_5511999999999@c.us_AAA",
        "from": "5511999999999@c.us",
        "to": "5511888888888@c.us",
        "fromMe": False,
        "body": "Olá",
        "hasMedia": False,
    }
    payload.update(payload_overrides)
    return {"event": "message", "session": "default", "payload": payload}


class TestParseWahaEvent:
    def test_text_message(self):
        result = parse_waha_event(_event())
        assert isinstance(result, WahaInbound)
        assert result.message_id == "false_5511999999999@c.us_AAA"
        assert result.chat_id == "5511999999999@c.us"
        assert result.phone_number == "+5511999999999"
        assert result.to_number == "+5511888888888"
        assert result.body == "Olá"
        assert result.media_url is None

    def test_ignores_from_me(self):
        """Evita loop: o WAHA também notifica as mensagens enviadas pelo bot."""
        result = parse_waha_event(_event(fromMe=True))
        assert result == WahaIgnored("from_me")

    def test_ignores_non_message_events(self):
        result = parse_waha_event({"event": "message.ack", "payload": {}})
        assert isinstance(result, WahaIgnored)
        assert result.reason == "event:message.ack"

    def test_ignores_groups_and_status(self):
        for chat in ("120363@g.us", "status@broadcast", "123@newsletter"):
            result = parse_waha_event(_event(**{"from": chat}))
            assert result == WahaIgnored("unsupported_chat")

    def test_ignores_empty_message(self):
        assert parse_waha_event(_event(body="")) == WahaIgnored("empty")

    def test_media_message_strips_codec_from_mimetype(self):
        result = parse_waha_event(
            _event(
                body="",
                hasMedia=True,
                media={
                    "url": "http://waha:3000/api/files/default/a.oga",
                    "mimetype": "audio/ogg; codecs=opus",
                },
            )
        )
        assert isinstance(result, WahaInbound)
        assert result.media_url == "http://waha:3000/api/files/default/a.oga"
        assert result.media_type == "audio/ogg"

    def test_media_without_file_keeps_caption(self):
        """Download de mídia desligado no WAHA: só a legenda é aproveitada."""
        result = parse_waha_event(_event(body="legenda", hasMedia=True, media=None))
        assert isinstance(result, WahaInbound)
        assert result.body == "legenda"
        assert result.media_url is None

    def test_lid_chat_is_kept_as_identity(self):
        result = parse_waha_event(_event(**{"from": "99887766@lid"}))
        assert isinstance(result, WahaInbound)
        assert result.phone_number == "99887766@lid"
        assert result.chat_id == "99887766@lid"

    def test_invalid_payload(self):
        assert parse_waha_event({"event": "message"}) == WahaIgnored("no_payload")


def test_phone_from_chat_id():
    assert phone_from_chat_id("5511999999999@c.us") == "+5511999999999"
