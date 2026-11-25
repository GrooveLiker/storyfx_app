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


def test_repeated_anchor_is_the_same_event(actions, clock):
    """«Дождь всё шёл и шёл» — повтор того же якоря в той же фразе — то же событие: первое «шёл»
    решено «без звука» (дождь не ходит), повтор молчит — его окно узкое, без подлежащего
    (контрольная №4, 2026-11-25: «шёл и жучка тряхнула» давал шаги)."""
    m = matcher(actions, clock)
    ds = m.process("дождь всё шёл и шёл, и собака тряхнула мокрой шерстью", 0, final=True)
    assert "footsteps" not in sounds(ds)
    # контроль: настоящая ходьба звучит, и повтор «шли» ей не мешает
    m2 = matcher(actions, clock)
    assert "footsteps" in sounds(m2.process("они шли и шли по каменным плитам", 0, final=True))


def test_listened_how_is_not_simile(actions, clock):
    """«Слушали, как трещат дрова в печи» — «как» после глагола восприятия не сравнение;
    звука мороза всё равно нет: треск дров — не треск мороза (примеры _none, контрольная №4)."""
    m = matcher(actions, clock)
    ds = m.process("слушали, как трещат дрова в печи", 0, final=True)
    assert "frost_crackle" not in sounds(ds)
    assert not any(d.note == "сравнение" for d in ds)            # решено по смыслу, не отмахнулись
    m2 = matcher(actions, clock)
    assert "frost_crackle" in sounds(m2.process("мороз пуще затрещал", 0, final=True))


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


def test_gunshot_is_not_arrow_topic(actions, clock):
    """«Выстрел» — якорь только ружья: «выстрелил, не попал» не должно давать стрелу (задача 23)."""
    m = matcher(actions, clock)
    groups = {d.group for d in m.process("он выстрелил и не попал", 0, final=True)}
    assert "arrow" not in groups and "gun" in groups
    assert "arrow" in {d.group for d in m.process("лучник прицелился", 1, final=True)}


def test_live_log_anchors(actions, clock):
    """Живой тест 2026-11-17: «скрипка» давала стук в дверь; «уронил», «бросился в реку» — без звука."""
    m = matcher(actions, clock)
    groups = lambda text, i: {d.group for d in m.process(text, i, final=True)}
    g = groups("музыканты заиграли на скрипке", 0)
    assert "door" not in g and "music" in g
    assert "door" in groups("калитка тихо скрипнула", 1)
    assert "fall" in groups("все стулья уронил", 2)
    assert "fall" in groups("все столы перевернул", 3)
    assert "water" in groups("бросился в реку", 4)


def test_simile_is_not_action(actions, clock):
    """«Голос громкий, как гром» — сравнение, грома нет; «загремел гром» — гром."""
    m = matcher(actions, clock)
    assert not [d for d in m.process("голос у трактирщика был громкий как гром", 0, final=True) if d.sfx]
    clock.advance(10)
    assert "thunder" in [d.sfx for d in m.process("вдруг загремел гром", 1, final=True)]


def test_same_anchor_once_when_asr_rewrites_start(actions, clock):
    """Vosk переписал начало длинной фразы — позиции сдвинулись, но решётка звучит один раз (прогон 2026-11-22)."""
    m = matcher(actions, clock)
    fired = []
    for text in ["опустилась железная решётка и он",
                 "вдруг опустилась железная решётка и он",
                 "вдруг сверху опустилась железная решётка и он отпер"]:
        clock.advance(3)
        fired += [d.sfx for d in m.process(text, 0, final=False) if d.group == "trap" and d.sfx]
    clock.advance(3)
    fired += [d.sfx for d in m.process("вдруг сверху опустилась железная решётка и он отпер", 0, final=True)
              if d.group == "trap" and d.sfx]
    assert len(fired) <= 1, fired


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


def test_cast_net_anchor(actions, clock):
    """Vosk: «закинул невод» → «закинул не вот» — глагол «закинул» сам открывает тему воды (задача 23)."""
    m = matcher(actions, clock)
    assert "water" in {d.group for d in m.process("как то старик закинул не вот", 0, final=True)}
