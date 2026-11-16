"""Логика ActionMatcher без модели смысла (запасной классификатор по основам слов).
Качество выбора по смыслу проверяется в test_e2e.py (slow)."""
from storyfx.actions import ActionMatcher, split_clauses
from storyfx.textnorm import tokenize


def sounds(decisions):
    return [d.sfx for d in decisions if d.sfx]


def matcher(actions, clock):
    return ActionMatcher(list(actions), embedder=None, clock=clock)


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


def test_false_friends(actions, clock):
    """Слова, похожие на якоря, но не про тему."""
    m = matcher(actions, clock)
    for i, text in enumerate(["он громко сказал", "совсем стемнело", "огромный зал", "во дворе было тихо"]):
        assert sounds(m.process(text, i, final=True)) == [], text


# ---------- голое слово-якорь и набор текста (задача 23, шаг 3) ----------
def fixed_answer(m, label, conf):
    """Подменить классификатор: проверяем правила решения, а не качество модели."""
    m.classify = lambda group, ctx: (label, conf)
    return m


def test_bare_anchor_needs_confidence_before_phrase_end(actions, clock):
    """«…так воем и воют» — после якоря ни слова: до конца фразы решаем только при уверенности ≥ 0,6."""
    m = fixed_answer(matcher(actions, clock), "wolf_howl", 0.45)
    m.process("а волны так воем и воют", 0, final=False)
    clock.advance(1.0)                                            # все сроки прошли
    assert sounds(m.process("а волны так воем и воют", 0, final=False)) == []
    m2 = fixed_answer(matcher(actions, clock), "wolf_howl", 0.7)
    m2.process("вдалеке завыли", 1, final=False)
    clock.advance(1.0)
    assert sounds(m2.process("вдалеке завыли", 1, final=False)) == ["wolf_howl"]


def test_one_word_clause_needs_confidence_at_phrase_end(actions, clock):
    """В части фразы одно слово-якорь — смысла мало и в конце фразы."""
    m = fixed_answer(matcher(actions, clock), "wolf_howl", 0.45)
    assert sounds(m.process("а волны так воем и воют", 0, final=True)) == []
    assert sounds(m.process("в лесу завыли волки", 1, final=True)) == ["wolf_howl"]   # есть контекст


def test_late_decision_needs_late_conf_then_waits_for_phrase_end(actions, clock):
    """Голос: «девка завыла ну…» — после жёсткого срока нужно ACTION_LATE_CONF (0,5); меньше — решаем
    в конце фразы с полным контекстом, где хватает ACTION_MIN_CONF."""
    m = fixed_answer(matcher(actions, clock), "wolf_howl", 0.46)
    m.process("а девка завыла ну", 0, final=False)
    clock.advance(1.0)                                            # все сроки прошли
    assert sounds(m.process("а девка завыла ну", 0, final=False)) == []
    m2 = fixed_answer(matcher(actions, clock), "wolf_howl", 0.55)
    m2.process("в лесу завыли волки", 1, final=False)
    clock.advance(1.0)
    assert sounds(m2.process("в лесу завыли волки", 1, final=False)) == ["wolf_howl"]


def test_typing_mode_waits_for_meaning_not_clock(actions, clock):
    """Набор текста: слова идут медленно — не решать по секундомеру; ранний выстрел — только при ясном смысле."""
    m = fixed_answer(matcher(actions, clock), "roar", 0.5)
    m.use_deadlines = False
    m.process("а медведь зарычал", 0, final=False)
    clock.advance(5.0)                                            # человек думает над следующим словом
    assert sounds(m.process("а медведь зарычал и", 0, final=False)) == []
    assert sounds(m.process("а медведь зарычал и пошёл", 0, final=True)) == ["roar"]   # фраза закрыта
    m2 = fixed_answer(matcher(actions, clock), "roar", 0.9)
    m2.use_deadlines = False
    assert sounds(m2.process("медведь зарычал грозно", 1, final=False)) == ["roar"]    # смысл ясен — сразу
