"""Медленный слой: окно последних слов → сцена (фон) и наложения (погода, огонь, ночь)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import yaml

from . import config
from .textnorm import Pattern, find_matches, is_negated, parse_pattern, tokenize


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


def _has_match(patterns: list[Pattern], tokens) -> bool:
    return any(not is_negated(tokens, m.start, end=m.end) for p in patterns for m in find_matches(p, tokens))


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
    _words: list[str] = field(default_factory=list)
    _candidate: str | None = None
    _candidate_hits: int = 0
    last_scores: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.embedder is not None:
            for s in self.scenes:
                if s.descriptions:
                    v = self.embedder.encode(s.descriptions).mean(axis=0)
                    s.centroid = v / (np.linalg.norm(v) + 1e-9)

    # ---------- входы ----------
    def add_utterance(self, text: str) -> list[Change]:
        """Финальная фраза: обновить окно, наложения и сцену."""
        tokens = tokenize(text)
        self._words = (self._words + [t.word for t in tokens])[-config.SCENE_WINDOW_WORDS:]
        changes = self._update_overlays(tokens)
        # Явное ключевое слово сцены в последней фразе — сменить сразу («вошли в таверну»).
        explicit = [s for s in self.scenes if _has_match(s.keywords, tokens)]
        if explicit:
            vec = self._embed(" ".join(self._words))
            best = max(explicit, key=lambda s: self._score(s, vec, tokens))
            if best.id != self.current:
                self._set(best.id)
                changes.append(Change("scene", best.id, "ключевое слово"))
                return changes
        c = self.evaluate()
        if c:
            changes.append(c)
        return changes

    def evaluate(self, extra_text: str = "") -> Change | None:
        """Оценка по смыслу всего окна (с гистерезисом). Можно вызывать с текущим частичным текстом."""
        text = " ".join(self._words + tokenize_words(extra_text))
        if not text.strip():
            return None
        tokens = tokenize(text)
        vec = self._embed(text)
        scores = {s.id: self._score(s, vec, tokens) for s in self.scenes}
        self.last_scores = scores
        best_id = max(scores, key=scores.get)
        best = scores[best_id]
        cur = scores.get(self.current, 0.0) if self.current else 0.0
        if best_id == self.current or best < config.SCENE_THRESHOLD or best - cur < config.SCENE_MARGIN:
            self._candidate, self._candidate_hits = None, 0
            return None
        if best_id == self._candidate:
            self._candidate_hits += 1
        else:
            self._candidate, self._candidate_hits = best_id, 1
        if self._candidate_hits >= config.SCENE_CONFIRM:
            self._set(best_id)
            return Change("scene", best_id, f"по смыслу ({best:.2f})")
        return None

    # ---------- внутреннее ----------
    def _set(self, scene_id: str) -> None:
        self.current = scene_id
        self._candidate, self._candidate_hits = None, 0
        # Перешли в новое место — слова о прежнем месте больше не голосуют (иначе «…в деревне… пошли в лес…»
        # возвращало деревню: её ключевое слово ещё в окне). D-011.
        self._words = self._words[-config.SCENE_KEEP_AFTER_SWITCH:]

    def _embed(self, text: str) -> np.ndarray | None:
        return self.embedder.encode([text])[0] if self.embedder is not None else None

    def _score(self, scene: Scene, vec: np.ndarray | None, tokens) -> float:
        sim = 0.0
        if vec is not None and scene.centroid is not None:
            sim = float(vec @ scene.centroid)
        kw = sum(1 for p in scene.keywords for m in find_matches(p, tokens) if not is_negated(tokens, m.start, end=m.end))
        return sim + min(kw, 3) * config.KEYWORD_BONUS

    def _update_overlays(self, tokens) -> list[Change]:
        changes = []
        for o in self.overlays:
            if o.id in self.active_overlays and _has_match(o.stop, tokens):
                self.active_overlays.remove(o.id)
                changes.append(Change("overlay_off", o.id, "стоп-фраза"))
            elif o.id not in self.active_overlays and _has_match(o.keywords, tokens) and not _has_match(o.stop, tokens):
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
