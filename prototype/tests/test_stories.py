"""Сказки целиком (задача 23): что обязано и что не должно прозвучать — tests/story_expectations.yaml.

Каждая проверка — отдельный тест. Известные ошибки (known_failing) помечены «ожидаемо падает» строго:
если такая проверка начала проходить, тест упадёт и попросит убрать её из списка — список честный.
Прогон: tools/story_run.py (движок с моделью смысла, как живая речь). Отчёт для разбора —
  python tools/story_run.py tests/stories/<имя>.txt
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.slow

TESTS = Path(__file__).parent
sys.path.insert(0, str(TESTS.parent / "tools"))
import story_run  # noqa: E402

SPEC = yaml.safe_load((TESTS / "story_expectations.yaml").read_text(encoding="utf-8"))
_RUNS: dict = {}


def checks():
    """(сказка, имя проверки, функция-проверка) для всех сказок."""
    out = []
    lim_default = SPEC["defaults"]["limits"]
    for name, sp in SPEC["stories"].items():
        for kind, ids in (sp.get("expect") or {}).items():
            for i in ids:
                out.append((name, f"expect:{kind}:{i}", ("expect", kind, i)))
        for kind, ids in (sp.get("forbid") or {}).items():
            for i in ids:
                out.append((name, f"forbid:{kind}:{i}", ("forbid", kind, i)))
        for n, rule in enumerate(sp.get("forbid_in") or []):
            out.append((name, f"forbid_in:{n}", ("forbid_in", rule)))
        for what, per in {**lim_default, **(sp.get("limits") or {})}.items():
            out.append((name, f"limit:{what}", ("limit", what, per)))
    return out


def params():
    for name, check_id, check in checks():
        known = check_id in (SPEC["stories"][name].get("known_failing") or [])
        marks = [pytest.mark.xfail(strict=True, reason="известная ошибка, задача 23")] if known else []
        yield pytest.param(name, check, id=f"{name}-{check_id}", marks=marks)


@pytest.fixture(scope="module")
def story_results(embedder):
    def get(name):
        if name not in _RUNS:
            text = (TESTS / "stories" / f"{name}.txt").read_text(encoding="utf-8")
            _RUNS[name] = story_run.run(text, engine=lambda c, log: story_run.build(c, log, embedder=embedder))
        return _RUNS[name]
    return get


def _where(result, kind, i):
    return [n for n, r in enumerate(result, 1) if (kind, i) in r.events]


def describe(result, phrase_nums) -> str:
    return "\n".join(f"  {n}. {result[n - 1].text[:90]}" for n in phrase_nums[:6])


@pytest.mark.parametrize("name,check", list(params()))
def test_story(name, check, story_results):
    result = story_results(name)
    if check[0] == "expect":
        _, kind, i = check
        assert _where(result, kind, i), f"{name}: не прозвучало {kind}={i}"
    elif check[0] == "forbid":
        _, kind, i = check
        bad = _where(result, kind, i)
        assert not bad, f"{name}: лишнее {kind}={i} на фразах:\n{describe(result, bad)}"
    elif check[0] == "forbid_in":
        rule = check[1]
        rx = re.compile(rule["words"], re.I)
        bad = [n for n, r in enumerate(result, 1) if rx.search(r.text)
               for kind, ids in rule.items() if kind != "words" for i in ids if (kind, i) in r.events]
        assert not bad, f"{name}: на фразах со словом /{rule['words']}/ лишний звук {rule}:\n{describe(result, bad)}"
    else:
        _, what, per = check
        kind = "scene" if what == "scene" else "mood"
        changes = sum(1 for r in result for k, _ in r.events if k == kind) - (1 if kind == "scene" else 0)
        allowed = max(1, len(result) // per)
        assert changes <= allowed, f"{name}: смен {what} {changes} на {len(result)} фраз (можно ≤ {allowed})"


def test_known_failing_names_exist():
    """В known_failing — только настоящие имена проверок (опечатка не должна прятать проверку)."""
    names = {(n, c) for n, c, _ in checks()}
    bad = [(n, k) for n, sp in SPEC["stories"].items() for k in (sp.get("known_failing") or []) if (n, k) not in names]
    assert not bad, f"нет таких проверок: {bad}"
