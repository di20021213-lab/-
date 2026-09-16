"""Загрузка config.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class Config(dict):
    """dict с доступом через точечный путь: cfg.get_path('sending.max_per_hour')."""

    def get_path(self, path: str, default: Any = None) -> Any:
        node: Any = self
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def selectors(self, name: str) -> list[str]:
        value = self.get_path(f"selectors.{name}", [])
        return list(value) if value else []


def load_config(path: str = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"Нет {p}. Скопируйте config.example.yaml в {p} и заполните."
        )
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Config(data)
