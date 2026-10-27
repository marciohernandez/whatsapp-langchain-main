-- 003_waha_chat_id.sql
-- Suporte a WAHA: guarda o chatId de destino e deduplica reentregas de webhook.

-- chatId do WhatsApp (ex: 5511999999999@c.us) usado para responder.
ALTER TABLE message_queue
    ADD COLUMN IF NOT EXISTS chat_id TEXT;

-- IDs de mensagens de entrada já aceitas. O WAHA reentrega o webhook em caso
-- de timeout/5xx; a PK garante que cada mensagem seja enfileirada uma vez
-- (inclusive as que o debounce concatena a outra mensagem da fila).
CREATE TABLE IF NOT EXISTS inbound_dedupe (
    message_id  TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inbound_dedupe_created
    ON inbound_dedupe (created_at);
