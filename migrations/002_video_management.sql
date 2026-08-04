BEGIN;

CREATE TABLE IF NOT EXISTS camera_stream_health (
    camera_id uuid NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    stream_type text NOT NULL CHECK (stream_type IN ('main', 'ai_substream')),
    observed_at timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN ('unknown', 'connecting', 'online', 'offline', 'error')),
    last_frame_at timestamptz,
    reconnect_count bigint NOT NULL DEFAULT 0 CHECK (reconnect_count >= 0),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    schema_version text NOT NULL DEFAULT '1.0.0',
    PRIMARY KEY (camera_id, stream_type)
);

CREATE INDEX IF NOT EXISTS camera_stream_health_observed_idx
    ON camera_stream_health (observed_at DESC);

CREATE TABLE IF NOT EXISTS video_asset_refs (
    asset_id uuid PRIMARY KEY,
    store_id uuid NOT NULL REFERENCES stores(id),
    camera_id uuid NOT NULL REFERENCES cameras(id),
    asset_type text NOT NULL CHECK (asset_type IN ('recording', 'clip', 'snapshot')),
    start_time timestamptz NOT NULL,
    end_time timestamptz,
    uri text NOT NULL,
    sha256 text,
    schema_version text NOT NULL DEFAULT '1.0.0',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_time IS NULL OR end_time >= start_time)
);

CREATE INDEX IF NOT EXISTS video_asset_refs_camera_time_idx
    ON video_asset_refs (camera_id, start_time DESC);

INSERT INTO schema_migrations(version)
VALUES ('002_video_management')
ON CONFLICT (version) DO NOTHING;

COMMIT;
