#!/usr/bin/env bash
set -eu
here=$(cd "$(dirname "$0")" && pwd)
if [[ "$(uname)" == Darwin ]] && curl -fsS --max-time 3 http://127.0.0.1:5191/display-policy >/dev/null; then
  open http://127.0.0.1:5191/ http://127.0.0.1:5191/display
  exit 0
fi
children=()
cleanup(){ for child in "${children[@]:-}"; do [[ -z "$child" ]] || kill "$child" 2>/dev/null || true; done; }
trap cleanup EXIT
trap 'exit 0' TERM INT
if ! curl -fsS --max-time 10 http://127.0.0.1:8080/actuator/health >/dev/null || ! curl -fsS --max-time 10 http://127.0.0.1:8000/health >/dev/null; then
  echo '실시간 전시에는 운영 백엔드(8080)와 모델(8000)이 필요합니다. 맥북 전시 시작.command를 먼저 실행하세요.' >&2
  exit 1
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
