"""Прослушать кандидатов с Freesound и выбрать лучший звук для каждого id.

  python tools/pick_sounds.py            # по очереди все звуки, у которых есть кандидаты и ещё нет выбора
  python tools/pick_sounds.py --only owl # только этот (можно переизбрать)
  python tools/pick_sounds.py --auto     # без прослушивания: взять кандидата №1 везде, где нет выбора

Выбранный файл копируется в sounds/<sfx|ambience>/<id>.wav (поверх заглушки),
запись — в sounds/chosen.yaml (в git), авторы — в sounds/LICENSES.md.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "sounds" / "candidates"
CHOSEN = ROOT / "sounds" / "chosen.yaml"
LICENSES = ROOT / "sounds" / "LICENSES.md"

HELP = "  номер — прослушать · «+» — выбрать последний прослушанный · Enter — дальше без выбора · q — выход"


def load_chosen() -> dict:
    return (yaml.safe_load(CHOSEN.read_text(encoding="utf-8")) or {}) if CHOSEN.exists() else {}


def save_chosen(chosen: dict) -> None:
    CHOSEN.write_text(
        "# Выбранные звуки Freesound (CC0). Восстановить файлы: python tools/fetch_freesound.py --chosen\n"
        + yaml.safe_dump(dict(sorted(chosen.items())), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| {k}.wav | {c['url']} | {c['username']} | CC0 1.0 | обрезка, громкость{', петля' if k.startswith('ambience') else ''} |"
        for k, c in sorted(chosen.items())
    )
    LICENSES.write_text(
        "# Лицензии звуков\n\n"
        "Файлы, не перечисленные ниже, синтезированы `tools/gen_sounds.py` — собственная работа проекта.\n"
        "Внешние звуки — только CC0 (общественное достояние, указание автора не требуется, но мы указываем).\n\n"
        "| Файл | Источник | Автор | Лицензия | Изменения |\n|---|---|---|---|---|\n" + rows + "\n",
        encoding="utf-8",
    )


def install(kind: str, sid: str, cand: dict, chosen: dict) -> None:
    src = CANDIDATES / kind / sid / cand["file"]
    shutil.copyfile(src, ROOT / "sounds" / kind / f"{sid}.wav")
    chosen[f"{kind}/{sid}"] = {k: cand[k] for k in ("id", "name", "username", "url", "license")}
    save_chosen(chosen)
    print(f"  ✓ {kind}/{sid} ← {cand['name']} ({cand['username']})")


def folders(only: set[str] | None):
    for kind in ("sfx", "ambience"):
        for d in sorted((CANDIDATES / kind).glob("*")):
            if (d / "meta.json").exists() and (not only or d.name in only):
                yield kind, d.name, json.loads((d / "meta.json").read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="через запятую: id звуков")
    ap.add_argument("--auto", action="store_true", help="взять кандидата №1 без прослушивания")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    chosen = load_chosen()

    if args.auto:
        for kind, sid, metas in folders(only):
            if metas and (only or f"{kind}/{sid}" not in chosen):
                install(kind, sid, metas[0], chosen)
        return 0

    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    pygame.mixer.init(44100, -16, 2, 512)
    print(HELP)
    for kind, sid, metas in folders(only):
        key = f"{kind}/{sid}"
        if not metas or (key in chosen and not only):
            continue
        print(f"\n=== {key} ===" + (f"  (сейчас: {chosen[key]['name']})" if key in chosen else ""))
        for c in metas:
            print(f"  {c['n']}. {c['name'][:60]} — {c['username']}")
        last = None
        while True:
            cmd = input("> ").strip().lower()
            if cmd == "q":
                return 0
            if cmd == "":
                break
            if cmd == "+" and last:
                install(kind, sid, last, chosen)
                break
            c = next((m for m in metas if str(m["n"]) == cmd), None)
            if c is None:
                print(HELP)
                continue
            pygame.mixer.stop()
            snd = pygame.mixer.Sound(str(CANDIDATES / kind / sid / c["file"]))
            snd.play(maxtime=8000 if kind == "ambience" else 0, fade_ms=300 if kind == "ambience" else 0)
            last = c
    return 0


if __name__ == "__main__":
    sys.exit(main())
