"""Testes de integração do webhook — FastAPI TestClient.

Testa o fluxo de webhook sem banco de dados real.
Usa mocking para simular pool e operações de fila.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from whatsapp_langchain import __version__
from whatsapp_langchain.server.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def mock_db():
    """Mock do banco de dados para testes sem PostgreSQL."""
    mock_pool = AsyncMock()

    with (
        patch(
            "whatsapp_langchain.server.routes.health.check_db_health",
            return_value=True,
        ),
        patch(
            "whatsapp_langchain.server.routes.webhook.get_pool",
            return_value=mock_pool,
        ),
        patch(
            "whatsapp_langchain.server.routes.admin.get_pool",
            return_value=mock_pool,
        ),
        patch("whatsapp_langchain.shared.db.get_pool", return_value=mock_pool),
        patch("whatsapp_langchain.shared.db.run_migrations"),
        patch("whatsapp_langchain.shared.db.close_pool"),
    ):
        yield mock_pool


class TestHealthCheck:
    """Testes do endpoint /health."""

    def test_health_ok(self):
        """Retorna 200 quando o banco está acessível."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "database": "connected",
            "version": __version__,
        }


class TestWebhookSync:
    """Testes do webhook síncrono."""

    def test_sync_requires_agent(self):
        """Deve exigir o query param 'agent'."""
        response = client.post(
            "/webhook/sync",
            json={"phone": "+5511999999999", "message": "Olá"},
        )
        # Sem agent= -> 422 (query param obrigatório)
        assert response.status_code == 422

    def test_sync_nonexistent_agent(self):
        """Deve retornar erro para agente inexistente."""
        response = client.post(
            "/webhook/sync?agent=nao_existe",
            json={"phone": "+5511999999999", "message": "Olá"},
        )
        assert response.status_code == 400


WAHA_EVENT = {
    "event": "message",
    "session": "default",
    "payload": {
        "id": "false_5511999999999@c.us_AAA",
        "from": "5511999999999@c.us",
        "to": "5511888888888@c.us",
        "fromMe": False,
        "body": "Olá",
        "hasMedia": False,
    },
}


class TestWebhookWaha:
    """Testes do webhook WAHA."""

    def test_waha_requires_agent(self):
        """Deve exigir o query param 'agent'."""
        response = client.post("/webhook/waha", json=WAHA_EVENT)
        assert response.status_code == 422

    def test_waha_nonexistent_agent(self):
        """Deve retornar erro para agente inexistente."""
        response = client.post("/webhook/waha?agent=nao_existe", json=WAHA_EVENT)
        assert response.status_code == 400

    def test_waha_invalid_json(self):
        response = client.post("/webhook/waha?agent=rhawk_assistant", content=b"x")
        assert response.status_code == 400

    @patch("whatsapp_langchain.server.routes.webhook.register_inbound_message")
    @patch("whatsapp_langchain.server.routes.webhook.enqueue_or_buffer")
    def test_waha_enqueues_message(self, mock_enqueue, mock_register):
        """Deve enfileirar a mensagem com o chat_id para resposta."""
        from whatsapp_langchain.shared.models import EnqueueResult

        mock_register.return_value = True
        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)

        response = client.post("/webhook/waha?agent=rhawk_assistant", json=WAHA_EVENT)

        assert response.status_code == 200
        assert response.json() == {"status": "queued"}
        kwargs = mock_enqueue.call_args.kwargs
        assert kwargs["phone_number"] == "+5511999999999"
        assert kwargs["chat_id"] == "5511999999999@c.us"
        assert kwargs["message_id"] == "false_5511999999999@c.us_AAA"

    @patch("whatsapp_langchain.server.routes.webhook.register_inbound_message")
    @patch("whatsapp_langchain.server.routes.webhook.enqueue_or_buffer")
    def test_waha_duplicate_is_not_enqueued(self, mock_enqueue, mock_register):
        mock_register.return_value = False

        response = client.post("/webhook/waha?agent=rhawk_assistant", json=WAHA_EVENT)

        assert response.json() == {"status": "duplicate"}
        mock_enqueue.assert_not_called()

    @patch("whatsapp_langchain.server.routes.webhook.forget_inbound_message")
    @patch("whatsapp_langchain.server.routes.webhook.register_inbound_message")
    @patch("whatsapp_langchain.server.routes.webhook.enqueue_or_buffer")
    def test_waha_enqueue_failure_releases_dedupe(
        self, mock_enqueue, mock_register, mock_forget
    ):
        """Falha no enqueue → 500 e o ID é liberado para a reentrega do WAHA."""
        mock_register.return_value = True
        mock_enqueue.side_effect = RuntimeError("db down")

        response = client.post("/webhook/waha?agent=rhawk_assistant", json=WAHA_EVENT)

        assert response.status_code == 500
        mock_forget.assert_awaited_once()

    @patch("whatsapp_langchain.server.routes.webhook.enqueue_or_buffer")
    def test_waha_ignores_own_messages(self, mock_enqueue):
        event = {**WAHA_EVENT, "payload": {**WAHA_EVENT["payload"], "fromMe": True}}

        response = client.post("/webhook/waha?agent=rhawk_assistant", json=event)

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        mock_enqueue.assert_not_called()

    @patch("whatsapp_langchain.server.routes.webhook.register_inbound_message")
    @patch("whatsapp_langchain.server.routes.webhook.enqueue_or_buffer")
    def test_waha_rate_limited_returns_200(self, mock_enqueue, mock_register):
        """429 faria o WAHA reentregar; respondemos 200 e descartamos."""
        from fastapi import HTTPException

        with patch(
            "whatsapp_langchain.server.routes.webhook.check_rate_limit",
            side_effect=HTTPException(status_code=429),
        ):
            response = client.post(
                "/webhook/waha?agent=rhawk_assistant", json=WAHA_EVENT
            )

        assert response.json() == {"status": "rate_limited"}
        mock_enqueue.assert_not_called()

    @patch("whatsapp_langchain.server.routes.webhook.register_inbound_message")
    @patch("whatsapp_langchain.server.routes.webhook.enqueue_or_buffer")
    def test_waha_rejects_bad_token(self, mock_enqueue, mock_register, monkeypatch):
        from pydantic import SecretStr

        from whatsapp_langchain.shared.models import EnqueueResult

        mock_register.return_value = True
        mock_enqueue.return_value = EnqueueResult(message_id=1)

        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "waha_webhook_token", SecretStr("tok"))

        response = client.post("/webhook/waha?agent=rhawk_assistant", json=WAHA_EVENT)
        assert response.status_code == 403

        response = client.post(
            "/webhook/waha?agent=rhawk_assistant",
            json=WAHA_EVENT,
            headers={"X-Webhook-Token": "tok"},
        )
        assert response.status_code == 200


class TestAdminRoutes:
    """Testes das rotas administrativas."""

    def test_list_agents(self):
        """Deve listar agentes disponíveis."""
        response = client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "rhawk_assistant" in data["agents"]
