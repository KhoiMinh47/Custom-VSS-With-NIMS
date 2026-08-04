#!/bin/sh
set -eu

ES="${ELASTICSEARCH_URL:-http://elasticsearch:9200}"
CONFIG_DIR="${CONFIG_DIR:-/config}"

put_json() {
  path="$1"
  file="$2"
  curl --fail --silent --show-error \
    -X PUT "$ES$path" \
    -H 'Content-Type: application/json' \
    --data-binary "@$file" >/dev/null
}

put_json "/_ilm/policy/vss-default-retention" "$CONFIG_DIR/ilm-vss-default.json"
put_json "/_component_template/vss-common-fields" "$CONFIG_DIR/component-vss-common.json"
put_json "/_index_template/vss-events" "$CONFIG_DIR/template-events.json"
put_json "/_index_template/vss-video-embeddings" "$CONFIG_DIR/template-video-embeddings.json"
put_json "/_index_template/vss-object-embeddings" "$CONFIG_DIR/template-object-embeddings.json"
put_json "/_index_template/vss-phase13-captions" "$CONFIG_DIR/template-phase13-captions.json"
put_json "/_index_template/vss-phase13-summaries" "$CONFIG_DIR/template-phase13-summaries.json"

for alias in \
  mdx-raw mdx-incidents mdx-vlm-incidents mdx-rt-vlm-alerts \
  vss-behavior-events vss-captions vss-summaries \
  retail-shelf-results vss-system-events vss-video-embeddings \
  vss-object-embeddings; do
  if ! curl --fail --silent "$ES/_alias/$alias" >/dev/null 2>&1; then
    curl --fail --silent --show-error \
      -X PUT "$ES/${alias}-000001" \
      -H 'Content-Type: application/json' \
      --data-binary "{\"settings\":{\"index.lifecycle.rollover_alias\":\"$alias\"},\"aliases\":{\"$alias\":{\"is_write_index\":true}}}" >/dev/null
  fi
done

put_json \
  "/vss-behavior-events-000001/_mapping" \
  "$CONFIG_DIR/mapping-behavior-events.json"
put_json \
  "/mdx-incidents-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase10-incidents.json"
put_json \
  "/mdx-vlm-incidents-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase10-incidents.json"
put_json \
  "/mdx-rt-vlm-alerts-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase11-direct-alerts.json"
put_json \
  "/vss-video-embeddings-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase12-video-embeddings.json"
put_json \
  "/vss-object-embeddings-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase12-object-embeddings.json"
put_json \
  "/vss-captions-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase13-captions.json"
put_json \
  "/vss-summaries-000001/_mapping" \
  "$CONFIG_DIR/mapping-phase13-summaries.json"

curl --fail --silent "$ES/_cluster/health?wait_for_status=yellow" >/dev/null
echo "Elasticsearch templates, ILM policy and write aliases are ready."
