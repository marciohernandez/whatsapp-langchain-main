"""Cliente assíncrono para o WAHA (WhatsApp HTTP API).

Usa httpx para chamadas não-bloqueantes à API REST do WAHA. Cada instância
do cliente é fixada em uma sessão (WAHA_SESSION); a autenticação é feita pelo
header X-Api-Key quando WAHA_API_KEY está configurada.

Uso:
    from whatsapp_langchain.worker.waha_client import WahaClient

    client = WahaClient(base_url="http://waha:3000", api_key="...", session="default")
    msg_id = await client.send_message("5511999999999@c.us", "Olá!")
    await client.send_typing("5511999999999@c.us")
"""

from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger()


class WahaSendError(Exception):
    """Erro ao chamar a API do WAHA.

    Encapsula status HTTP e body de erro para facilitar diagnóstico.
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"WAHA API error {status_code}: {detail}")


class WahaClient:
    """Cliente do WAHA fixado em uma sessão.

    Args:
        base_url: URL base do WAHA alcançável pelo worker (ex: http://waha:3000).
        api_key: Valor do header X-Api-Key (vazio se o WAHA roda sem auth).
        session: Nome da sessão WAHA que envia as mensagens.
    """

    def __init__(self, base_url: str, api_key: str = "", session: str = "default"):
        if not base_url:
            raise ValueError("base_url não pode ser vazio")
        if not session:
            raise ValueError("session não pode ser vazio")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    async def send_message(self, chat_id: str, body: str) -> str:
        """Envia texto via POST /api/sendText.

        Args:
            chat_id: chatId de destino (ex: 5511999999999@c.us).
            body: Texto da mensagem.

        Returns:
            ID da mensagem criada no WAHA (string vazia se não vier na resposta).

        Raises:
            WahaSendError: Se a API retornar erro (4xx/5xx).
        """
        async with httpx.AsyncClient() as http:
            response = await http.post(
                f"{self.base_url}/api/sendText",
                headers=self._headers,
                json={"session": self.session, "chatId": chat_id, "text": body},
                timeout=15.0,
            )

        if not response.is_success:
            detail = response.text[:500]
            logger.error(
                "waha_send_failed",
                chat_id=chat_id,
                status_code=response.status_code,
                detail=detail,
            )
            raise WahaSendError(response.status_code, detail)

        data = response.json()
        # Dependendo do engine, "id" vem como string ou como objeto com _serialized
        raw_id = data.get("id", "")
        message_id = (
            raw_id.get("_serialized", "") if isinstance(raw_id, dict) else raw_id
        )

        logger.info("waha_message_sent", chat_id=chat_id, message_id=message_id)
        return message_id

    async def _post_best_effort(self, path: str, chat_id: str) -> bool:
        try:
            async with httpx.AsyncClient() as http:
                response = await http.post(
                    f"{self.base_url}{path}",
                    headers=self._headers,
                    json={"session": self.session, "chatId": chat_id},
                    timeout=5.0,
                )
        except Exception as exc:
            logger.warning(
                "waha_call_error", path=path, chat_id=chat_id, error=str(exc)
            )
            return False

        if response.is_success:
            return True

        logger.warning(
            "waha_call_failed",
            path=path,
            chat_id=chat_id,
            status_code=response.status_code,
            detail=response.text[:200],
        )
        return False

    async def send_typing(self, chat_id: str) -> bool:
        """Marca a conversa como lida e exibe "digitando..." (best-effort).

        Chama /api/sendSeen e /api/startTyping. Nunca levanta exceção.

        Returns:
            True se o "digitando..." foi enviado, False caso contrário.
        """
        await self._post_best_effort("/api/sendSeen", chat_id)
        return await self._post_best_effort("/api/startTyping", chat_id)

    async def stop_typing(self, chat_id: str) -> bool:
        """Remove o "digitando..." (best-effort). Nunca levanta exceção."""
        return await self._post_best_effort("/api/stopTyping", chat_id)

    async def download_media(self, media_url: str) -> bytes:
        """Baixa uma mídia entregue pelo WAHA.

        Só o *path* da URL do webhook é usado; o host vem de WAHA_BASE_URL.
        Assim a API key nunca é enviada a um host escolhido por quem chamou o
        webhook, e o WAHA pode anunciar uma URL pública diferente da interna.
        """
        parsed = urlparse(media_url)
        url = f"{self.base_url}{parsed.path}"
        if parsed.query:
            url = f"{url}?{parsed.query}"

        async with httpx.AsyncClient() as http:
            response = await http.get(
                url,
                headers=self._headers,
                follow_redirects=False,
                timeout=30.0,
            )
        response.raise_for_status()
        return response.content
