# WhatsApp LangChain

Template educacional e production-ready para construir sistemas de agentes de IA no WhatsApp com LangGraph.

## O que é?

Um sistema completo e production-ready que conecta agentes de IA ao WhatsApp. Você define o comportamento do agente com LangChain/LangGraph, e a infraestrutura do projeto cuida do resto: recebimento de mensagens, processamento assíncrono, memória e operação.

O objetivo deste repositório é ensinar arquitetura de sistemas em volta do agente:
- entrada confiável de mensagens
- processamento assíncrono
- persistência de contexto e memória
- observabilidade, retries e limites

## Fase Atual

**Fase 3 concluída no código.**

Já implementado no código:
- API FastAPI com webhook Twilio assíncrono (`/webhook/twilio`)
- fila em PostgreSQL com debounce e retry
- worker assíncrono para processamento LangGraph
- bootstrap de schema LangGraph no startup (sem criação lazy no primeiro request)
- ciclo de vida explícito no worker para `checkpointer`/`store` (abertos no boot e reutilizados)
- checkpointer PostgreSQL (`thread_id`) para contexto por conversa
- memória semântica com `AsyncPostgresStore` + embeddings (`user_id`)
- middleware de contexto (`trim`, `summarize`, `none`)
- tools de memória semântica (`save_memory` e `read_memory`)
- processamento de mídia (imagem e áudio) via OpenRouter multimodal
- rate limit por telefone (in-memory)
- rotas administrativas (`/api/agents`, `/api/chats`, `/api/metrics`)
- endpoint síncrono educacional (`/webhook/sync`)
- validação criptográfica de `X-Twilio-Signature`
- envio real de resposta via Twilio Messages API
- typing indicator via Twilio antes do processamento
- documentação de sandbox/webhook/túnel com cloudflared

Fase 4 será o fechamento operacional do projeto:
- frontend/admin panel integrado neste repositório
- deploy documentado e reprodutível
- stress testing e hardening final

## Arquitetura

![Arquitetura](docs/architecture.png)

Fluxo principal:

```text
WhatsApp/Twilio -> API (/webhook/twilio) -> PostgreSQL (message_queue)
                                              -> Worker -> LangGraph Agent
                                              -> PostgreSQL (response, conversation)
```

Separar API e Worker evita bloqueio na borda HTTP e melhora confiabilidade sob carga.

## Quick Start

### 1. Setup

```bash
git clone <repo-url>
cd whatsapp-langchain
make setup
cp .env.example .env
```

Edite o `.env` e configure pelo menos:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

### 2. Suba o stack local

```bash
make up
# sobe: db + api + worker
```

### Acesso ao banco (DBeaver)

Use estes dados de conexão PostgreSQL:

- Host: `localhost`
- Port: `5432`
- Database: `whatsapp_langchain`
- User: `postgres`
- Password: `postgres`

Valide saúde da API:

```bash
curl http://localhost:8000/health
```

### 3. Teste rápido (endpoint síncrono)

```bash
curl -X POST "http://localhost:8000/webhook/sync?agent=rhawk_assistant" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+5511999999999","message":"Olá!"}'
```

### 4. Teste assíncrono (simulando Twilio)

```bash
curl -X POST "http://localhost:8000/webhook/twilio?agent=rhawk_assistant" \
  -d "MessageSid=SM123" \
  -d "From=whatsapp:+5511999999999" \
  -d "To=whatsapp:+14155238886" \
  -d "Body=Quero aprender sistemas de agentes" \
  -d "NumMedia=0"
```

Acompanhe métricas:

```bash
curl http://localhost:8000/api/metrics
curl http://localhost:8000/api/chats
```

## Estrutura do Projeto

```text
whatsapp-langchain/
├── src/whatsapp_langchain/
│   ├── agents/        # Catálogo de agentes, middleware e tools
│   ├── server/        # API FastAPI (webhooks + admin APIs)
│   ├── worker/        # Loop consumidor da fila e execução dos agentes
│   └── shared/        # Config, DB, fila, modelos, logging, factory LLM
├── db/migrations/     # Schema SQL (fila + conversas + vector)
├── docs/              # Documentação técnica e onboarding
└── tests/             # Unit e integração
```

## Aprendizado (foco em sistemas)

Este projeto é para aprender decisões de engenharia reais:
- fronteiras entre serviços (`server`, `worker`, `shared`)
- contratos de dados (`MessageQueue`, `Conversation`, webhook payload)
- estados e transições (`queued -> processing -> done/failed`)
- consistência operacional (retry com backoff, debounce, lease)
- limites e custo (rate limit HTTP e rate limit de LLM)

Para detalhes técnicos:
- [Arquitetura](docs/ARCHITECTURE.md)
- [Primeiros Passos](docs/GETTING_STARTED.md)
- [Criando Agentes](docs/ADDING_AGENTS.md)
- [Banco de Dados](docs/DATABASE.md)
- [Integração Twilio](docs/TWILIO.md)
- [Deploy](docs/DEPLOY.md)



## Comandos úteis

```bash
make help
make api
make worker
make migrate
make test
make test-live
make check
make logs
make reset
make test-demo
```

## Roadmap

- **Fase 1** concluída: base de agentes + middleware de contexto
- **Fase 2** concluída: API + Worker + PostgreSQL + observabilidade operacional
- **Fase 3** concluída: integração Twilio + assinatura real + typing + reforço dos testes de debounce
- **Fase 4** em aberto: frontend/admin panel + deploy + stress + hardening final

## Licença

[TOPHAWKS Community License](LICENSE) - uso restrito a membros da comunidade [TOPHAWKS](https://www.rhawk.pro/comunidade).
