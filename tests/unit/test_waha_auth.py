"""Testes da autenticação do webhook WAHA (HMAC e token)."""

import hashlib
import hmac
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from whatsapp_langchain.server.dependencies import verify_waha_webhook
from whatsapp_langchain.shared.config import settings

BODY = b'{"event":"message"}'


def _request(headers=None, body=BODY):
    request = MagicMock()
    request.headers = headers or {}

    async def read():
        return body

    request.body = read
    return request


@pytest.fixture(autouse=True)
def no_secrets(monkeypatch):
    monkeypatch.setattr(settings, "waha_webhook_hmac_key", None)
    monkeypatch.setattr(settings, "waha_webhook_token", None)


def _sig(key, body=BODY, algo="sha512"):
    return hmac.new(key.encode(), body, getattr(hashlib, algo)).hexdigest()


async def test_open_when_nothing_configured():
    await verify_waha_webhook(_request())


class TestHmac:
    @pytest.fixture(autouse=True)
    def key(self, monkeypatch):
        monkeypatch.setattr(settings, "waha_webhook_hmac_key", SecretStr("s3cret"))

    async def test_valid_sha512(self):
        await verify_waha_webhook(_request({"X-Webhook-Hmac": _sig("s3cret")}))

    async def test_valid_sha256_when_declared(self):
        headers = {
            "X-Webhook-Hmac": _sig("s3cret", algo="sha256"),
            "X-Webhook-Hmac-Algorithm": "sha256",
        }
        await verify_waha_webhook(_request(headers))

    async def test_missing_signature_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await verify_waha_webhook(_request())
        assert exc.value.status_code == 403

    async def test_tampered_body_rejected(self):
        headers = {"X-Webhook-Hmac": _sig("s3cret")}
        with pytest.raises(HTTPException) as exc:
            await verify_waha_webhook(_request(headers, body=b"{}"))
        assert exc.value.status_code == 403

    async def test_unknown_algorithm_rejected(self):
        headers = {"X-Webhook-Hmac": "x", "X-Webhook-Hmac-Algorithm": "md5"}
        with pytest.raises(HTTPException):
            await verify_waha_webhook(_request(headers))


class TestToken:
    @pytest.fixture(autouse=True)
    def token(self, monkeypatch):
        monkeypatch.setattr(settings, "waha_webhook_token", SecretStr("tok"))

    async def test_valid_token(self):
        await verify_waha_webhook(_request({"X-Webhook-Token": "tok"}))

    async def test_wrong_or_missing_token_rejected(self):
        for headers in ({"X-Webhook-Token": "nope"}, {}):
            with pytest.raises(HTTPException) as exc:
                await verify_waha_webhook(_request(headers))
            assert exc.value.status_code == 403
