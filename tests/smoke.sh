#!/usr/bin/env bash
# Сквозная проверка помощника без настоящей нейросети: поддельная Ollama просит
# выполнить команду и записать файл, а мы проверяем, что это действительно сделано.
#
# Использование:
#   tests/smoke.sh python3 agent.py
#   PYTHON=python tests/smoke.sh ./dist/AI-Helper.exe
set -u
cd "$(dirname "$0")/.." || exit 1
PY=${PYTHON:-python3}
PORT=${SMOKE_PORT:-11999}
OUT=smoke_out.txt
FILE=smoke_test_output.txt
rm -f "$OUT" "$FILE"

"$PY" tests/fake_ollama.py "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; rm -f "$OUT" "$FILE"' EXIT
for _ in $(seq 1 40); do
  "$PY" -c "import socket; socket.create_connection(('127.0.0.1', $PORT), 1)" 2>/dev/null && break
  sleep 0.5
done

# просьба, Enter (выполнить команду), Enter (записать файл), выход
printf 'test\n\n\nexit\n' | "$@" --host "127.0.0.1:$PORT" > "$OUT" 2>&1
CODE=$?
cat "$OUT"

fail() { echo "SMOKE FAIL: $1"; exit 1; }
[ "$CODE" -eq 0 ] || fail "код завершения $CODE"
grep -q "ok-5" "$OUT" || fail "команда не выполнилась"
grep -q "smoke-file" "$FILE" 2>/dev/null || fail "файл не записан"
grep -q "DONE" "$OUT" || fail "нет итогового ответа"
echo "SMOKE OK"
