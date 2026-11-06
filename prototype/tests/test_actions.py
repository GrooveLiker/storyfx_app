"""Логика ActionMatcher без модели смысла (запасной классификатор по основам слов).
Качество выбора по смыслу проверяется в test_e2e.py (slow)."""
from storyfx.actions import ActionMatcher, split_clauses
from storyfx.textnorm import tokenize


def sounds(decisions):
    return [d.sfx for d in decisions if d.sfx]


def matcher(actions, clock, mode="dnd"):
    return ActionMatcher(list(actions), embedder=None, mode=mode, clock=clock)


def test_split_clauses():
    toks = tokenize("воин выхватил меч и ударил орка а потом убежал")
    parts = [" ".join(t.word for t in toks[s: e + 1]) for s, e, _ in split_clauses(toks)]
    assert parts == ["воин выхватил меч", "ударил орка", "убежал"]


def test_waits_for_context_on_partials(actions, clock):
    m = matcher(actions, clock)
    assert m.process("орк упал", 0, final=False) == []                     # мало слов после якоря — ждём
    assert "fall" in sounds(m.process("орк упал на землю с грохотом", 0, final=False))


def test_final_decides_immediately(actions, clock):
    m = matcher(actions, clock)
    assert "fall" in sounds(m.process("орк упал", 0, final=True))


def test_no_repeat_within_utterance(actions, clock):
    m = matcher(actions, clock)
    fired = []
    for p in ["орк упал на землю с", "орк упал на землю с грохотом", "орк упал на землю с грохотом прямо"]:
        fired += sounds(m.process(p, 0, final=False))
        clock.advance(5)
    fired += sounds(m.process("орк упал на землю с грохотом прямо", 0, final=True))
    assert fired == ["fall"]


def test_two_events_same_topic(actions, clock):
    m = matcher(actions, clock)
    ds = [d for d in m.process("воин выхватил меч и ударил мечом по щиту", 0, final=True) if d.group == "fight"]
    assert len(ds) == 2


def test_context_crosses_conjunction(actions, clock):
    m = matcher(actions, clock)
    d = [d for d in m.process("девочка подошла к лошадке и ласково погладила", 0, final=True) if d.group == "horse"]
    assert d and "погладила" in d[0].context


def test_negation_in_own_clause_only(actions, clock):
    m = matcher(actions, clock)
    assert sounds(m.process("рыцарь не упал", 0, final=True)) == []
    clock.advance(5)
    assert "fall" in sounds(m.process("орк упал на землю и больше не встал", 1, final=True))
    assert sounds(m.process("дракон так и не зарычал", 2, final=True)) == []
    clock.advance(5)
    assert "fall" in sounds(m.process("орк упал и не встал", 3, final=True))


def test_cooldown(actions, clock):
    m = matcher(actions, clock)
    assert "fall" in sounds(m.process("орк упал на землю", 0, final=True))
    clock.advance(0.5)
    assert "fall" not in sounds(m.process("орк упал на землю", 1, final=True))
    clock.advance(5)
    assert "fall" in sounds(m.process("орк упал на землю", 2, final=True))


def test_kids_mode_skips_scary(actions, clock):
    m = matcher(actions, clock, mode="kids")
    assert "roar" not in sounds(m.process("дракон взревел", 0, final=True))
    assert "explosion" not in sounds(m.process("раздался взрыв", 1, final=True))


def test_false_friends(actions, clock):
    """Слова, похожие на якоря, но не про тему."""
    m = matcher(actions, clock)
    for i, text in enumerate(["он громко сказал", "совсем стемнело", "огромный зал", "во дворе было тихо"]):
        assert sounds(m.process(text, i, final=True)) == [], text
