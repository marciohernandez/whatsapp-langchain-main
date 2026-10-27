"""Grafo para uso com langgraph dev.

Este arquivo exporta uma variável `graph` para integração com `langgraph dev`.
O servidor de produção usa `build_graph()` de agent.py, passando o checkpointer
e store reais.

Em dev, usa InMemoryStore para testar memória sem PostgreSQL.
Sem embeddings — busca é por texto exato (suficiente para testes locais).
"""

from langgraph.store.memory import InMemoryStore

from whatsapp_langchain.agents.catalog.rhawk_assistant.agent import build_graph

# InMemoryStore sem index: funciona para dev, sem busca semântica
store = InMemoryStore()

# Grafo compilado para langgraph dev (in-memory, sem checkpointer)
graph = build_graph(store=store)
