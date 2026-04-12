ALTER TABLE streaming_availability
    ADD CONSTRAINT fk_streaming_movie
    FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE;
