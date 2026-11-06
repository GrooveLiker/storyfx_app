"""Скачивает кандидатов-звуков с Freesound (только CC0) и готовит их к прослушиванию.

Ключ API: файл prototype/.freesound_key (одна строка) или переменная FREESOUND_API_KEY.
Получить: https://freesound.org/apiv2/apply/ → «Client secret/Api key».

  python tools/fetch_freesound.py                 # кандидаты для всех звуков, у кого их ещё нет
  python tools/fetch_freesound.py --only owl,bell # только эти
  python tools/fetch_freesound.py --chosen        # скачать уже выбранные (sounds/chosen.yaml) — на новом компьютере

Кандидаты: sounds/candidates/<sfx|ambience>/<id>/<N>_<freesound_id>.wav + meta.json.
Выбор лучшего на слух: tools/pick_sounds.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storyfx.soundproc import decode, process_ambience, process_sfx, write_wav  # noqa: E402

API = "https://freesound.org/apiv2"
QUERIES = ROOT / "data" / "freesound_queries.yaml"
CANDIDATES = ROOT / "sounds" / "candidates"
CHOSEN = ROOT / "sounds" / "chosen.yaml"
KEY_FILE = ROOT / ".freesound_key"
FIELDS = "id,name,username,license,duration,previews,url,num_downloads,avg_rating"
CC0 = "publicdomain/zero"
MAX_PER_AUTHOR = 2


def api_key() -> str:
    key = os.environ.get("FREESOUND_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8-sig").strip()
    if not key:
        sys.exit(f"Нет ключа Freesound. Сохраните его в {KEY_FILE} (см. docs/sounds.md).")
    return key


class Freesound:
    def __init__(self, key: str):
        self.key = key

    def get(self, path: str, **params) -> dict:
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Token {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("Freesound отклонил ключ (401). Проверьте .freesound_key — нужен «Client secret/Api key».")
            raise
        finally:
            time.sleep(1.1)      # лимит API — 60 запросов в минуту

    def search(self, query: str, dmin: float, dmax: float, page_size: int = 30) -> list[dict]:
        params = dict(query=query, page_size=page_size, fields=FIELDS,
                      filter=f'license:"Creative Commons 0" duration:[{dmin} TO {dmax}]')
        try:
            return self.get("/search/text/", **params).get("results", [])
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            return self.get("/search/", **params).get("results", [])   # новый адрес поиска в API

    def sound(self, sound_id: int) -> dict:
        return self.get(f"/sounds/{sound_id}/", fields=FIELDS)


def rank(results: list[dict]) -> list[dict]:
    """Только CC0 (проверяем сами, не доверяя фильтру), популярные и хорошо оценённые — выше."""
    ok = [r for r in results if CC0 in r.get("license", "")]
    return sorted(ok, key=lambda r: -(math.log1p(r.get("num_downloads", 0)) * (1 + r.get("avg_rating", 0) / 5)))


def download(url: str, dst: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as r:
        dst.write_bytes(r.read())


def prepare(meta: dict, kind: str, spec: dict, out_wav: Path) -> None:
    """Скачать превью (mp3 высокого качества), обработать и сохранить WAV."""
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "src.mp3"
        download(meta["previews"]["preview-hq-mp3"], mp3)
        x = decode(mp3)
    y = process_ambience(x, spec["cut"]) if kind == "ambience" else process_sfx(x, spec["cut"])
    write_wav(out_wav, y)


def meta_record(r: dict) -> dict:
    return {k: r[k] for k in ("id", "name", "username", "license", "duration", "url")}


def fetch_candidates(fs: Freesound, kind: str, sid: str, spec: dict, count: int) -> int:
    folder = CANDIDATES / kind / sid
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.wav"):      # перекачка (--force): старые кандидаты не смешиваем с новыми
        old.unlink()
    seen, metas = set(), []
    for q in spec["queries"]:
        for r in rank(fs.search(q, spec["min"], spec["max"])):
            if len(metas) >= count:
                break
            if r["id"] in seen:
                continue
            # не больше 2 от одного автора: звуки из одного набора обычно похожи — выбор беднее
            if sum(m["username"] == r["username"] for m in metas) >= MAX_PER_AUTHOR:
                continue
            seen.add(r["id"])
            n = len(metas) + 1
            wav = folder / f"{n}_{r['id']}.wav"
            try:
                prepare(r, kind, spec, wav)
            except Exception as e:        # битый файл, слишком короткий фон и т.п. — берём следующий
                print(f"    пропуск {r['id']} ({r['name'][:40]}): {e}")
                continue
            metas.append({"n": n, "file": wav.name, "query": q, **meta_record(r)})
            print(f"    {n}. {r['name'][:60]} — {r['username']} ({r['duration']:.1f} с)")
        if len(metas) >= count:
            break
    (folder / "meta.json").write_text(json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(metas)


def fetch_chosen(fs: Freesound) -> None:
    chosen = yaml.safe_load(CHOSEN.read_text(encoding="utf-8")) or {}
    specs = yaml.safe_load(QUERIES.read_text(encoding="utf-8"))
    for key, c in chosen.items():
        kind, sid = key.split("/")
        out = ROOT / "sounds" / kind / f"{sid}.wav"
        print(f"{key}: freesound #{c['id']}")
        prepare(fs.sound(c["id"]), kind, specs[kind][sid], out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="через запятую: id звуков (sword_clash,forest)")
    ap.add_argument("--count", type=int, default=5, help="кандидатов на звук")
    ap.add_argument("--force", action="store_true", help="перекачать, даже если кандидаты уже есть")
    ap.add_argument("--chosen", action="store_true", help="скачать выбранные звуки из sounds/chosen.yaml")
    args = ap.parse_args()
    fs = Freesound(api_key())
    if args.chosen:
        fetch_chosen(fs)
        return 0
    only = set(args.only.split(",")) if args.only else None
    specs = yaml.safe_load(QUERIES.read_text(encoding="utf-8"))
    if only:
        unknown = only - set(specs["sfx"]) - set(specs["ambience"])
        if unknown:
            sys.exit(f"Нет таких звуков в {QUERIES.name}: {', '.join(sorted(unknown))}")
    total = 0
    for kind in ("sfx", "ambience"):
        for sid, spec in specs[kind].items():
            if only and sid not in only:
                continue
            if (CANDIDATES / kind / sid / "meta.json").exists() and not args.force:
                continue
            print(f"[{kind}] {sid}")
            got = fetch_candidates(fs, kind, sid, spec, args.count)
            total += got
            if got == 0:
                print("    ничего не нашлось — поправьте запросы в data/freesound_queries.yaml")
    print(f"Готово: {total} кандидатов в {CANDIDATES}. Дальше: python tools/pick_sounds.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
