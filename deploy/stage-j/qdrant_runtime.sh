#!/usr/bin/env bash
set -euo pipefail

NAME="ai-qdrant"
IMAGE="qdrant/qdrant@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10"
DATA_DIR="${QDRANT_DATA_DIR:-/srv/ai-data/qdrant/storage}"
REST_URL="http://127.0.0.1:6333"

wait_ready() {
  for _ in $(seq 1 30); do
    if curl -fsS "${REST_URL}/readyz" >/dev/null 2>&1; then
      echo "Qdrant ready at ${REST_URL}"
      return 0
    fi
    sleep 1
  done
  echo "Qdrant readiness timeout" >&2
  return 1
}

start_qdrant() {
  mkdir -p "${DATA_DIR}"
  docker pull "${IMAGE}" >/dev/null
  if docker inspect "${NAME}" >/dev/null 2>&1; then
    configured="$(docker inspect "${NAME}" --format '{{.Config.Image}}')"
    if [[ "${configured}" != "${IMAGE}" ]]; then
      echo "Existing ${NAME} uses unexpected image: ${configured}" >&2
      return 20
    fi
    docker start "${NAME}" >/dev/null
  else
    docker run -d --name "${NAME}" --restart unless-stopped \
      -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 \
      -e QDRANT__TELEMETRY_DISABLED=true -e QDRANT__LOG_LEVEL=INFO \
      -v "${DATA_DIR}:/qdrant/storage" \
      --security-opt no-new-privileges:true \
      "${IMAGE}" >/dev/null
  fi
  wait_ready
}

status_qdrant() {
  docker ps --filter "name=^/${NAME}$" \
    --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
  curl -fsS "${REST_URL}/readyz" || true
  echo
}
case "${1:-status}" in
  start)
    start_qdrant
    ;;
  stop)
    docker stop "${NAME}" >/dev/null
    ;;
  status)
    status_qdrant
    ;;
  smoke)
    wait_ready
    PYTHONPATH="${PYTHONPATH:-src}" ./.venv/bin/python deploy/stage-j/smoke_qdrant.py
    ;;
  *)
    echo "usage: $0 {start|stop|status|smoke}" >&2
    exit 2
    ;;
esac
