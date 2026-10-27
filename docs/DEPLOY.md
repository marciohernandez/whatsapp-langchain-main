# Deploy

Este guia cobre o deploy da base da **Fase 2**:
- API FastAPI
- Worker assíncrono
- PostgreSQL com pgvector

Objetivo: publicar a arquitetura de processamento assíncrono com persistência e memória.

## Escopo desta fase

Incluído:
- webhook Twilio assíncrono (`/webhook/twilio`)
- fila em PostgreSQL
- execução de agente no worker
- contexto por checkpointer
- memória semântica por store com tools (`save_memory` e `read_memory`)
- rotas administrativas e health check

Ainda não incluído como fluxo completo de produção:
- envio de resposta para WhatsApp via API Twilio
- validação completa de assinatura Twilio

## Topologia mínima de produção

- `db`: PostgreSQL (com extensão `vector`)
- `api`: processo HTTP (`uvicorn ...server.main:app`)
- `worker`: processo consumidor (`python -m ...worker.main`)

A API e o worker devem compartilhar:
- o mesmo banco
- o mesmo conjunto de variáveis de ambiente
- a mesma versão de código

## Variáveis obrigatórias

- `DATABASE_URL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL`

Recomendadas para operação:
- `LOG_JSON=true`
- `CONTEXT_STRATEGY`
- `MESSAGE_BUFFER_SECONDS`
- `POLL_INTERVAL_SECONDS`
- `LEASE_SECONDS`
- `MAX_ATTEMPTS`
- `MEMORY_ENABLED`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMS`

## Ordem de subida

1. Subir banco PostgreSQL com pgvector.
2. Subir API (aplica migrações no startup).
3. Subir Worker (também valida/aplica migrações).
4. Verificar `GET /health`.
5. Enviar mensagem de teste para `/webhook/twilio`.
6. Acompanhar `/api/metrics` e logs.

## Deploy com Docker (referência)

Os Dockerfiles e `docker-compose.yml` deste repositório já representam a base da Fase 2.

Build local:

```bash
docker compose build
```

Subida local (modo próximo da produção):

```bash
docker compose up -d
```

Logs:

```bash
docker compose logs -f api worker db
```

## Checklist operacional

- health check responde 200
- `message_queue` recebe mensagens
- worker faz transição `queued -> processing -> done|failed`
- memória semântica persiste em `store` com prefixo `<phone_number>.memories`
- retries acontecem quando há erro transitório
- métricas administrativas retornam dados
- logs estruturados habilitados (`LOG_JSON=true` em produção)

## Hardening recomendado

- mover rate limit HTTP para backend distribuído (Redis ou DB)
- configurar supervisão de processos (restart policy/health probes)
- adicionar alertas para:
  - crescimento de `queue_size`
  - aumento de `failed`
  - latência média de processamento
- proteger rotas admin (authn/authz)

## Próxima evolução

Ao avançar para fases seguintes:
- integrar envio de resposta via Twilio no worker
- validar assinatura Twilio com SDK oficial
- publicar frontend/admin panel desacoplado
