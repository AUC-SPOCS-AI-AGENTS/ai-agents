-- embeddings.sql
-- One embedding (meaning vector) per resume record.
-- source_table + record_id point to the record the vector belongs to.
CREATE TABLE IF NOT EXISTS embeddings (
    source_table  TEXT    NOT NULL,   -- 'institutions', 'positions', 'experiences' or 'skills'
    record_id     INTEGER NOT NULL,   -- the record's ID in that table
    text          TEXT    NOT NULL,   -- the exact text that was embedded
    vector        TEXT    NOT NULL,   -- the embedding, stored as a JSON list of numbers
    model         TEXT    NOT NULL,   -- which embedding model made it
    PRIMARY KEY (source_table, record_id)
);