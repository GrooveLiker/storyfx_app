"""Каталог звуков: страница в браузере — послушать текущий звук и варианты с Freesound, выбрать или оставить.
Плюс «Тест озвучки» (live_session.py): текст или диктовка → настоящий движок → звук из колонок.

  python tools/catalog.py            # http://127.0.0.1:8765 (откроется в браузере)
  python tools/catalog.py --port 9000 --no-browser

Сервер доступен только с этого компьютера (127.0.0.1). В интернет ходит одна кнопка — «Найти другие»:
поиск на Freesound, как tools/fetch_freesound.py (инструмент разработчика, CLAUDE.md правило 5).
Выбор пишет то же, что pick_sounds.py: sounds/<kind>/<id>.wav, sounds/chosen.yaml, sounds/LICENSES.md.
«Оставить» — отметка в sounds/reviewed.yaml (прогресс проверки на слух).
«Свой файл» — запись владельца: обработка как у Freesound, копия в sounds/own/ (в git), лицензия «своя».
«Не нужен» — звук выключен (data/muted.yaml), распознавание остаётся; «Вернуть» — включить.
Запущенное приложение перечитывает звук только при перезапуске (тест озвучки — сразу).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_freesound as ff  # noqa: E402
import pick_sounds as ps  # noqa: E402
from live_session import LiveSession  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storyfx import muted as mt  # noqa: E402
from storyfx import soundproc as sp  # noqa: E402
from storyfx.actions import load_actions  # noqa: E402
from storyfx.characters import load_characters  # noqa: E402
from storyfx.scenes import load_scenes  # noqa: E402

PAGE = Path(__file__).resolve().parent / "catalog.html"
QUERIES = ROOT / "data" / "freesound_queries.yaml"
KINDS = ("sfx", "ambience")
MAX_UPLOAD = 25 * 1024 * 1024          # своя запись — не больше 25 МБ
UPLOAD_TYPES = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aiff", ".aif"}
JOBS: dict[str, dict] = {}             # «Найти другие» в фоне: key → {"state": running|done|error, "msg": …}


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
    chosen, rev, use, muted = ps.load_chosen(), load_reviewed(), usage(), mt.load_muted()
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
                "muted": key in muted,
                "own": bool(cur and cur.get("license") == ps.OWN_LICENSE),
                "job": JOBS.get(key),
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


def item(key: str) -> dict:
    return next(i for i in catalog() if i["key"] == key)


def set_muted(key: str, on: bool) -> dict:
    """«Не нужен» / «Вернуть»: звук выключается без удаления данных."""
    if not find(key):
        raise ValueError(f"нет такого звука: {key}")
    muted = mt.load_muted()
    (muted.add if on else muted.discard)(key)
    mt.save_muted(muted)
    return item(key)


def _spec(kind: str, sid: str) -> dict:
    return yaml.safe_load(QUERIES.read_text(encoding="utf-8"))[kind][sid]


def search(key: str, queries: list[str], count: int = 5, wait: bool = False) -> dict:
    """«Найти другие»: свои запросы → новые варианты с Freesound (в фоне). Удачные запросы сохраняются."""
    loc = find(key)
    queries = [q.strip() for q in queries if q.strip()][:6]
    if not loc or not queries:
        raise ValueError("нужен звук и хотя бы один запрос")
    if (JOBS.get(key) or {}).get("state") == "running":
        raise ValueError("поиск уже идёт")
    kind, sid = loc
    spec = {**_spec(kind, sid), "queries": queries}
    JOBS[key] = {"state": "running", "msg": f"ищу на Freesound: {', '.join(queries)}…"}

    def job():
        try:
            got = ff.fetch_candidates(ff.Freesound(ff.api_key()), kind, sid, spec, max(1, min(int(count), 10)))
            if got:
                ff.set_queries(kind, sid, queries, QUERIES)
                JOBS[key] = {"state": "done", "msg": f"новых вариантов: {got}. Запросы сохранены."}
            else:
                JOBS[key] = {"state": "error", "msg": "ничего не нашлось — попробуйте другие слова (по-английски, коротко)"}
        except SystemExit as e:               # api_key(): нет ключа
            JOBS[key] = {"state": "error", "msg": str(e)}
        except Exception as e:                # сеть, лимит API, ffmpeg
            JOBS[key] = {"state": "error", "msg": f"ошибка: {e}"}

    t = threading.Thread(target=job, daemon=True)
    t.start()
    if wait:
        t.join()
    return item(key)


def upload(key: str, filename: str, data: bytes) -> dict:
    """«Свой файл»: обработать как звук с Freesound, добавить вариантом и сразу поставить."""
    loc = find(key)
    if not loc:
        raise ValueError(f"нет такого звука: {key}")
    ext = Path(filename).suffix.lower()
    if ext not in UPLOAD_TYPES:
        raise ValueError(f"нужен аудиофайл ({', '.join(sorted(UPLOAD_TYPES))})")
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("файл пустой или больше 25 МБ")
    kind, sid = loc
    spec = _spec(kind, sid)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"upload{ext}"
        src.write_bytes(data)
        try:
            x = sp.decode(src)
        except Exception as e:
            raise ValueError(f"не удалось прочитать файл: {e}") from e
    if len(x) < sp.SR * 0.1:
        raise ValueError("слишком короткая запись")
    y = sp.process_ambience(x, spec["cut"]) if kind == "ambience" else sp.process_sfx(x, spec["cut"])
    folder = ps.CANDIDATES / kind / sid
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "meta.json"
    metas = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else []
    n = max([m["n"] for m in metas], default=0) + 1
    own_id = f"own-{int(time.time())}"
    wav = folder / f"{n}_{own_id}.wav"
    sp.write_wav(wav, y)
    metas.append({"n": n, "file": wav.name, "query": "свой файл", "id": own_id, "name": Path(filename).name,
                  "username": "владелец", "license": ps.OWN_LICENSE, "duration": round(len(x) / sp.SR, 1), "url": ""})
    meta_path.write_text(json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    return pick(key, n)


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
    session: LiveSession | None = None     # «Тест озвучки» — один на сервер, создаётся в serve()

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
        if path == "/api/item":                     # опрос «Найти другие», пока идёт поиск
            key = parse_qs(urlparse(self.path).query).get("key", [""])[0]
            if not find(key):
                return self._json({"error": "нет такого звука"}, HTTPStatus.NOT_FOUND)
            return self._json(item(key))
        if path == "/api/live/state":
            since = parse_qs(urlparse(self.path).query).get("since", ["0"])[0]
            return self._json(self.session.state(int(since) if since.isdigit() else 0))
        if path.startswith("/audio/"):
            p = audio_path(path)
            if p is None:
                return self._json({"error": "нет файла"}, HTTPStatus.NOT_FOUND)
            return self._send(200, p.read_bytes(), "audio/wav")
        self._json({"error": "нет такой страницы"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        try:
            size = int(self.headers.get("Content-Length", 0))
            if path == "/api/upload":                  # тело — сам файл; key и name — в адресе
                if size > MAX_UPLOAD:
                    raise ValueError("файл больше 25 МБ")
                qs = parse_qs(url.query)
                it = upload(qs.get("key", [""])[0], qs.get("name", [""])[0], self.rfile.read(size))
                self.session.sound_changed()
                return self._json(it)
            body = json.loads(self.rfile.read(size) or b"{}")
            if path == "/api/pick":
                it = pick(body["key"], int(body["n"]))
                self.session.sound_changed()          # тест озвучки возьмёт новый файл
                return self._json(it)
            if path == "/api/review":
                return self._json(mark(body["key"], bool(body["ok"])))
            if path == "/api/mute":
                it = set_muted(body["key"], bool(body["on"]))
                self.session.muted_changed()
                return self._json(it)
            if path == "/api/search":
                return self._json(search(body["key"], list(body["queries"]), int(body.get("count", 5))))
            s = self.session
            if path == "/api/live/start":
                s.ensure_engine()
                return self._json(s.state())
            if path == "/api/live/say":
                return self._json({"phrases": s.say(str(body["text"]), str(body.get("tempo", "normal")))})
            if path == "/api/live/mic":
                s.mic_start() if body.get("on") else s.mic_stop()
                return self._json(s.state())
            if path == "/api/live/stop":
                s.stop()
                return self._json(s.state())
            if path == "/api/live/music":
                s.set_music(bool(body["on"]))
                return self._json(s.state())
        except (ValueError, KeyError, TypeError) as e:
            return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        self._json({"error": "нет такого действия"}, HTTPStatus.NOT_FOUND)


def serve(port: int, session: LiveSession | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"session": session or LiveSession()})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)    # только этот компьютер


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
