from storyfx.triggers import TriggerMatcher


def run(matcher, text, utt=0, final=True):
    return [f.sfx for f in matcher.process(text, utt, final)]


def test_word_forms(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    for i, text in enumerate(["орк упал", "эльфийка упала", "все попадали и рухнули"]):
        clock.advance(5)
        assert "fall" in run(m, text, utt=i), text


def test_longer_phrase_wins(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    fired = run(m, "воин ударил мечом")
    assert "sword_clash" in fired and "punch" not in fired


def test_gap_words_allowed(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    assert "sword_clash" in run(m, "он ударил тяжёлым мечом")


def test_negation(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    assert run(m, "рыцарь не упал") == []
    assert run(m, "дракон так и не зарычал", utt=1) == []
    assert run(m, "стрел нет", utt=2) == []


def test_negation_does_not_leak(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    assert "sword_clash" in run(m, "он не испугался и ударил мечом")


def test_no_repeat_on_partials(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    fired = []
    for partial in ["орк", "орк упал", "орк упал на", "орк упал на землю"]:
        fired += run(m, partial, final=False)
        clock.advance(2)    # больше кулдауна — повтор отсекается именно по позиции
    fired += run(m, "орк упал на землю", final=True)
    assert fired.count("fall") == 1


def test_partial_waits_for_longer_phrase(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    assert "punch" not in run(m, "воин ударил", final=False)          # ждём: может быть «ударил мечом»
    assert "sword_clash" in run(m, "воин ударил мечом", final=False)


def test_partial_fires_when_not_extended(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    run(m, "воин ударил", final=False)
    run(m, "воин ударил орка", final=False)
    assert "punch" in run(m, "воин ударил орка дубиной", final=False)


def test_partial_revision(triggers, clock):
    """Vosk переписывает последнее слово: «ударил меня» → «ударил мечом»."""
    m = TriggerMatcher(triggers, clock=clock)
    fired = []
    for p in ["воин ударил меня", "воин ударил", "воин ударил мечом", "воин ударил мечом орка"]:
        fired += run(m, p, final=False)
    assert fired == ["sword_clash"]


def test_cooldown(triggers, clock):
    m = TriggerMatcher(triggers, clock=clock)
    assert "fall" in run(m, "упал", utt=0)
    clock.advance(0.5)
    assert "fall" not in run(m, "упал", utt=1)
    clock.advance(5)
    assert "fall" in run(m, "упал", utt=2)


def test_kids_mode_skips_scary(triggers, clock):
    m = TriggerMatcher(triggers, mode="kids", clock=clock)
    assert "roar" not in run(m, "дракон зарычал")
    assert "explosion" not in run(m, "раздался взрыв", utt=1)


def test_false_friends(triggers, clock):
    """Слова, похожие на триггеры, но означающие другое."""
    m = TriggerMatcher(triggers, clock=clock)
    assert "thunder" not in run(m, "он громко сказал")
    assert "footsteps" not in run(m, "пошёл дождь", utt=1)
    assert "wolf_howl" not in run(m, "во дворе было тихо", utt=2)
