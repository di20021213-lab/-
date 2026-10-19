#!/usr/bin/env bash
# Запуск локального ИИ-помощника в Linux/macOS.
cd "$(dirname "$0")" || exit 1
exec python3 agent.py "$@"
