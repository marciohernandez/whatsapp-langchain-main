# Integração Twilio — Setup, Webhook e Cloudflared

Guia para configurar o envio e recebimento de mensagens WhatsApp via Twilio.

## Visão geral

```
Usuário WhatsApp
       │
       ▼
Twilio (nuvem)
       │  POST /webhook/twilio?agent=rhawk_assistant
       │  X-Twilio-Signature: <HMAC-SHA1>
       ▼
cloudflared tunnel ──► API (localhost:8000)
                              │
                              ▼
                       PostgreSQL (fila)
                              │
                              ▼
                       Worker ──► TwilioClient.send_typing()
                              │
                              ▼
                       graph.ainvoke()
                              │
                              ▼
                       TwilioClient.send_message() ──► WhatsApp
```

## 1. Pré-requisitos

- Conta Twilio com sandbox WhatsApp ativa
- `cloudflared` instalado ([download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/))
- Stack local rodando (`make up` ou `make db` + `make api` + `make worker`)

### 1.1 Criar conta Twilio (do zero)

1. Acesse [Twilio Console](https://console.twilio.com/) e clique em **Sign up**.
2. Confirme e-mail e telefone.
3. No onboarding, siga o fluxo padrão até chegar no dashboard.
4. Se sua conta estiver em trial, mantenha o trial ativo (é suficiente para sandbox).

> Dica (Brasil): se a confirmação por SMS falhar, tente validação por ligação de voz.

### 1.2 Obter credenciais no Console (SID, Token e API Key)

1. No Dashboard, copie:
   - `Account SID` (começa com `AC`)
   - `Auth Token` (clique em **Show** para revelar)
2. Vá em **Account → API keys & tokens** e clique em **Create API Key**.
3. Preencha:
   - **Friendly name**: ex. `tophawks-whatsapp-worker`
   - **Region**: `United States - Default`
   - **Key type**: prefira `Standard`/`Main` quando disponível.
4. Se só aparecer `Restricted`, selecione permissões mínimas de envio:
   - Produto `Messaging`
   - Recurso `Messages` com permissão `Create` (opcional `Read` para debug)
5. Crie a key e copie:
   - `API Key SID` (começa com `SK`)
   - `API Key Secret`

> O `API Key Secret` aparece apenas uma vez. Guarde imediatamente.

## 2. Variáveis de ambiente

A autenticação Twilio é dividida em dois contextos:

- **Outbound** (Worker → Twilio): usa API Key (`TWILIO_API_KEY_SID` + `TWILIO_API_KEY_SECRET`)
- **Inbound** (validação de assinatura): usa `TWILIO_AUTH_TOKEN`

Todas as variáveis Twilio no `.env`:

```bash
# === Twilio ===
# Account SID (Console → Account Info)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# --- Outbound (Worker → Twilio Messages API) ---
# API Key: Console → Account → API keys & tokens → Create API Key
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Número WhatsApp do sandbox (Console → Messaging → Try it out → WhatsApp)
TWILIO_FROM_NUMBER=whatsapp:+14155238886

# --- Inbound (validação de assinatura no webhook) ---
# Auth Token: Console → Account Info (para HMAC-SHA1)
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Habilitar validação de assinatura em produção
VALIDATE_TWILIO_SIGNATURE=false

# URL pública base do túnel — apenas o domínio, sem path
# (ex: https://abc.trycloudflare.com, NÃO incluir /webhook/twilio)
TWILIO_WEBHOOK_URL=
```

**Onde encontrar:**
- `TWILIO_ACCOUNT_SID` e `TWILIO_AUTH_TOKEN`: [Console Twilio](https://console.twilio.com/) → Account Info
- `TWILIO_API_KEY_SID` e `TWILIO_API_KEY_SECRET`: Console → Account → API keys & tokens → Create API Key
- `TWILIO_FROM_NUMBER`: Console → Messaging → Try it out → Send a WhatsApp message

## 3. Ativar sandbox WhatsApp

1. Acesse [Twilio Console → WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn)
2. Envie a mensagem de ativação (ex: "join <código>") do seu celular para o número do sandbox
3. Confirme que o sandbox está ativo (status "Connected")
4. Copie o número do sandbox exibido na tela (ex: `+1 415 523 8886`) e configure:
   - `TWILIO_FROM_NUMBER=whatsapp:+14155238886`

> O sandbox tem validade de 72h. Se parar de funcionar, reenvie a mensagem de ativação.

## 4. Túnel local com cloudflared

Cloudflared cria um túnel público → localhost sem necessidade de conta Cloudflare.

```bash
# Iniciar túnel (porta da API)
cloudflared tunnel --url http://localhost:8000
```

Saída esperada:
```
INF +----------------------------+
INF |  Your quick Tunnel has been created! Visit it at:
INF |  https://random-name.trycloudflare.com
INF +----------------------------+
```

Copie a URL gerada (ex: `https://random-name.trycloudflare.com`) e configure no `.env`:

```bash
TWILIO_WEBHOOK_URL=https://random-name.trycloudflare.com
```

> A URL muda a cada reinício do cloudflared. Se reiniciar, atualize `.env` e o webhook no Twilio Console.

### Por que cloudflared e não ngrok?

- Zero config: não precisa de conta, token ou login
- Sem limites de rate no free tier
- Mesmo protocolo (HTTPS com cert válido)
- Suporte nativo a HTTP/2

## 5. Configurar webhook no Twilio

1. Acesse [Twilio Console → WhatsApp Sandbox Settings](https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox)
2. Em "When a message comes in", configure:
   ```
   https://random-name.trycloudflare.com/webhook/twilio?agent=rhawk_assistant
   ```
   Método: **HTTP POST**
3. Salve

### Validar que o tunnel está funcionando

```bash
curl https://random-name.trycloudflare.com/health
# {"status":"ok","database":"connected","version":"0.1.0"}
```

## 6. Teste ponta a ponta

### 6.1 Fluxo simulado (sem Twilio real)

```bash
# Simula o que o Twilio enviaria
curl -X POST "http://localhost:8000/webhook/twilio?agent=rhawk_assistant" \
  -d "MessageSid=SMTEST001" \
  -d "From=whatsapp:+5511999999999" \
  -d "To=whatsapp:+14155238886" \
  -d "Body=Olá, teste local" \
  -d "NumMedia=0"
```

Verifique:
```bash
curl http://localhost:8000/api/chats/+5511999999999
```

> Neste modo, VALIDATE_TWILIO_SIGNATURE deve estar `false` (padrão).

### 6.2 Fluxo real (Twilio + WhatsApp)

1. Confirme que todos os serviços estão rodando:
   ```bash
   make logs
   # api, worker e db devem estar healthy
   ```

2. Confirme o túnel:
   ```bash
   curl https://random-name.trycloudflare.com/health
   ```

3. Envie uma mensagem do WhatsApp para o número do sandbox

4. Verifique nos logs:
   ```bash
   make logs
   # Procure por: webhook_twilio_received, message_claimed, twilio_typing_sent, message_processed
   ```

5. A resposta do agente deve chegar no WhatsApp (se `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` e `TWILIO_FROM_NUMBER` estiverem configurados)

### 6.3 Habilitar validação de assinatura

Para testar com validação real:

```bash
VALIDATE_TWILIO_SIGNATURE=true
TWILIO_AUTH_TOKEN=<seu-auth-token>
TWILIO_WEBHOOK_URL=https://random-name.trycloudflare.com
```

Reinicie a API (`make api` ou `docker compose restart api`).

Teste que assinatura inválida é rejeitada:
```bash
curl -X POST "https://random-name.trycloudflare.com/webhook/twilio?agent=rhawk_assistant" \
  -d "MessageSid=SMFAKE" \
  -d "From=whatsapp:+5511999999999" \
  -d "Body=Teste sem assinatura" \
  -d "NumMedia=0"
# Deve retornar 403 (Missing Twilio signature)
```

## 7. Variáveis por serviço

| Variável | API | Worker | Obrigatória |
|---|---|---|---|
| `DATABASE_URL` | sim | sim | sim |
| `OPENROUTER_API_KEY` | não | sim | sim (para agente) |
| `TWILIO_ACCOUNT_SID` | não | sim | **sim** |
| `TWILIO_API_KEY_SID` | não | sim | **sim** |
| `TWILIO_API_KEY_SECRET` | não | sim | **sim** |
| `TWILIO_FROM_NUMBER` | não | sim | **sim** |
| `TWILIO_AUTH_TOKEN` | sim* | não | se validação ativa |
| `TWILIO_WEBHOOK_URL` | sim* | não | se validação ativa |
| `VALIDATE_TWILIO_SIGNATURE` | sim | não | não (default: false) |

\* Usada pela dependency de validação de assinatura no webhook.

> **Fase 3:** Twilio é obrigatório no Worker. O Worker faz fail-fast na inicialização se `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` ou `TWILIO_FROM_NUMBER` estiverem vazios. Nenhum `mark_done` ocorre sem envio Twilio confirmado.

## 8. Debounce e mídia

Regras de debounce da Fase 3:

- **Texto**: mensagens rápidas do mesmo phone+agent são agrupadas (concatenadas) dentro da janela de `MESSAGE_BUFFER_SECONDS` (padrão: 2s)
- **Mídia**: entra imediatamente (sem debounce). Antes de inserir mídia, textos pendentes do mesmo phone+agent são "flushed" (processados imediatamente)
- **Ordem**: o worker processa por `created_at ASC`, então texto flushed sai antes da mídia
- **Concorrência**: `pg_advisory_xact_lock(hash(phone+agent))` serializa operações do mesmo remetente/agente, impedindo race conditions entre webhooks simultâneos

Exemplo de fluxo:
```
T=0.0s  Texto "Oi"           → enfileira, process_after=T+2s
T=0.5s  Texto "Olha isso"    → debounce: "Oi\nOlha isso", process_after=T+2.5s
T=1.0s  Imagem (foto.jpg)    → flush texto (process_after=NOW), insere mídia (NOW)
T=1.1s  Worker pega texto    → processa "Oi\nOlha isso"
T=1.2s  Worker pega imagem   → processa foto.jpg
```

### Download de mídia

O worker autentica o download de mídia do Twilio com API Key (`TWILIO_API_KEY_SID` + `TWILIO_API_KEY_SECRET`). Sem autenticação, o download retorna 401 Unauthorized.

## 9. Limitações conhecidas

### NumMedia > 1

Se o Twilio enviar um webhook com `NumMedia > 1` (múltiplas mídias no mesmo webhook), apenas a primeira mídia (`MediaUrl0`, `MediaContentType0`) é processada. As demais são ignoradas.

Este é um tradeoff consciente desta fase — o template educacional foca em clareza do fluxo single-media. Suporte a multi-media pode ser adicionado em fases futuras.

### Typing indicator

O `TwilioClient.send_typing()` usa o endpoint **Public Beta** do Twilio (lançado out/2025):

```
POST https://messaging.twilio.com/v2/Indicators/Typing.json
```

Parâmetros: `messageId` (SID da mensagem inbound) + `channel=whatsapp`.

Efeitos no WhatsApp do usuário:
- Mensagem marcada como lida (blue checkmarks)
- Indicador "digitando..." exibido por até 25 segundos

O typing é **best-effort**: chamado antes de `graph.ainvoke()`, falha não interrompe processamento. Auth via API Key (mesmas credenciais do envio de mensagens).

> Public Beta: endpoint pode mudar antes do GA. Não é coberto pelo SLA do Twilio.

### Sandbox WhatsApp

- Validade de 72h (requer reativação periódica)
- Apenas números previamente cadastrados recebem mensagens
- Rate limits mais restritivos que produção

## 10. Troubleshooting

### Mensagem não chega no WhatsApp

1. Verifique credenciais Twilio no `.env`
2. Confirme que o sandbox está ativo (reenvie "join <código>")
3. Verifique logs do worker: `make logs | grep twilio`
4. Confirme que `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` e `TWILIO_FROM_NUMBER` estão preenchidos

### 403 no webhook

- `VALIDATE_TWILIO_SIGNATURE=true` mas `TWILIO_AUTH_TOKEN` vazio → configure o token
- `TWILIO_WEBHOOK_URL` não bate com a URL real do cloudflared → atualize após reiniciar túnel

### cloudflared desconecta

O tunnel efêmero do cloudflared pode cair. Reinicie e atualize:
1. `cloudflared tunnel --url http://localhost:8000`
2. Copie a nova URL para `TWILIO_WEBHOOK_URL` no `.env`
3. Atualize o webhook no Twilio Console
4. Reinicie a API

### Worker não inicia (fail-fast)

O worker faz fail-fast se credenciais outbound estiverem faltando. Verifique:
```bash
grep -E '^TWILIO_(ACCOUNT_SID|API_KEY_SID|API_KEY_SECRET|FROM_NUMBER)' .env
```

### Identidade inbound

O webhook usa `From` (formato `whatsapp:+55...`) como identidade primária, com fallback para `WaId` (normalizado para `+E.164`). Se o phone_number chega incorreto, verifique o payload do Twilio nos logs.
