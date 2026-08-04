BEGIN;

DROP TABLE IF EXISTS video_asset_refs;
DROP TABLE IF EXISTS camera_stream_health;
DELETE FROM schema_migrations WHERE version = '002_video_management';

COMMIT;
