#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$BACKEND_DIR/runtime-logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_URL="http://127.0.0.1:23333"
BACKEND_HEALTH_URL="$BACKEND_URL/api/v1/health"
FRONTEND_URL="http://127.0.0.1:5173"

BACKEND_PID=""
FRONTEND_PID=""
STARTED_BACKEND=0
STARTED_FRONTEND=0

mkdir -p "$LOG_DIR"

translate_windows_path() {
  local raw_path="$1"

  if [[ -z "$raw_path" ]]; then
    return 1
  fi

  if command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$raw_path"
    return 0
  fi

  if [[ "$raw_path" =~ ^([A-Za-z]):\\(.*)$ ]]; then
    local drive_letter="${BASH_REMATCH[1],,}"
    local tail_path="${BASH_REMATCH[2]//\\//}"
    printf '/mnt/%s/%s\n' "$drive_letter" "$tail_path"
    return 0
  fi

  printf '%s\n' "$raw_path"
}

url_is_ready() {
  local url="$1"

  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null "$url" >/dev/null 2>&1
    return $?
  fi

  powershell.exe -NoProfile -Command \
    "try { Invoke-WebRequest -UseBasicParsing '$url' | Out-Null; exit 0 } catch { exit 1 }" \
    >/dev/null 2>&1
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local pid="${3:-}"
  local attempts="${4:-60}"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if url_is_ready "$url"; then
      return 0
    fi
    if [[ -n "$pid" ]] && ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "$name process exited before becoming ready: $url"
      return 1
    fi
    sleep 1
  done

  echo "$name did not become ready: $url"
  return 1
}

python_runner=()

resolve_python_runner() {
  if [[ -n "${DM_AGENT_PYTHON:-}" ]]; then
    python_runner=("$DM_AGENT_PYTHON")
    return 0
  fi

  local win_conda_python=""
  win_conda_python="$(translate_windows_path 'C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe' || true)"
  if [[ -n "$win_conda_python" && -x "$win_conda_python" ]]; then
    python_runner=("$win_conda_python")
    return 0
  fi

  if [[ -n "${CONDA_PREFIX:-}" ]]; then
    if [[ -x "$CONDA_PREFIX/python.exe" ]]; then
      python_runner=("$CONDA_PREFIX/python.exe")
      return 0
    fi
    if [[ -x "$CONDA_PREFIX/bin/python" ]]; then
      python_runner=("$CONDA_PREFIX/bin/python")
      return 0
    fi
  fi

  if command -v conda >/dev/null 2>&1; then
    python_runner=(conda run -n DM_Agent python)
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    python_runner=(python3)
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    python_runner=(python)
    return 0
  fi

  echo "Could not find a usable Python runtime."
  echo "Set DM_AGENT_PYTHON or install the DM_Agent conda environment first."
  return 1
}

cleanup() {
  local exit_code=$?

  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi

  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi

  wait >/dev/null 2>&1 || true
  exit "$exit_code"
}

trap cleanup INT TERM EXIT

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  echo "Missing backend/.env."
  echo "Copy backend/.env.example to backend/.env and fill in your API settings first."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but was not found in PATH."
  exit 1
fi

resolve_python_runner

if ! "${python_runner[@]}" -c "import fastapi, uvicorn, langgraph, langchain_openai" >/dev/null 2>&1; then
  echo "Backend Python dependencies are missing."
  echo "Run: ${python_runner[*]} -m pip install -r backend/requirements.txt"
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (
    cd "$FRONTEND_DIR"
    npm install
  )
fi

if url_is_ready "$BACKEND_HEALTH_URL"; then
  echo "Backend already running at $BACKEND_URL"
else
  echo "Starting backend..."
  : >"$BACKEND_LOG"
  (
    cd "$BACKEND_DIR"
    PYTHONUNBUFFERED=1 "${python_runner[@]}" main.py
  ) >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  STARTED_BACKEND=1
fi

if url_is_ready "$FRONTEND_URL"; then
  echo "Frontend already running at $FRONTEND_URL"
else
  echo "Starting frontend..."
  : >"$FRONTEND_LOG"
  (
    cd "$FRONTEND_DIR"
    npm run dev -- --host 127.0.0.1
  ) >"$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!
  STARTED_FRONTEND=1
fi

if [[ "$STARTED_BACKEND" -eq 1 ]]; then
  wait_for_url "Backend" "$BACKEND_HEALTH_URL" "$BACKEND_PID" 90 || {
    echo "Backend log: $BACKEND_LOG"
    tail -n 80 "$BACKEND_LOG" || true
    exit 1
  }
fi

if [[ "$STARTED_FRONTEND" -eq 1 ]]; then
  wait_for_url "Frontend" "$FRONTEND_URL" "$FRONTEND_PID" 90 || {
    echo "Frontend log: $FRONTEND_LOG"
    tail -n 80 "$FRONTEND_LOG" || true
    exit 1
  }
fi

echo
echo "DM_Agent is ready."
echo "Frontend: $FRONTEND_URL"
echo "Backend:  $BACKEND_URL"
echo "Logs:"
echo "  $BACKEND_LOG"
echo "  $FRONTEND_LOG"
echo
echo "Press Ctrl+C to stop the services started by this script."

if [[ "$STARTED_BACKEND" -eq 0 && "$STARTED_FRONTEND" -eq 0 ]]; then
  trap - INT TERM EXIT
  exit 0
fi

while true; do
  if [[ -n "$BACKEND_PID" && ! -d "/proc/$BACKEND_PID" ]] && ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    echo "Backend process exited unexpectedly."
    echo "Backend log: $BACKEND_LOG"
    tail -n 80 "$BACKEND_LOG" || true
    exit 1
  fi

  if [[ -n "$FRONTEND_PID" && ! -d "/proc/$FRONTEND_PID" ]] && ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    echo "Frontend process exited unexpectedly."
    echo "Frontend log: $FRONTEND_LOG"
    tail -n 80 "$FRONTEND_LOG" || true
    exit 1
  fi

  sleep 2
done
