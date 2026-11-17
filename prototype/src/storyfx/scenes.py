"""Медленный слой: окно последних слов → сцена (фон) и наложения (погода, огонь, ночь)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache
from typing import Protocol

import numpy as np
import yaml

from . import config
from .textnorm import Pattern, find_matches, is_comparison, is_negated, parse_pattern, tokenize


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray:
        """Возвращает нормированные векторы смысла, форма (len(texts), dim)."""


class RuBertEmbedder:
    """cointegrated/rubert-tiny2 через sentence-transformers (~30 МБ параметров, CPU)."""

    def __init__(self, model_name: str = config.EMBED_MODEL_NAME):
        import os
        cached = config.HF_CACHE_DIR / ("models--" + model_name.replace("/", "--")) / "snapshots"
        if cached.exists() and any(cached.iterdir()):
            os.environ["HF_HUB_OFFLINE"] = "1"   # модель уже скачана — в сеть не ходим
        from sentence_transformers import SentenceTransformer  # тяжёлый импорт — только по требованию
        self.model = SentenceTransformer(model_name, cache_folder=str(config.HF_CACHE_DIR), device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True))


@dataclass
class Scene:
    id: str
    ambience: str
    descriptions: list[str]
    keywords: list[Pattern]
    centroid: np.ndarray | None = None


@dataclass
class Overlay:
    id: str
    ambience: str
    keywords: list[Pattern]
    stop: list[Pattern]


def load_scenes(path: Path = config.DATA_DIR / "scenes.yaml") -> tuple[list[Scene], list[Overlay]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenes = [
        Scene(sid, s["ambience"], list(s.get("descriptions", [])),
              [parse_pattern(k) for k in s.get("keywords", [])])
        for sid, s in raw["scenes"].items()
    ]
    overlays = [
        Overlay(oid, o["ambience"], [parse_pattern(k) for k in o.get("keywords", [])],
                [parse_pattern(k) for k in o.get("stop", [])])
        for oid, o in raw.get("overlays", {}).items()
    ]
    return scenes, overlays


def _real(tokens, m) -> bool:
    """Совпадение — по-настоящему: не «дождя не было» и не «как гроза разразилась»."""
    return not is_negated(tokens, m.start, end=m.end) and not is_comparison(tokens, m.start)


@lru_cache(maxsize=1)
def _far_words() -> frozenset[str]:
    raw = yaml.safe_load((config.DATA_DIR / "scenes.yaml").read_text(encoding="utf-8"))
    return frozenset(raw.get("far_words", []))


@lru_cache(maxsize=1)
def _not_place_near() -> tuple[Pattern, ...]:
    raw = yaml.safe_load((config.DATA_DIR / "scenes.yaml").read_text(encoding="utf-8"))
    return tuple(parse_pattern(w) for w in raw.get("not_place_near", []))


def _not_a_place(tokens, start: int, end: int) -> bool:
    """«вскрыл замок отмычкой» — дверной замок, а не замок короля: рядом слова про ключи и замки."""
    near = tokens[max(0, start - 3): start] + tokens[end + 1: end + 4]
    return any(find_matches(p, near) for p in _not_place_near())


def _is_far(tokens, start: int) -> bool:
    """«пропали за тёмным лесом», «вдалеке за рекой» — место вдали, не то, где герой."""
    return any(t.word in _far_words() for t in tokens[max(0, start - 2): start])


def _has_place(patterns: list[Pattern], tokens, skip: frozenset[int] = frozenset()) -> bool:
    """Как _has_match, но место вдали («за лесом») не считается: сцену меняет только то, где герой."""
    return any(_real(tokens, m) and m.start not in skip and not _is_far(tokens, m.start)
               and not _not_a_place(tokens, m.start, m.end)
               for p in patterns for m in find_matches(p, tokens))


def _has_match(patterns: list[Pattern], tokens, skip: frozenset[int] = frozenset()) -> bool:
    """skip — номера слов в репликах героев: «Печка, печка, скажи…» не переносит рассказ в избу."""
    return any(_real(tokens, m) and m.start not in skip for p in patterns for m in find_matches(p, tokens))


@dataclass
class Change:
    kind: str        # "scene" | "overlay_on" | "overlay_off"
    id: str | None
    reason: str


@dataclass
class SceneTracker:
    scenes: list[Scene]
    overlays: list[Overlay]
    embedder: Embedder | None = None
    current: str | None = None
    active_overlays: list[str] = field(default_factory=list)
    # Смена ПО СМЫСЛУ (ключевое слово в фразе меняет сразу). Настроение — тот же трекер со своими числами (mood.py).
    threshold: float = config.SCENE_THRESHOLD   # оценка победителя не ниже
    margin: float = config.SCENE_MARGIN         # и выше текущей хотя бы на столько
    confirm: int = config.SCENE_CONFIRM         # столько оценок подряд
    min_words: int = config.SCENE_MIN_WORDS     # меньше слов в окне — не оценивать (2–3 слова — шум)
    min_dwell: int = config.SCENE_MIN_DWELL     # фраз после смены, пока по смыслу не меняем
    # Только для настроения: напряжённость. Переход к более напряжённому — без выдержки min_dwell
    # (живой тест 2026-11-17: после «пустился в пляс» ворвался разбойник, а музыка ещё 90 с была весёлой).
    intensity: dict[str, float] | None = None
    _words: list[str] = field(default_factory=list)
    _candidate: str | None = None
    _candidate_hits: int = 0
    _since_switch: int = 10**6                   # фраз с последней смены
    last_scores: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.embedder is not None:
            for s in self.scenes:
                if s.descriptions:
                    v = self.embedder.encode(s.descriptions).mean(axis=0)
                    s.centroid = v / (np.linalg.norm(v) + 1e-9)

    # ---------- входы ----------
    def add_utterance(self, text: str, speech: tuple[bool, ...] | None = None) -> list[Change]:
        """Финальная фраза: обновить окно, наложения и сцену.
        speech — какие слова в репликах героев (для текста): они не меняют место и погоду
        и не попадают в окно смысла сцены («— Печка, печка, скажи…» — разговор, а не изба)."""
        tokens = tokenize(text)
        spoken = frozenset(i for i, f in enumerate(speech) if f) if speech and len(speech) == len(tokens) else frozenset()
        narration = [t.word for i, t in enumerate(tokens) if i not in spoken]
        self._words = (self._words + narration)[-config.SCENE_WINDOW_WORDS:]
        self._since_switch += 1
        changes = self._update_overlays(tokens, spoken)
        # Явное ключевое слово сцены в последней фразе — сменить сразу («вошли в таверну»).
        explicit = [s for s in self.scenes if _has_place(s.keywords, tokens, spoken)]
        if explicit:
            vec = self._embed(" ".join(self._words))
            best = max(explicit, key=lambda s: self._score(s, vec, tokens))
            if best.id != self.current:
                self._set(best.id, keep=len(narration))  # новое место названо в этой фразе — помним только её
                changes.append(Change("scene", best.id, "ключевое слово"))
                return changes
        c = self.evaluate()
        if c:
            changes.append(c)
        return changes

    def evaluate(self, extra_text: str = "") -> Change | None:
        """Оценка по смыслу всего окна (с гистерезисом). Можно вызывать с текущим частичным текстом."""
        words = self._words + tokenize_words(extra_text)
        if not words:
            return None
        text = " ".join(words)
        tokens = tokenize(text)
        vec = self._embed(text)
        scores = {s.id: self._score(s, vec, tokens) for s in self.scenes}
        self.last_scores = scores
        if len(words) < self.min_words:
            return None       # «на опушке» — ещё не смысл
        best_id = max(scores, key=scores.get)
        if self._since_switch < self.min_dwell and not self._escalates(best_id):
            return None       # только что сменили — дать постоять
        best = scores[best_id]
        cur = scores.get(self.current, 0.0) if self.current else 0.0
        if best_id == self.current or best < self.threshold or best - cur < self.margin:
            self._candidate, self._candidate_hits = None, 0
            return None
        if best_id == self._candidate:
            self._candidate_hits += 1
        else:
            self._candidate, self._candidate_hits = best_id, 1
        if self._candidate_hits >= self.confirm:
            self._set(best_id)
            return Change("scene", best_id, f"по смыслу ({best:.2f})")
        return None

    # ---------- внутреннее ----------
    def _escalates(self, target: str) -> bool:
        if not self.intensity or self.current is None:
            return False
        return self.intensity.get(target, 0.0) > self.intensity.get(self.current, 0.0)

    def _set(self, scene_id: str, keep: int | None = None) -> None:
        self.current = scene_id
        self._candidate, self._candidate_hits = None, 0
        self._since_switch = 0
        # Перешли в новое место — слова о прежнем месте больше не голосуют (иначе «…в деревне… пошли в лес…»
        # возвращало деревню: её ключевое слово ещё в окне). D-011. Место названо в фразе — оставляем только её
        # (при коротких фразах «последние 8 слов» захватывали «…в деревне» из предыдущей).
        n = keep if keep is not None else config.SCENE_KEEP_AFTER_SWITCH
        self._words = self._words[-n:] if n > 0 else []

    def _embed(self, text: str) -> np.ndarray | None:
        return self.embedder.encode([text])[0] if self.embedder is not None else None

    def _score(self, scene: Scene, vec: np.ndarray | None, tokens) -> float:
        sim = 0.0
        if vec is not None and scene.centroid is not None:
            sim = float(vec @ scene.centroid)
        kw = sum(1 for p in scene.keywords for m in find_matches(p, tokens) if _real(tokens, m))
        return sim + min(kw, 3) * config.KEYWORD_BONUS

    def _update_overlays(self, tokens, spoken: frozenset[int] = frozenset()) -> list[Change]:
        changes = []
        for o in self.overlays:
            if o.id in self.active_overlays and _has_match(o.stop, tokens, spoken):
                self.active_overlays.remove(o.id)
                changes.append(Change("overlay_off", o.id, "стоп-фраза"))
            elif (o.id not in self.active_overlays and _has_match(o.keywords, tokens, spoken)
                  and not _has_match(o.stop, tokens, spoken)):
                self.active_overlays.append(o.id)
                changes.append(Change("overlay_on", o.id, "ключевое слово"))
                while len(self.active_overlays) > config.MAX_OVERLAYS:
                    old = self.active_overlays.pop(0)
                    changes.append(Change("overlay_off", old, "вытеснено новым"))
        return changes

    def ambience_for(self, scene_id: str | None) -> str | None:
        return next((s.ambience for s in self.scenes if s.id == scene_id), None)

    def overlay_ambience(self, overlay_id: str) -> str:
        return next(o.ambience for o in self.overlays if o.id == overlay_id)


def tokenize_words(text: str) -> list[str]:
    return [t.word for t in tokenize(text)]
