#!/usr/bin/env bash
set -eu
here=$(cd "$(dirname "$0")" && pwd)
core="$here/../../sentrix-core"
children=()
cleanup(){ for child in "${children[@]:-}"; do [[ -z "$child" ]] || kill "$child" 2>/dev/null || true; done; }
trap cleanup EXIT
trap 'exit 0' TERM INT
ready(){ curl -fsS --max-time 4 "http://127.0.0.1:5177/actuator/health" >/dev/null && curl -fsS --max-time 4 http://127.0.0.1:8001/health >/dev/null; }
if ! ready; then
  "$core/dev/replay/start-local.sh" &
  server=$!
  children+=("$server")
  for ((i=0;i<90;i++)); do
    kill -0 "$server" 2>/dev/null || { echo '재생 서버 로그를 확인하세요.'; exit 1; }
    if ready; then break; fi
    sleep 1
  done
  ready || { echo '재생 서버 준비 시간 초과'; exit 1; }
fi
if ! curl -fsS --max-time 3 http://127.0.0.1:5190/state >/dev/null 2>&1; then
  python3 "$here/visitor.py" &
  children+=("$!")
  for ((i=0;i<20;i++)); do
    curl -fsS --max-time 2 http://127.0.0.1:5190/state >/dev/null 2>&1 && break
    sleep 1
  done
fi
curl -fsS --max-time 3 http://127.0.0.1:5190/state >/dev/null
echo '맥북  http://127.0.0.1:5190/'
echo '큰 모니터  http://127.0.0.1:5190/display'
if [[ "$(uname)" == Darwin ]]; then open http://127.0.0.1:5190/ http://127.0.0.1:5190/display; fi
wait
