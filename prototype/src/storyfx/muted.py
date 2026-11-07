"""Выключенные звуки (data/muted.yaml): «звук не нужен» — без удаления данных, обратимо.

Персонаж или действие по-прежнему распознаются (журнал), фон сцены по-прежнему определяется —
просто звукорежиссёр не включает этот файл.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import config

MUTED_FILE = config.DATA_DIR / "muted.yaml"
HEADER = ("# Выключенные звуки: распознавание работает (видно в журнале), но звук не играет.\n"
          "# Ведётся кнопкой «Не нужен» / «Вернуть» в каталоге звуков (tools/catalog.py). Формат: kind/id.\n")


def load_muted(path: Path | None = None) -> set[str]:
    path = path or MUTED_FILE
    if not path.exists():
        return set()
    return set((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("muted") or [])


def save_muted(muted: set[str], path: Path | None = None) -> None:
    path = path or MUTED_FILE
    path.write_text(HEADER + yaml.safe_dump({"muted": sorted(muted)}, allow_unicode=True), encoding="utf-8")
