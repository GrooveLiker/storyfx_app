"""Звуки действий по смыслу фразы.

Как работает:
1. Фраза режется на части по союзам («и», «а», «но», «потом»…).
2. Если в части есть слово-якорь темы (лошадь, меч, дверь…), ждём немного контекста
   (CONTEXT_AFTER слов после якоря или конца части/фразы).
3. Классификатор темы по смыслу части выбирает вариант: «лошадь прискакала» → horse_gallop,
   «погладил лошадь» → horse_snort, «у него была лошадь» → _none (без звука).

Классификатор — логистическая регрессия поверх векторов rubert-tiny2, обучается на примерах
из data/actions.yaml при запуске (около секунды). Без модели смысла (--no-embed) — по
совпадению основ слов с примерами.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import yaml

from . import config
from .textnorm import Pattern, Token, find_matches, is_negated, parse_pattern, tokenize

NONE = "_none"


@dataclass
class Variant:
    id: str
    examples: list[str]


@dataclass
class ActionGroup:
    id: str
    topic: list[Pattern]
    variants: list[Variant]
    cooldown: float = config.DEFAULT_COOLDOWN_S

    @property
    def sounds(self) -> list[str]:
        return [v.id for v in self.variants if v.id != NONE]


@dataclass
class Decision:
    group: str
    sfx: str | None          # None — тема упомянута, но звук не нужен (или запрещён)
    confidence: float
    context: str
    note: str = ""


def load_actions(path: Path = config.DATA_DIR / "actions.yaml") -> list[ActionGroup]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    groups = []
    for gid, g in raw.items():
        variants = [Variant(vid, list(v["examples"])) for vid, v in g["variants"].items()]
        groups.append(ActionGroup(gid, [parse_pattern(p) for p in g["topic"]], variants,
                                  float(g.get("cooldown", config.DEFAULT_COOLDOWN_S))))
    return groups


# ---------- классификаторы ----------
class SoftmaxClassifier:
    """Многоклассовая логистическая регрессия (numpy), обучается за доли секунды."""

    def __init__(self, X: np.ndarray, labels: list[str], iters: int = 1500, lr: float = 0.5, l2: float = 1e-3):
        self.classes = sorted(set(labels))
        y = np.array([self.classes.index(l) for l in labels])
        W = np.zeros((X.shape[1], len(self.classes)))
        b = np.zeros(len(self.classes))
        for _ in range(iters):
            p = self._softmax(X @ W + b)
            p[np.arange(len(y)), y] -= 1
            W -= lr * (X.T @ p / len(y) + l2 * W)
            b -= lr * p.mean(axis=0)
        self.W, self.b = W, b

    @staticmethod
    def _softmax(z):
        z = np.exp(z - z.max(axis=-1, keepdims=True))
        return z / z.sum(axis=-1, keepdims=True)

    def predict(self, x: np.ndarray) -> tuple[str, float]:
        p = self._softmax(x @ self.W + self.b)
        i = int(p.argmax())
        return self.classes[i], float(p[i])


class LexicalClassifier:
    """Запасной вариант без модели смысла: у какого варианта больше общих основ слов с примерами."""

    def __init__(self, group: ActionGroup):
        self.examples = [(v.id, {t.stem for t in tokenize(e)}) for v in group.variants for e in v.examples]

    def predict_text(self, text: str) -> tuple[str, float]:
        stems = {t.stem for t in tokenize(text)}
        best, best_score = NONE, 0.0
        for vid, ex in self.examples:
            score = len(stems & ex) / (len(ex) ** 0.5 + 1e-9)
            if score > best_score:
                best, best_score = vid, score
        return best, min(1.0, best_score)


# ---------- разбор фразы ----------
def split_clauses(tokens: list[Token]) -> list[tuple[int, int, bool]]:
    """Части фразы между союзами: (начало, конец включительно, закрыта ли союзом справа)."""
    out, start = [], 0
    for i, t in enumerate(tokens):
        # «так и не зарычал»: союз перед отрицанием не делит фразу
        nxt = tokens[i + 1].word if i + 1 < len(tokens) else ""
        if t.word in config.CLAUSE_BREAKS and nxt not in config.NEGATIONS:
            if i > start:
                out.append((start, i - 1, True))
            start = i + 1
    if start < len(tokens):
        out.append((start, len(tokens) - 1, False))
    return out


@dataclass
class ActionMatcher:
    groups: list[ActionGroup]
    embedder: object | None = None
    clock: Callable[[], float] = time.monotonic
    use_deadlines: bool = True          # речь: решать не позже ~1 с (D-011). Набор текста: False — по смыслу, не по секундомеру
    _seen: set[tuple[int, int, str]] = field(default_factory=set)    # (фраза, начало части, тема)
    _last_fired: dict[str, float] = field(default_factory=dict)
    _clf: dict[str, object] = field(default_factory=dict)
    _first_seen: dict[tuple, float] = field(default_factory=dict)   # (фраза, часть, тема, якорь) → когда услышали

    def __post_init__(self):
        if self.embedder is not None:
            texts = [e for g in self.groups for v in g.variants for e in v.examples]
            X = self.embedder.encode(texts)
            i = 0
            for g in self.groups:
                labels = [v.id for v in g.variants for _ in v.examples]
                self._clf[g.id] = SoftmaxClassifier(X[i: i + len(labels)], labels)
                i += len(labels)
        else:
            self._clf = {g.id: LexicalClassifier(g) for g in self.groups}

    def classify(self, group: ActionGroup, text: str) -> tuple[str, float]:
        clf = self._clf[group.id]
        if isinstance(clf, LexicalClassifier):
            return clf.predict_text(text)
        return clf.predict(self.embedder.encode([text])[0])

    def process(self, text: str, utterance_id: int, final: bool) -> list[Decision]:
        tokens = tokenize(text)
        clauses = split_clauses(tokens)
        decisions: list[Decision] = []
        now = self.clock()
        for g in self.groups:
            # части фразы, где есть якорь этой темы: (начало, конец, якоря)
            anchored = []
            for start, end, _ in clauses:
                clause = tokens[start: end + 1]
                anchors = sorted({start + m.start for p in g.topic for m in find_matches(p, clause)})
                if anchors:
                    anchored.append((start, end, anchors))
            for k, (start, end, anchors) in enumerate(anchored):
                key = (utterance_id, start, g.id)
                if key in self._seen:
                    continue
                # Контекст после якоря может перейти через союз («подошла к лошадке и погладила её»),
                # но не заходит в следующую часть с якорем той же темы — это уже другое событие.
                limit = anchored[k + 1][0] - 2 if k + 1 < len(anchored) else len(tokens) - 1
                hi = min(limit, anchors[-1] + config.CONTEXT_AFTER)
                # Ждём контекст: фраза закончилась, началось следующее событие темы или набралось N слов.
                # Последние слова частичного результата Vosk ещё может переписать — отсюда запас.
                ready = final or k + 1 < len(anchored) or len(tokens) - 1 >= anchors[-1] + config.CONTEXT_AFTER
                lo = max(start, anchors[0] - config.CONTEXT_BEFORE)
                ctx_tokens = tokens[lo: hi + 1]
                ctx = " ".join(t.word for t in ctx_tokens)
                negated = any(is_negated(tokens, a) for a in anchors)
                label = conf = None
                if not ready:
                    bare = len(tokens) - 1 <= anchors[-1]          # после якоря ещё ни слова
                    if negated or tokens[-1].word in config.PENDING_WORDS:
                        continue        # «дракон так и …» — дальше может быть «не зарычал»
                    if not self.use_deadlines:
                        # набор текста: слова приходят медленно, секундомер врёт — только ранний выстрел,
                        # когда за якорем уже есть слово и смысл ясен; иначе ждём слов или конца фразы
                        if bare:
                            continue
                        label, conf = self.classify(g, ctx)
                        if label == NONE or conf < config.ACTION_EARLY_CONF:
                            continue
                    else:
                        # D-011: звук ≤ 1 с. Чем дольше ждём, тем меньше уверенности нужно:
                        # до SOFT — только ясный смысл (ранний выстрел), потом SOFT_CONF, после HARD — обычный минимум.
                        # Отсчёт — от последнего якоря: «ударил … мечом» — новое слово темы, новая информация.
                        waited = now - self._first_seen.setdefault((*key, anchors[-1]), now)
                        if waited < config.ACTION_SOFT_DEADLINE_S and bare:
                            continue        # рано, и после якоря ещё ни слова
                        label, conf = self.classify(g, ctx)
                        need = (config.ACTION_EARLY_CONF if waited < config.ACTION_SOFT_DEADLINE_S
                                else config.ACTION_SOFT_CONF if waited < config.ACTION_HARD_DEADLINE_S
                                else config.ACTION_LATE_CONF)
                        if bare:
                            # голое слово: «…так воем и воют» (волны) — по одному слову решаем, только если уверены
                            if label == NONE:
                                continue
                            need = max(need, config.ACTION_BARE_CONF)
                        if (label == NONE and waited < config.ACTION_HARD_DEADLINE_S) or (label != NONE and conf < need):
                            continue
                self._seen.add(key)
                # отрицание относится к якорю: «не зарычал», «дождя нет»; «орк упал и не встал» — звук нужен
                if negated:
                    decisions.append(Decision(g.id, None, 1.0, ctx, "отрицание"))
                    continue
                if label is None:
                    label, conf = self.classify(g, ctx)
                variant = next((v for v in g.variants if v.id == label), None)
                if label == NONE or variant is None:
                    decisions.append(Decision(g.id, None, conf, ctx, "по смыслу без звука"))
                elif conf < config.ACTION_MIN_CONF:
                    decisions.append(Decision(g.id, None, conf, ctx, f"не уверен ({label})"))
                elif len(ctx_tokens) <= len(anchors) and conf < config.ACTION_BARE_CONF:
                    # в части фразы — одно слово-якорь («…так воем | и воют»): смысла мало, нужен уверенный ответ
                    decisions.append(Decision(g.id, None, conf, ctx, f"одно слово, не уверен ({label})"))
                elif now - self._last_fired.get(label, -1e9) < g.cooldown:
                    decisions.append(Decision(g.id, None, conf, ctx, f"кулдаун ({label})"))
                else:
                    self._last_fired[label] = now
                    decisions.append(Decision(g.id, label, conf, ctx))
        if final:
            self._seen = {k for k in self._seen if k[0] != utterance_id}
            self._first_seen = {k: v for k, v in self._first_seen.items() if k[0] != utterance_id}
        return decisions
