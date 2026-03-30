-- Persist ConversationContext between SMS messages so multi-turn
-- sighting flows (photo -> plate correction -> borough) retain state.
CREATE TABLE IF NOT EXISTS chat_context (
    phone_number VARCHAR(20) PRIMARY KEY,
    context_json JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
