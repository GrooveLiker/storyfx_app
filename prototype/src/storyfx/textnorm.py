"""Токенизация, стемминг и сопоставление фраз-шаблонов (общие для триггеров и сцен)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import snowballstemmer

from . import config

_stemmer = snowballstemmer.stemmer("russian")
_WORD_RE = re.compile(r"[а-яa-z0-9]+")


@dataclass(frozen=True)
class Token:
    word: str
    stem: str


@lru_cache(maxsize=50000)
def stem(word: str) -> str:
    return _stemmer.stemWord(word)


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def tokenize(text: str) -> list[Token]:
    return [Token(w, stem(w)) for w in _WORD_RE.findall(normalize(text))]


@dataclass(frozen=True)
class PatternWord:
    kind: str    # "prefix" — слово начинается с value; "stem" — совпадение основ; "word" — точное слово
    value: str

    def matches(self, tok: Token) -> bool:
        if self.kind == "prefix":
            return tok.word.startswith(self.value)
        if self.kind == "stem":
            return tok.stem == self.value
        return tok.word == self.value


@dataclass(frozen=True)
class Pattern:
    words: tuple[PatternWord, ...]
    source: str

    @property
    def specificity(self) -> tuple[int, int]:
        """Длиннее и точнее — важнее (для разрешения пересечений)."""
        return (len(self.words), sum(w.kind != "prefix" for w in self.words))


def parse_pattern(phrase: str) -> Pattern:
    words = []
    for raw in normalize(phrase).split():
        if raw.endswith("*"):
            words.append(PatternWord("prefix", raw[:-1]))
        else:
            s = stem(raw)
            # слишком короткая основа («вой» → «во») совпадёт с предлогами — сравниваем слово целиком
            words.append(PatternWord("stem", s) if len(s) >= 3 else PatternWord("word", raw))
    if not words:
        raise ValueError(f"пустая фраза: {phrase!r}")
    return Pattern(tuple(words), phrase)


@dataclass(frozen=True)
class Match:
    pattern: Pattern
    start: int
    end: int        # индекс последнего слова совпадения (включительно)


def find_matches(pattern: Pattern, tokens: list[Token], max_gap: int = config.MAX_GAP_WORDS) -> list[Match]:
    out = []
    first, rest = pattern.words[0], pattern.words[1:]
    for i, tok in enumerate(tokens):
        if not first.matches(tok):
            continue
        pos, ok = i, True
        for pw in rest:
            for j in range(pos + 1, min(len(tokens), pos + 2 + max_gap)):
                if pw.matches(tokens[j]):
                    pos = j
                    break
            else:
                ok = False
                break
        if ok:
            out.append(Match(pattern, i, pos))
    return out


def is_negated(tokens: list[Token], start: int, window: int = config.NEGATION_WINDOW,
               end: int | None = None) -> bool:
    """«не упал», «без дождя» — отрицание перед словом; «дождя нет», «дождя не было» — после."""
    if any(t.word in config.NEGATIONS for t in tokens[max(0, start - window): start]):
        return True
    after = [t.word for t in tokens[(end if end is not None else start) + 1:][:2]]
    return after[:1] == ["нет"] or (after[:1] == ["не"] and len(after) > 1 and after[1].startswith("был"))
