# Phase 12 search service

The service exposes action search (Cosmos-Embed1), object/attribute search
(SigLIP2), reciprocal-rank fusion, search by image, optional Nemotron query
decomposition, and optional Cosmos3 top-K criticism.

GPU providers are offline between admitted windows. Query vectors generated
during an admitted window are cached under `runtime/search`; normal vector
retrieval then continues without a GPU. If the critic is unavailable, ranked
results are returned unchanged with `critic_status=unavailable`.

Endpoints:

- `GET /dashboard`, `/api/v1/state`, `/health/live`, `/health/ready`, `/metrics`
- `POST /api/v1/index/video`, `/api/v1/index/object`
- `POST /api/v1/search`, `/api/v1/search/image`, `/api/v1/decompose`
- `POST /api/v1/evaluation`

Only `selected-clip://` and `selected-snapshot://` inputs are accepted. Raw
video storage is not mounted.
