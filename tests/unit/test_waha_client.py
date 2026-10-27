"""Testes do WahaClient (httpx mockado)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from whatsapp_langchain.worker.waha_client import WahaClient, WahaSendError


def _response(status=200, json=None, content=b"", text=""):
    response = MagicMock()
    response.is_success = 200 <= status < 300
    response.status_code = status
    response.text = text
    response.content = content
    response.json.return_value = json or {}
    response.raise_for_status.side_effect = (
        None
        if response.is_success
        else httpx.HTTPStatusError("err", request=MagicMock(), response=response)
    )
    return response


@pytest.fixture
def http():
    """Substitui httpx.AsyncClient por um mock com post/get."""
    client = AsyncMock()
    with patch("whatsapp_langchain.worker.waha_client.httpx.AsyncClient") as cls:
        cls.return_value.__aenter__.return_value = client
        yield client


@pytest.fixture
def waha():
    return WahaClient("http://waha:3000/", api_key="k", session="s1")


class TestInit:
    def test_requires_base_url(self):
        with pytest.raises(ValueError):
            WahaClient("")

    def test_strips_trailing_slash(self, waha):
        assert waha.base_url == "http://waha:3000"


class TestSendMessage:
    async def test_posts_send_text_with_api_key(self, waha, http):
        http.post.return_value = _response(json={"id": "true_x"})

        msg_id = await waha.send_message("5511@c.us", "oi")

        assert msg_id == "true_x"
        args, kwargs = http.post.call_args
        assert args[0] == "http://waha:3000/api/sendText"
        assert kwargs["headers"] == {"X-Api-Key": "k"}
        assert kwargs["json"] == {"session": "s1", "chatId": "5511@c.us", "text": "oi"}

    async def test_object_id_is_serialized(self, waha, http):
        http.post.return_value = _response(json={"id": {"_serialized": "true_y"}})
        assert await waha.send_message("5511@c.us", "oi") == "true_y"

    async def test_no_api_key_header_when_unset(self, http):
        http.post.return_value = _response(json={"id": "x"})
        await WahaClient("http://waha:3000").send_message("5511@c.us", "oi")
        assert http.post.call_args.kwargs["headers"] == {}

    async def test_error_raises(self, waha, http):
        http.post.return_value = _response(status=500, text="boom")
        with pytest.raises(WahaSendError) as exc:
            await waha.send_message("5511@c.us", "oi")
        assert exc.value.status_code == 500


class TestTyping:
    async def test_send_typing_calls_seen_and_typing(self, waha, http):
        http.post.return_value = _response()
        assert await waha.send_typing("5511@c.us") is True
        paths = [c.args[0] for c in http.post.call_args_list]
        assert paths == [
            "http://waha:3000/api/sendSeen",
            "http://waha:3000/api/startTyping",
        ]

    async def test_typing_never_raises(self, waha, http):
        http.post.side_effect = httpx.ConnectError("down")
        assert await waha.send_typing("5511@c.us") is False
        assert await waha.stop_typing("5511@c.us") is False


class TestDownloadMedia:
    async def test_uses_configured_host_not_url_host(self, waha, http):
        """A API key só vai para WAHA_BASE_URL, nunca para o host do payload."""
        http.get.return_value = _response(content=b"bytes")

        data = await waha.download_media("http://evil.example/api/files/s1/a.oga?x=1")

        assert data == b"bytes"
        args, kwargs = http.get.call_args
        assert args[0] == "http://waha:3000/api/files/s1/a.oga?x=1"
        assert kwargs["headers"] == {"X-Api-Key": "k"}
        assert kwargs["follow_redirects"] is False

    async def test_http_error_propagates(self, waha, http):
        http.get.return_value = _response(status=404)
        with pytest.raises(httpx.HTTPStatusError):
            await waha.download_media("http://waha:3000/api/files/s1/a.oga")
