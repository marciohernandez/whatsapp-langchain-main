# Integração WAHA

O projeto recebe e envia mensagens de WhatsApp através do [WAHA](https://waha.devlike.pro/)
(WhatsApp HTTP API) que você já tem rodando na sua infra.

**Modelo de deploy:** um deploy deste projeto = um agente = uma sessão WAHA.
Para outro agente/número, suba outro deploy apontando para outra sessão.

```text
WhatsApp ─► WAHA ─POST /webhook/waha?agent=<id>─► API ─► PostgreSQL ─► Worker ─► Agente
                                                                         │
WhatsApp ◄─ WAHA ◄─────── /api/sendText, /api/startTyping ───────────────┘
```

## 1. Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `WAHA_BASE_URL` | sim (worker) | URL do WAHA alcançável **pelo worker**, ex: `http://waha:3000` |
| `WAHA_API_KEY` | se o WAHA exige | Enviada no header `X-Api-Key` |
| `WAHA_SESSION` | não | Nome da sessão (default `default`) |
| `WAHA_WEBHOOK_HMAC_KEY` | recomendado | Chave HMAC do webhook (ver abaixo) |
| `WAHA_WEBHOOK_TOKEN` | opcional | Token estático no header `X-Webhook-Token` |

Se nem `WAHA_WEBHOOK_HMAC_KEY` nem `WAHA_WEBHOOK_TOKEN` estiverem definidos, o
webhook aceita qualquer request. **Use isso apenas em desenvolvimento local.**

## 2. Configurar o webhook no WAHA

Na sessão do WAHA (via dashboard, `POST /api/sessions` ou `WHATSAPP_HOOK_*`):

```json
{
  "name": "default",
  "config": {
    "webhooks": [
      {
        "url": "http://api:8000/webhook/waha?agent=rhawk_assistant",
        "events": ["message"],
        "hmac": { "key": "MESMO_VALOR_DE_WAHA_WEBHOOK_HMAC_KEY" },
        "customHeaders": [{ "name": "X-Webhook-Token", "value": "MESMO_VALOR_DE_WAHA_WEBHOOK_TOKEN" }]
      }
    ]
  }
}
```

- Assine **apenas** o evento `message`. Outros eventos são aceitos e ignorados, mas geram tráfego inútil.
- `hmac` e `customHeaders` são independentes: configure um ou ambos, junto com a variável correspondente.
- Para mídia (imagem/áudio), mantenha o download de mídia ligado no WAHA
  (`WHATSAPP_DOWNLOAD_MEDIA=true`); sem arquivo, só a legenda chega ao agente.

## 3. O que o webhook faz

`POST /webhook/waha?agent=<id>` (JSON) responde sempre `200` com `{"status": ...}`:

| status | Significado |
|---|---|
| `queued` / `buffered` | Mensagem enfileirada (ou concatenada a outra pendente pelo debounce) |
| `duplicate` | O WAHA reentregou um ID já aceito (dedupe na tabela `inbound_dedupe`) |
| `rate_limited` | Limite por telefone excedido; descartada (200 evita reentrega pelo WAHA) |
| `ignored` | Não é mensagem de usuário: `fromMe`, grupos, canais, status, acks, mensagem vazia |

Erros reais: `400` (JSON inválido ou agente inexistente), `403` (HMAC/token), `500` (falha ao enfileirar;
o WAHA reentrega e o ID é liberado do dedupe).

## 4. Identidade e resposta

- `from: 5511999999999@c.us` → `phone_number = +5511999999999`, usado em `thread_id` e `user_id`.
- O `chatId` original fica em `message_queue.chat_id` e é o destino da resposta.
- IDs `@lid` (endereçamento anônimo do WhatsApp) não são telefones: são guardados como vieram
  (`123@lid`) e funcionam como identidade da conversa.
- Grupos (`@g.us`) são ignorados.

## 5. Teste manual

```bash
curl -X POST "http://localhost:8000/webhook/waha?agent=rhawk_assistant" \
  -H "Content-Type: application/json" \
  -d '{"event":"message","session":"default","payload":{
        "id":"false_5511999999999@c.us_TESTE1","from":"5511999999999@c.us",
        "to":"5500000000000@c.us","fromMe":false,"body":"Olá!","hasMedia":false}}'
```

Com o worker rodando e `WAHA_BASE_URL` válido, a resposta é enviada ao `chatId` informado.

## 6. Observações

- O worker usa `POST /api/sendText`, `/api/sendSeen`, `/api/startTyping` e `/api/stopTyping`.
  Typing é best-effort: falha não interrompe a resposta.
- Mídia é baixada de `WAHA_BASE_URL` + *path* da URL do payload. O host do payload é
  ignorado de propósito: a API key só é enviada ao WAHA configurado.
- Os caminhos acima seguem a API do WAHA; confirme na documentação da sua versão/engine
  (WEBJS, NOWEB, GOWS) caso algum endpoint responda 404.
