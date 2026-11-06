"""Каталог звуков: страница в браузере — послушать текущий звук и варианты с Freesound, выбрать или оставить.

  python tools/catalog.py            # http://127.0.0.1:8765 (откроется в браузере)
  python tools/catalog.py --port 9000 --no-browser

Работает только на этом компьютере (127.0.0.1), в сеть ничего не отправляет.
Выбор пишет то же, что pick_sounds.py: sounds/<kind>/<id>.wav, sounds/chosen.yaml, sounds/LICENSES.md.
«Оставить» — отметка в sounds/reviewed.yaml (прогресс проверки на слух).
Запущенное приложение перечитывает звук только при перезапуске.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick_sounds as ps  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storyfx.actions import load_actions  # noqa: E402
from storyfx.characters import load_characters  # noqa: E402
from storyfx.scenes import load_scenes  # noqa: E402

PAGE = Path(__file__).resolve().parent / "catalog.html"
QUERIES = ROOT / "data" / "freesound_queries.yaml"
KINDS = ("sfx", "ambience")


def reviewed_path() -> Path:
    return ps.ROOT / "sounds" / "reviewed.yaml"


def load_reviewed() -> dict[str, bool]:
    p = reviewed_path()
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def save_reviewed(rev: dict[str, bool]) -> None:
    reviewed_path().write_text(
        "# Звуки, проверенные владельцем на слух в каталоге (tools/catalog.py)\n"
        + yaml.safe_dump({k: True for k, v in sorted(rev.items()) if v}, allow_unicode=True),
        encoding="utf-8")


def usage() -> dict[str, list[str]]:
    """Кто использует звук: «персонаж: медведь (медведь, мишка)», «действие: …», «сцена: …»."""
    use: dict[str, list[str]] = {}

    def add(key, text):
        use.setdefault(key, []).append(text)

    for g in load_actions():
        for v in g.variants:
            if v.id != "_none":
                add(f"sfx/{v.id}", f"действие «{g.id}»: {v.examples[0]}")
    for c in load_characters():
        add(f"sfx/{c.sound}", f"персонаж: {c.title}")
    scenes, overlays = load_scenes()
    for s in scenes:
        add(f"ambience/{s.ambience}", f"сцена {s.id}: {s.descriptions[0] if s.descriptions else ''}")
    for o in overlays:
        add(f"ambience/{o.ambience}", f"наложение {o.id} (поверх сцены)")
    return use


def catalog() -> list[dict]:
    """Все звуки из freesound_queries.yaml с текущим выбором, вариантами и отметкой «проверено»."""
    q = yaml.safe_load(QUERIES.read_text(encoding="utf-8"))
    chosen, rev, use = ps.load_chosen(), load_reviewed(), usage()
    items = []
    for kind in KINDS:
        for sid in q[kind]:
            key = f"{kind}/{sid}"
            meta = ps.CANDIDATES / kind / sid / "meta.json"
            cands = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else []
            cur = chosen.get(key)
            items.append({
                "key": key, "kind": kind, "id": sid,
                "used_by": use.get(key, []),
                "queries": q[kind][sid]["queries"],
                "current": ({"freesound_id": cur["id"], "name": cur["name"], "username": cur["username"], "url": cur["url"]}
                            if cur else None),
                "has_file": (ps.ROOT / "sounds" / kind / f"{sid}.wav").exists(),
                "reviewed": bool(rev.get(key)),
                "candidates": [{"n": c["n"], "name": c["name"], "username": c["username"],
                                "duration": c["duration"], "url": c["url"], "file": c["file"],
                                "freesound_id": c["id"], "current": bool(cur and cur["id"] == c["id"])}
                               for c in cands],
            })
    return items


def find(key: str) -> tuple[str, str] | None:
    kind, _, sid = key.partition("/")
    if kind not in KINDS or not sid or not all(ch.isalnum() or ch == "_" for ch in sid):
        return None
    return kind, sid


def pick(key: str, n: int) -> dict:
    loc = find(key)
    if not loc:
        raise ValueError(f"нет такого звука: {key}")
    kind, sid = loc
    meta = json.loads((ps.CANDIDATES / kind / sid / "meta.json").read_text(encoding="utf-8"))
    cand = next((m for m in meta if m["n"] == n), None)
    if cand is None:
        raise ValueError(f"{key}: нет варианта №{n}")
    chosen = ps.load_chosen()
    ps.install(kind, sid, cand, chosen)
    rev = load_reviewed()
    rev[key] = True                     # выбрал на слух — значит проверил
    save_reviewed(rev)
    return next(i for i in catalog() if i["key"] == key)


def mark(key: str, ok: bool) -> dict:
    if not find(key):
        raise ValueError(f"нет такого звука: {key}")
    rev = load_reviewed()
    rev[key] = ok
    save_reviewed(rev)
    return next(i for i in catalog() if i["key"] == key)


def audio_path(url_path: str) -> Path | None:
    """/audio/current/sfx/owl.wav → sounds/sfx/owl.wav; /audio/cand/sfx/owl/1_123.wav → кандидат.
    Только .wav внутри своих папок — никаких «../»."""
    parts = [unquote(p) for p in url_path.split("/") if p]
    if len(parts) == 4 and parts[:2] == ["audio", "current"] and parts[2] in KINDS:
        base, rel = ps.ROOT / "sounds" / parts[2], parts[3]
    elif len(parts) == 5 and parts[:2] == ["audio", "cand"] and parts[2] in KINDS:
        base, rel = ps.CANDIDATES / parts[2] / parts[3], parts[4]
    else:
        return None
    p = (base / rel).resolve()
    if p.suffix != ".wav" or base.resolve() not in p.parents or not p.is_file():
        return None
    return p


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):     # тише в консоли
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/sounds":
            return self._json(catalog())
        if path.startswith("/audio/"):
            p = audio_path(path)
            if p is None:
                return self._json({"error": "нет файла"}, HTTPStatus.NOT_FOUND)
            return self._send(200, p.read_bytes(), "audio/wav")
        self._json({"error": "нет такой страницы"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if path == "/api/pick":
                return self._json(pick(body["key"], int(body["n"])))
            if path == "/api/review":
                return self._json(mark(body["key"], bool(body["ok"])))
        except (ValueError, KeyError, TypeError) as e:
            return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        self._json({"error": "нет такого действия"}, HTTPStatus.NOT_FOUND)


def serve(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)    # только этот компьютер


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    srv = serve(args.port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Каталог звуков: {url}   (Ctrl+C — выход)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
