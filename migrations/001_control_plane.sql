BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stores (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    timezone text NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cameras (
    id uuid PRIMARY KEY,
    store_id uuid NOT NULL REFERENCES stores(id),
    external_id text NOT NULL,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'disabled'
        CHECK (status IN ('disabled', 'enabled', 'offline', 'online', 'error')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (store_id, external_id)
);

CREATE TABLE IF NOT EXISTS camera_streams (
    id uuid PRIMARY KEY,
    camera_id uuid NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    stream_type text NOT NULL CHECK (stream_type IN ('main', 'ai_substream')),
    uri_secret_ref text NOT NULL,
    codec text,
    width integer CHECK (width IS NULL OR width > 0),
    height integer CHECK (height IS NULL OR height > 0),
    fps numeric(6,2) CHECK (fps IS NULL OR fps > 0),
    enabled boolean NOT NULL DEFAULT true,
    UNIQUE (camera_id, stream_type)
);

CREATE TABLE IF NOT EXISTS camera_credentials_ref (
    camera_id uuid PRIMARY KEY REFERENCES cameras(id) ON DELETE CASCADE,
    secret_provider text NOT NULL,
    secret_ref text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zones (
    id uuid PRIMARY KEY,
    camera_id uuid NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    name text NOT NULL,
    zone_type text NOT NULL,
    polygon jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lines (
    id uuid PRIMARY KEY,
    camera_id uuid NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    name text NOT NULL,
    line_type text NOT NULL,
    points jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shelves (
    id uuid PRIMARY KEY,
    camera_id uuid NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    external_id text NOT NULL,
    roi jsonb NOT NULL,
    mapping_version integer NOT NULL DEFAULT 1,
    active boolean NOT NULL DEFAULT true,
    UNIQUE (camera_id, external_id, mapping_version)
);

CREATE TABLE IF NOT EXISTS products (
    id uuid PRIMARY KEY,
    sku text NOT NULL UNIQUE,
    name text NOT NULL,
    brand text,
    category text,
    reference_asset_uri text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS planograms (
    id uuid PRIMARY KEY,
    shelf_id uuid NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
    version integer NOT NULL,
    layout jsonb NOT NULL,
    active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (shelf_id, version)
);

CREATE TABLE IF NOT EXISTS model_profiles (
    id uuid PRIMARY KEY,
    model_id text NOT NULL,
    model_version text NOT NULL,
    image_digest text,
    profile_id text,
    cache_path text,
    status text NOT NULL DEFAULT 'discovered',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, model_version, profile_id)
);

CREATE TABLE IF NOT EXISTS prompts (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    version integer NOT NULL,
    body text NOT NULL,
    output_schema jsonb,
    active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS runtime_profiles (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    priority integer NOT NULL,
    config jsonb NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS batch_jobs (
    id uuid PRIMARY KEY,
    store_id uuid REFERENCES stores(id),
    camera_id uuid REFERENCES cameras(id),
    job_type text NOT NULL,
    status text NOT NULL
        CHECK (status IN ('queued', 'waiting_for_gpu', 'running', 'succeeded', 'failed', 'cancelled', 'dead_letter')),
    priority integer NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    request jsonb NOT NULL,
    result jsonb,
    checkpoint jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);

CREATE INDEX IF NOT EXISTS batch_jobs_queue_idx
    ON batch_jobs (status, priority DESC, created_at)
    WHERE status IN ('queued', 'waiting_for_gpu');

CREATE TABLE IF NOT EXISTS job_attempts (
    id bigserial PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
    attempt integer NOT NULL,
    status text NOT NULL,
    error_code text,
    error_message text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (job_id, attempt)
);

CREATE TABLE IF NOT EXISTS roles (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    permissions jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    subject text NOT NULL UNIQUE,
    display_name text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor_subject text NOT NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id text,
    correlation_id text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_logs_time_idx ON audit_logs (occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_correlation_idx ON audit_logs (correlation_id);

CREATE TABLE IF NOT EXISTS retention_policies (
    id uuid PRIMARY KEY,
    resource_type text NOT NULL UNIQUE,
    retention_days integer NOT NULL CHECK (retention_days > 0),
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feature_flags (
    name text PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT false,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations(version)
VALUES ('001_control_plane')
ON CONFLICT (version) DO NOTHING;

COMMIT;
