# Arquitetura

Este projeto ensina agentes por uma perspectiva de **sistemas**.
O agente é só uma parte da solução. O valor real está no fluxo completo:
entrada confiável, processamento assíncrono, persistência, recuperação de falhas e inspeção operacional.

## Estado Atual (Fase 2 concluída)

Implementado:
- API FastAPI com webhook Twilio assíncrono (`POST /webhook/twilio`)
- fila em PostgreSQL (`message_queue`) com debounce e lease
- worker assíncrono consumindo fila com `FOR UPDATE SKIP LOCKED`
- execução de agentes via loader dinâmico
- checkpointer PostgreSQL (contexto por `thread_id`)
- store semântico PostgreSQL (memória por `user_id`)
- middleware de contexto (`trim`, `summarize`, `none`)
- memória semântica orientada a tools (`save_memory` e `read_memory`)
- processamento de mídia (imagem e áudio) via OpenRouter
- retry com backoff progressivo e status de falha
- APIs administrativas para inspeção

Fora do escopo da Fase 2:
- envio de resposta via API Twilio no worker
- validação criptográfica completa da assinatura Twilio
- frontend/admin panel neste repositório

## Visão de Componentes

![Arquitetura](architecture.png)

```text
[Twilio/WhatsApp]
      |
      v
[API FastAPI]
  - valida entrada
  - rate limit
  - enqueue/debounce
      |
      v
[PostgreSQL]
  - message_queue
  - conversations
  - checkpoints (langgraph)
  - store semântico (langgraph)
      |
      v
[Worker]
  - claim com lease
  - processa mídia
  - invoca agente
  - marca done/failed
```

## Fronteiras e Contratos

### API (`src/whatsapp_langchain/server/`)

Responsabilidades:
- aceitar webhook Twilio
- responder rápido com TwiML vazio
- não executar agente inline
- enfileirar payload normalizado

Contratos relevantes:
- `agent` via query string
- payload form-encoded Twilio (`From`, `To`, `Body`, `NumMedia`, etc)
- `thread_id = "{phone}:{agent}"`

### Worker (`src/whatsapp_langchain/worker/`)

Responsabilidades:
- fazer polling da fila
- processar mídia se existir
- carregar agente com checkpointer/store compartilhados (abertos no boot)
- invocar grafo com `thread_id` e `user_id`
- persistir sucesso/falha

Contrato de execução do agente:
- `thread_id`: memória de conversa (checkpointer)
- `user_id`: memória cross-thread (store semântico), derivado do telefone do webhook Twilio

### Shared (`src/whatsapp_langchain/shared/`)

Responsabilidades:
- configurações tipadas (`Settings`)
- pool/migrações
- operações de fila
- modelos Pydantic
- logging estruturado
- factory de LLM com rate limiter

## Modelo de Dados

### `message_queue`

Estado da mensagem e ciclo operacional.

Fluxo de status:

```text
queued -> processing -> done
                    -> queued (retry)
                    -> failed
```

Campos importantes:
- `process_after`: debounce e atraso de retry
- `lease_until`: lock temporal para worker
- `attempts` / `max_attempts`: governança de retry
- `response` / `error`: auditoria de resultado

### `conversations`

Tabela agregada para consultas administrativas.
- chave lógica: `(phone_number, agent_id)`
- atualizada por `upsert` a cada mensagem concluída

## Fluxo End-to-End

1. Usuário envia mensagem no WhatsApp.
2. Twilio faz `POST /webhook/twilio?agent=<agent_id>`.
3. API valida agente, aplica rate limit e chama `enqueue_or_buffer`.
4. Debounce concatena mensagens rápidas do mesmo usuário/agente.
5. Worker faz `claim_next` com lease.
6. Worker monta `HumanMessage` (texto, imagem ou transcrição de áudio).
7. Worker carrega agente com:
   - `AsyncPostgresSaver` (checkpointer) aberto no startup do worker
   - `AsyncPostgresStore` + embeddings (quando memória habilitada), também aberto no startup
8. Agente executa e retorna resposta.
9. Worker persiste resultado (`mark_done`) e atualiza `conversations`.
10. Em erro, `mark_failed` decide retry com backoff ou falha final.

## Contexto e Memória

### Contexto por thread (checkpointer)

Persistência de mensagens de uma conversa específica (`thread_id`).

### Memória semântica por usuário (store)

- namespace: `(user_id, "memories")`
- `save_memory` grava fatos relevantes
- `read_memory` recupera memórias por similaridade quando o agente precisar
- `user_id` no runtime vem de `phone_number` (payload Twilio)
- não usamos escopo `tenant_user`/`tenant_shared` neste projeto

Isso separa duas necessidades diferentes:
- continuidade da conversa atual
- conhecimento durável sobre o usuário

## Controles Operacionais

### Debounce

Agrupa mensagens enviadas em sequência curta (`MESSAGE_BUFFER_SECONDS`) para reduzir custo e ruído.

### Retry com backoff

`mark_failed` aplica `backoff_seconds = attempts * 5` enquanto houver tentativas.

### Rate limits

- API: limite por telefone/hora (in-memory)
- LLM: token bucket por processo (`InMemoryRateLimiter`)

### Observabilidade

Logs estruturados com `structlog` em todos os componentes.

## Endpoints Disponíveis

- `GET /health`
- `POST /webhook/twilio?agent=<id>`
- `POST /webhook/sync?agent=<id>` (educacional)
- `GET /api/agents`
- `GET /api/chats`
- `GET /api/chats/{phone_number}`
- `GET /api/metrics`

## Decisões Arquiteturais (didáticas)

- PostgreSQL como fila: reduz moving parts no início.
- API e Worker separados: isola latência da IA da borda HTTP.
- Loader dinâmico de agentes: facilita catálogo e extensibilidade.
- Config centralizada: evita divergência de comportamento por módulo.
- Middleware explícito: torna política de contexto auditável.
- Memória por tools explícitas: separa contexto transiente (middleware) de memória durável (store).

## Próximos passos de arquitetura

- integrar envio de saída via Twilio no worker
- validação real da assinatura Twilio com SDK oficial
- endurecimento para multi-instância (rate limit distribuído)
- camada de frontend/admin externa a este pacote
