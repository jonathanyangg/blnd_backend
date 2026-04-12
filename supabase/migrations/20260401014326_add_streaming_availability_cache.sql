CREATE TABLE streaming_availability (
    id BIGSERIAL PRIMARY KEY,
    tmdb_id INTEGER NOT NULL,
    country VARCHAR(2) NOT NULL,
    streaming_data JSONB NOT NULL DEFAULT '[]',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tmdb_id, country)
);

CREATE INDEX idx_streaming_availability_tmdb_country
    ON streaming_availability (tmdb_id, country);

CREATE INDEX idx_streaming_availability_fetched_at
    ON streaming_availability (fetched_at);
