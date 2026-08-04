#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"

gate_file="$PROJECT_ROOT/artifacts/preflight/preflight-result.env"
if [[ ! -f "$gate_file" ]] || ! grep -qx 'RESULT=PASS' "$gate_file"; then
  if [[ "${1:-}" != "--acknowledge-unsupported-host" ]]; then
    echo "BLOCKED: PHASE-02 preflight must be PASS before pulling VSS images."
    echo "An explicit user override requires --acknowledge-unsupported-host."
    exit 2
  fi
  mkdir -p "$PROJECT_ROOT/artifacts/manifests"
  {
    printf 'acknowledgement=explicit-user-override\n'
    printf 'date=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'preflight_result=BLOCKED\n'
  } > "$PROJECT_ROOT/artifacts/manifests/unsupported-host-pull-acknowledgement.txt"
  echo "WARNING: pulling on an unsupported host by explicit user request."
fi

if [[ -z "${NGC_API_KEY:-}" ]]; then
  echo "BLOCKED: NGC_API_KEY is not loaded in the current shell."
  exit 2
fi

manifest="$PROJECT_ROOT/artifacts/manifests/vss-images.txt"
[[ -s "$manifest" ]] || {
  echo "BLOCKED: resolve VSS release manifests first."
  exit 2
}

"$PROJECT_ROOT/scripts/inventory.sh"

printf '%s' "$NGC_API_KEY" \
  | docker login nvcr.io --username '$oauthtoken' --password-stdin >/dev/null

while IFS= read -r image; do
  case "$image" in
    nvcr.io/nvidia/vss-core/*|nvcr.io/nim/*)
      docker_free_bytes="$(df -B1 --output=avail "$(docker info --format '{{.DockerRootDir}}')" | tail -n1 | tr -d ' ')"
      if [[ "$docker_free_bytes" -lt 55000000000 ]]; then
        echo "BLOCKED: Docker filesystem has less than 55 GB free before $image."
        exit 3
      fi
      docker pull "$image"
      printf '%s\t%s\t%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$image" \
        "$(df -B1 --output=avail "$(docker info --format '{{.DockerRootDir}}')" | tail -n1 | tr -d ' ')" \
        >> "$PROJECT_ROOT/artifacts/manifests/vss-pull-progress.tsv"
      ;;
  esac
done < "$manifest"

while IFS= read -r image; do
  case "$image" in
    nvcr.io/nvidia/vss-core/*|nvcr.io/nim/*)
      docker image inspect "$image" \
        --format '{{index .RepoDigests 0}}'
      ;;
  esac
done < "$manifest" \
  | sort -u > "$PROJECT_ROOT/artifacts/manifests/vss-image-digests.txt"

echo "VSS core image pull complete; no model cache was downloaded."
