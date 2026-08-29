#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$BACKEND_DIR/runtime-logs"
BACKEND_HOST="127.0.0.1"
FRONTEND_HOST="127.0.0.1"

resolve_python() {
  if [ -n "${DM_AGENT_PYTHON:-}" ]; then
    printf '%s\n' "$DM_AGENT_PYTHON"
  elif [ -x "$ROOT_DIR/.venv/bin/python3" ]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python3"
  else
    command -v python3 || true
  fi
}

PYTHON_BIN=$(resolve_python)
if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3 was not found. Set DM_AGENT_PYTHON or create .venv." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "DM_Agent requires Python 3.10 or newer; selected: $PYTHON_BIN" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Backend dependencies are missing. Run: $PYTHON_BIN -m pip install -r backend/requirements.txt" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found on PATH." >&2
  exit 1
fi
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "Frontend dependencies are missing. Run: cd frontend && npm install" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

available_port() {
  "$PYTHON_BIN" -c 'import socket,sys
host=sys.argv[1]
start=int(sys.argv[2])
for port in range(start, start + 30):
    sock=socket.socket()
    try:
        sock.bind((host, port))
    except OSError:
        continue
    finally:
        sock.close()
    print(port)
    break
else:
    raise SystemExit(1)' "$1" "$2"
}

BACKEND_PORT=$(available_port "$BACKEND_HOST" "${DM_AGENT_BACKEND_PORT:-23333}")
FRONTEND_PORT=$(available_port "$FRONTEND_HOST" "${DM_AGENT_FRONTEND_PORT:-5173}")
API_URL="http://$BACKEND_HOST:$BACKEND_PORT/api/v1"
FRONTEND_URL="http://$FRONTEND_HOST:$FRONTEND_PORT"
printf 'VITE_API_BASE_URL=%s\n' "$API_URL" > "$FRONTEND_DIR/.env.development.local"

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  [ -z "$FRONTEND_PID" ] || kill "$FRONTEND_PID" 2>/dev/null || true
  [ -z "$BACKEND_PID" ] || kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

(
  cd "$BACKEND_DIR"
  exec "$PYTHON_BIN" -m uvicorn main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
) >"$LOG_DIR/backend.out.log" 2>"$LOG_DIR/backend.err.log" &
BACKEND_PID=$!

(
  cd "$FRONTEND_DIR"
  exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
) >"$LOG_DIR/frontend.out.log" 2>"$LOG_DIR/frontend.err.log" &
FRONTEND_PID=$!

attempt=0
until curl -fsS "$API_URL/health" >/dev/null 2>&1 && curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "Startup timed out. See $LOG_DIR for details." >&2
    exit 1
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "A service exited during startup. See $LOG_DIR for details." >&2
    exit 1
  fi
  sleep 1
done

printf '{"backend_url":"%s","frontend_url":"%s","backend_pid":%s,"frontend_pid":%s}\n' \
  "$API_URL" "$FRONTEND_URL" "$BACKEND_PID" "$FRONTEND_PID" > "$LOG_DIR/runtime-state.json"
echo "DM_Agent is ready: $FRONTEND_URL"
echo "Press Ctrl-C to stop both services."

if [ "${DM_AGENT_NO_BROWSER:-0}" != "1" ]; then
  if command -v open >/dev/null 2>&1; then
    open "$FRONTEND_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$FRONTEND_URL" >/dev/null 2>&1 || true
  fi
fi

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 2
done
echo "A service stopped. See $LOG_DIR for details." >&2
exit 1
