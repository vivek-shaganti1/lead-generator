#!/usr/bin/env bash
# Single entrypoint for every role, so all containers share one image.
set -euo pipefail

ROLE="${1:-api}"

wait_for() {
  local name="$1" host="$2" port="$3" attempts=60
  echo "waiting for ${name} at ${host}:${port}..."
  until python -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${host}', ${port}))
except OSError:
    sys.exit(1)
" 2>/dev/null; do
    attempts=$((attempts - 1))
    if [ "$attempts" -le 0 ]; then
      echo "ERROR: ${name} never became reachable" >&2
      exit 1
    fi
    sleep 2
  done
  echo "${name} is up"
}

[ -n "${POSTGRES_HOST:-}" ] && wait_for postgres "${POSTGRES_HOST}" "${POSTGRES_PORT:-5432}"
[ -n "${REDIS_HOST:-}" ] && wait_for redis "${REDIS_HOST}" "${REDIS_PORT:-6379}"

case "$ROLE" in
  api)
    # Migrations run once, from the API container only.
    alembic upgrade head || python -c "from app.db import init_db; init_db()" || true
    exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers \
         --forwarded-allow-ips='*' --workers "${WEB_CONCURRENCY:-2}"
    ;;
  worker)
    exec celery -A app.workers.celery_app.celery_app worker \
         --loglevel="${CELERY_LOG_LEVEL:-info}" --concurrency="${CELERY_CONCURRENCY:-4}"
    ;;
  beat)
    exec celery -A app.workers.celery_app.celery_app beat \
         --loglevel="${CELERY_LOG_LEVEL:-info}"
    ;;
  flower)
    exec celery -A app.workers.celery_app.celery_app flower --port=5555
    ;;
  shell)
    exec python
    ;;
  *)
    exec "$@"
    ;;
esac
