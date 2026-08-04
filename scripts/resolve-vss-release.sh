#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"

upstream="$PROJECT_ROOT/third_party/video-search-and-summarization"
deploy_dir="$upstream/deploy/docker"
manifest_dir="$PROJECT_ROOT/artifacts/manifests"
generated_dir="$PROJECT_ROOT/deploy/generated/vss-3.2.1"
mkdir -p "$manifest_dir" "$generated_dir" "$PROJECT_ROOT/runtime/vss"
: > "$manifest_dir/vss-compose-warnings.log"

expected_ref="v3.2.1"
expected_commit="7640d917047cf7b0fd3085eefb8282754b56bc94"

actual_ref="$(git -C "$upstream" describe --tags --exact-match)"
actual_commit="$(git -C "$upstream" rev-parse HEAD)"
[[ "$actual_ref" == "$expected_ref" ]]
[[ "$actual_commit" == "$expected_commit" ]]

{
  printf 'repository=https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git\n'
  printf 'ref=%s\n' "$actual_ref"
  printf 'commit=%s\n' "$actual_commit"
  printf 'resolved_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$manifest_dir/vss-git-revision.txt"

sanitize_env() {
  source_file="$1"
  destination="$2"
  awk \
    -v apps="$deploy_dir" \
    -v data="$PROJECT_ROOT/runtime/vss" \
    '
      /^HARDWARE_PROFILE=/ { print "HARDWARE_PROFILE=OTHER"; next }
      /^VSS_APPS_DIR=/ { print "VSS_APPS_DIR=\"" apps "\""; next }
      /^VSS_DATA_DIR=/ { print "VSS_DATA_DIR=\"" data "\""; next }
      /^HOST_IP=/ { print "HOST_IP=127.0.0.1"; next }
      /^EXTERNAL_IP=/ { print "EXTERNAL_IP=127.0.0.1"; next }
      /^NGC_CLI_API_KEY=/ { print "NGC_CLI_API_KEY="; next }
      /^NVIDIA_API_KEY=/ { print "NVIDIA_API_KEY="; next }
      /^OPENAI_API_KEY=/ { print "OPENAI_API_KEY="; next }
      /^(RESERVED_DEVICE_IDS|FIXED_SHARED_DEVICE_IDS)=/ {
        split($0, item, "=")
        print item[1] "="
        next
      }
      /^[A-Z0-9_]*DEVICE_ID=/ {
        split($0, item, "=")
        print item[1] "=0"
        next
      }
      { print }
    ' "$source_file" > "$destination"
  chmod 600 "$destination"
}

resolve_profile() {
  label="$1"
  source_profile="$2"
  compose_profiles="$3"
  env_source="$deploy_dir/developer-profiles/dev-profile-$source_profile/.env"
  env_output="$generated_dir/$label.env"
  yaml_output="$manifest_dir/resolved-$label-compose.yml"
  json_output="$manifest_dir/resolved-$label-compose.json"
  images_output="$manifest_dir/vss-$label-images.txt"

  sanitize_env "$env_source" "$env_output"

  (
    cd "$deploy_dir"
    export NGC_API_KEY=
    export NGC_CLI_API_KEY=
    export NVIDIA_API_KEY=
    export OPENAI_API_KEY=
    export HF_TOKEN=
    COMPOSE_PROFILES="$compose_profiles" \
      docker compose \
        -f compose.yml \
        --env-file "$env_output" \
        config > "$yaml_output" \
        2>> "$manifest_dir/vss-compose-warnings.log"
    COMPOSE_PROFILES="$compose_profiles" \
      docker compose \
        -f compose.yml \
        --env-file "$env_output" \
        config --format json > "$json_output" \
        2>> "$manifest_dir/vss-compose-warnings.log"
    COMPOSE_PROFILES="$compose_profiles" \
      docker compose \
        -f compose.yml \
        --env-file "$env_output" \
        config --images \
        2>> "$manifest_dir/vss-compose-warnings.log" \
        | sort -u > "$images_output"
  )
}

resolve_profile \
  base \
  base \
  "bp_developer_base_2d,llm_local_shared_nvidia-nemotron-nano-9b-v2,vlm_local_shared_cosmos3-reasoner"
resolve_profile \
  alerts-verification \
  alerts \
  "bp_developer_alerts_2d_cv,llm_local_shared_nvidia-nemotron-nano-9b-v2"
resolve_profile \
  alerts-realtime \
  alerts \
  "bp_developer_alerts_2d_vlm,llm_local_shared_nvidia-nemotron-nano-9b-v2"
resolve_profile \
  search \
  search \
  "bp_developer_search_2d,llm_local_shared_nvidia-nemotron-nano-9b-v2,vlm_local_shared_cosmos3-reasoner"
resolve_profile \
  lvs \
  lvs \
  "bp_developer_lvs_2d,llm_local_shared_nvidia-nemotron-nano-9b-v2"

cat "$manifest_dir"/vss-*-images.txt | sort -u \
  > "$manifest_dir/vss-images.txt"

jq -r '
  .services
  | to_entries[]
  | .key as $service
  | (.value.ports // [])[]
  | [$service, (.published // ""), (.target // ""), (.protocol // "tcp")]
  | @tsv
' "$manifest_dir"/resolved-*-compose.json \
  | sort -u > "$manifest_dir/vss-resolved-ports.tsv"

if [[ -n "${NGC_API_KEY:-}" ]] \
  && grep -FRq -- "$NGC_API_KEY" "$generated_dir" "$manifest_dir"; then
  echo "ERROR: NGC_API_KEY value leaked into generated release artifacts."
  exit 1
fi

echo "VSS 3.2.1 source and five developer-profile manifests resolved without pulling images."
