CREATE TABLE IF NOT EXISTS embeddings (
    table_name  TEXT    NOT NULL,   -- which table the record lives in (institutions, skills, ...)
    record_id   INTEGER NOT NULL,   -- the record's ID in that table
    text        TEXT    NOT NULL,   -- the exact text that was embedded
    vector      TEXT    NOT NULL,   -- the embedding, stored as a JSON list of numbers
    model       TEXT    NOT NULL,   -- which embedding model produced it
    PRIMARY KEY (table_name, record_id)
);
