# Primeiros Passos

Este guia tem duas trilhas:
- **Trilha A (agentes):** LangGraph Studio para desenvolver comportamento
- **Trilha B (sistema):** API + Worker + DB para aprender arquitetura operacional

## Pré-requisitos

- Python 3.11+
- `uv` (gerenciador de pacotes)
- Docker + Docker Compose
- conta OpenRouter (API key)
- conta Twilio com sandbox WhatsApp (obrigatória para o Worker — veja [Integração Twilio](TWILIO.md), seções 1.1 e 1.2 para criação de conta/credenciais)

## 1. Setup local

```bash
git clone <repo-url>
cd whatsapp-langchain
make setup
cp .env.example .env
```

Edite `.env` e configure no mínimo:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MIDIA_MODEL=google/gemini-2.5-flash-lite

# Twilio (obrigatório para o Worker)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=whatsapp:+14155238886
```

## 2. Trilha A: desenvolvimento de agente no Studio

```bash
make dev
# abre o LangGraph Studio
```

O grafo padrão é `rhawk_assistant`, registrado em `langgraph.json`.

Arquivos centrais do agente:
- `src/whatsapp_langchain/agents/catalog/rhawk_assistant/agent.py`
- `src/whatsapp_langchain/agents/catalog/rhawk_assistant/prompts.py`
- `src/whatsapp_langchain/agents/catalog/rhawk_assistant/graph.py`

## 3. Trilha B: stack completo da Fase 2

### Subir serviços

```bash
make up
```

Isso sobe:
- `db` (PostgreSQL + pgvector)
- `api` (FastAPI)
- `worker` (consumidor da fila)

### Reset completo do ambiente Docker

Para reiniciar do zero (incluindo volume do PostgreSQL e dados):

```bash
make reset
```

### Validar saúde

```bash
curl http://localhost:8000/health
```

### Ver logs

```bash
make logs
```

## 4. Testes de fluxo

### 4.1 Endpoint síncrono (didático)

```bash
curl -X POST "http://localhost:8000/webhook/sync?agent=rhawk_assistant" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+5511999999999","message":"Me explique debounce"}'
```

Use para debugging rápido sem fila.

### 4.2 Webhook assíncrono (arquitetura real)

```bash
curl -X POST "http://localhost:8000/webhook/twilio?agent=rhawk_assistant" \
  -d "MessageSid=SM123" \
  -d "From=whatsapp:+5511999999999" \
  -d "To=whatsapp:+14155238886" \
  -d "Body=Mensagem de teste" \
  -d "NumMedia=0"
```

Depois consulte:

```bash
curl http://localhost:8000/api/metrics
curl http://localhost:8000/api/chats
curl http://localhost:8000/api/chats/+5511999999999
```

### 4.2.1 Teste manual no Swagger (`/docs`)

1. Abra `http://localhost:8000/docs`.
2. Execute `GET /api/agents` e confirme `rhawk_assistant`.
3. Abra `POST /webhook/twilio` e clique em `Try it out`.
4. Preencha:
   - `agent` (query): `rhawk_assistant`
   - `MessageSid`: `SMDOCS001`
   - `From`: `whatsapp:+5511999999999`
   - `To`: `whatsapp:+14155238886`
   - `Body`: `Mensagem de teste via Swagger`
   - `NumMedia`: `0`
5. Execute e verifique:
   - resposta `200` com TwiML vazio
   - dados em `GET /api/chats/+5511999999999`

### 4.3 Teste de memória semântica (save + recall via tools)

1. Envie uma mensagem pedindo para salvar um fato:

```bash
curl -X POST "http://localhost:8000/webhook/twilio?agent=rhawk_assistant" \
  -d "MessageSid=SMMEM001" \
  -d "From=whatsapp:+5511999999999" \
  -d "To=whatsapp:+14155238886" \
  -d "Body=Use a ferramenta save_memory e salve este fato: meu código é codex-12345" \
  -d "NumMedia=0"
```

2. Envie outra mensagem pedindo recall explícito:

```bash
curl -X POST "http://localhost:8000/webhook/twilio?agent=rhawk_assistant" \
  -d "MessageSid=SMMEM002" \
  -d "From=whatsapp:+5511999999999" \
  -d "To=whatsapp:+14155238886" \
  -d "Body=Sem salvar nada novo agora, use read_memory e me diga meu código" \
  -d "NumMedia=0"
```

3. Verifique evidências no banco:

```sql
SELECT prefix, value->>'memory' AS memory, updated_at
FROM store
WHERE prefix = '+5511999999999.memories'
ORDER BY updated_at DESC;

SELECT id, message_id, status, response
FROM message_queue
WHERE phone_number = '+5511999999999'
ORDER BY id DESC
LIMIT 5;
```

## 5. Configurações importantes (.env)

### Contexto

```bash
CONTEXT_STRATEGY=trim            # trim | summarize | none
TRIM_KEEP_TURNS=5
SUMMARIZE_TRIGGER_TOKENS=4000
SUMMARIZE_KEEP_MESSAGES=10
SUMMARIZE_MODEL=x-ai/grok-4.1-fast
```

### Memória semântica

```bash
MEMORY_ENABLED=true
# Use o modelo de embedding que está ativo no seu .env
# (deve bater com as dimensões abaixo)
EMBEDDING_MODEL=<modelo-de-embedding-em-uso>
EMBEDDING_DIMS=<dims-do-modelo>
MEMORY_SEARCH_LIMIT=5
```

Para evitar divergência de documentação vs ambiente, confirme os valores ativos:

```bash
grep -E '^EMBEDDING_MODEL|^EMBEDDING_DIMS' .env
```

### Operação da fila

```bash
MESSAGE_BUFFER_SECONDS=2.0
POLL_INTERVAL_SECONDS=1.0
LEASE_SECONDS=60
MAX_ATTEMPTS=3
RATE_LIMIT_PER_HOUR=30
```

## 6. Qualidade e testes

```bash
make test
make check
```

Comandos úteis:

```bash
make test-x
make test-v
make lint
make format
make typecheck
```

### Testes demonstrativos (com Docker)

Esses testes validam features de demonstração (imagem, áudio e memória semântica)
no fluxo real da stack Docker.

```bash
make test-demo
# ou:
make test-demo-up
```

## 7. Troubleshooting

### `OPENROUTER_API_KEY` ausente

```bash
grep OPENROUTER_API_KEY .env
```

### API sem conectar no banco

- confira `DATABASE_URL` no `.env`
- se estiver em Docker, lembre que API/Worker usam host `db` via `docker-compose.yml`

### Worker não processa mensagens

- verifique se o serviço `worker` está rodando (`make logs`)
- confira se há mensagens `queued` e `process_after <= now()`
- valide se o agente passado em `agent=` existe no catálogo

### Mídia não transcreve/processa

- confirme `MEDIA_IMAGE_ENABLED` / `MEDIA_AUDIO_ENABLED`
- confira se há chave OpenRouter válida
- verifique logs de `worker.media`

## Próximos passos

- [Integração Twilio](TWILIO.md)
- [Arquitetura](ARCHITECTURE.md)
- [Criando Agentes](ADDING_AGENTS.md)
- [Banco de Dados](DATABASE.md)
- [Deploy](DEPLOY.md)
