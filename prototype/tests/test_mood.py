"""Настроение рассказа → фоновая музыка: угадывание по ключевым словам и вкл/выкл в движке."""
from conftest import feed_text, make_engine

from storyfx.cli import with_music_toggle
from storyfx.mood import make_mood_tracker


def tracker(mood_data):
    moods, default = mood_data
    return make_mood_tracker(moods, default)


def test_starts_calm(mood_data):
    assert tracker(mood_data).current == "calm"


def test_mood_by_keyword(mood_data):
    t = tracker(mood_data)
    t.add_utterance("вдруг стало очень страшно")
    assert t.current == "tense"
    t.add_utterance("за ними началась погоня")
    assert t.current == "action"
    t.add_utterance("все засмеялись и пустились в пляс")
    assert t.current == "cheerful"
    t.add_utterance("наступила тишина, и все спокойно уснули")
    assert t.current == "calm"


def test_negated_keyword_keeps_mood(mood_data):
    t = tracker(mood_data)
    t.add_utterance("им было совсем не страшно")
    assert t.current == "calm"


def test_live_log_keywords(mood_data):
    """Живой тест 2026-11-17: «ворвался разбойник», «тревожное», «помчался» — музыка не менялась."""
    t = tracker(mood_data)
    t.add_utterance("мужик повеселел и пустился в пляс")
    assert t.current == "cheerful"
    t.add_utterance("в таверну ворвался разбойник")
    assert t.current == "tense"
    t2 = tracker(mood_data)
    t2.add_utterance("настроение стало тревожное")
    assert t2.current == "tense"
    t2.add_utterance("выбежал из таверны и помчался к полю")
    assert t2.current == "action"


def test_herding_is_not_a_chase(mood_data):
    """«Гнал коров на луг» — не погоня: стемминг стирает «-ся», поэтому в action — «=гнался»
    точным словом (контрольная №4, 2026-11-25: «гнал коров» + «моросил дождь» включали боевик)."""
    t = tracker(mood_data)
    t.add_utterance("каждое утро он гнал коров на луг за рекой")
    t.add_utterance("однажды с самого утра моросил холодный дождь")
    assert t.current == "calm"
    t.add_utterance("вор выскочил из кустов и гнался за ним по пятам")   # контроль: настоящая погоня
    assert t.current == "action"


def test_graveyard_is_tense(mood_data):
    """Живой тест 2026-11-22: после пляса в таверне пошли на кладбище — играла весёлая музыка."""
    t = tracker(mood_data)
    t.add_utterance("скрипач заиграл и все пустились в пляс")
    assert t.current == "cheerful"
    t.add_utterance("ночью друзья пошли на старое кладбище")
    assert t.current == "tense"


def test_escalation_skips_dwell(mood_data):
    """После смены настроения музыка стоит MOOD_MIN_DWELL фраз — но не когда напряжение растёт."""
    t = tracker(mood_data)
    t.add_utterance("все засмеялись и пустились в пляс")
    assert t.current == "cheerful"
    want = {}
    t._score = lambda s, vec, tokens: want.get(s.id, 0.1)
    want.update(calm=0.9)                      # спокойнее — ждём выдержку
    for _ in range(4):
        t.add_utterance("слова одной длинной фразы рассказа о том что было дальше")
    assert t.current == "cheerful"
    want.clear(); want.update(tense=0.9)       # напряжённее — сразу (после подтверждений)
    for _ in range(3):
        t.add_utterance("слова одной длинной фразы рассказа о том что было дальше")
    assert t.current == "tense"


def engine_with_music(actions, scene_data, mood_data, clock, music_on=True):
    eng = make_engine(actions, scene_data, clock)
    eng.moods = tracker(mood_data)
    eng.set_music_enabled(music_on)
    return eng


def test_music_follows_mood(actions, scene_data, mood_data, clock):
    eng = engine_with_music(actions, scene_data, mood_data, clock)
    assert eng.audio.log[-1] == ("music", "calm")
    feed_text(eng, "Вдруг стало страшно.", clock)
    assert ("music", "tense") in eng.audio.log and ("mood", "tense") in eng.events


def test_music_off_and_on(actions, scene_data, mood_data, clock):
    eng = engine_with_music(actions, scene_data, mood_data, clock)
    eng.set_music_enabled(False)
    assert eng.audio.log[-1] == ("music", None)
    n = len([e for e in eng.audio.log if e[0] == "music"])
    feed_text(eng, "Все засмеялись и пустились в пляс.", clock)
    assert eng.mood == "cheerful"                                    # настроение следим и без музыки
    assert len([e for e in eng.audio.log if e[0] == "music"]) == n   # но музыка молчит
    eng.set_music_enabled(True)
    assert eng.audio.log[-1] == ("music", "cheerful")               # включили — сразу текущее


def test_engine_without_moods_has_no_music(actions, scene_data, clock):
    eng = make_engine(actions, scene_data, clock)
    eng.set_music_enabled(True)
    assert not eng.music_on and eng.audio.log[-1] == ("music", None)


def test_text_mode_toggle_command(actions, scene_data, mood_data, clock):
    eng = engine_with_music(actions, scene_data, mood_data, clock)
    out = list(with_music_toggle(["жили-были", "!музыка", "дед и баба", "!MUSIC"], eng))
    assert out == ["жили-были", "дед и баба"]
    assert eng.music_on and ("music", None) in eng.audio.log


# ---------- D-019 (задача 30): фильтр контекста — прошедшее событие не меняет музыку ----------
import numpy as np                                                      # noqa: E402

from storyfx import config                                              # noqa: E402
from storyfx.scenes import Scene, SceneTracker                          # noqa: E402
from storyfx.textnorm import parse_pattern                              # noqa: E402


class MoodVecEmbedder:
    """Фейковый смысл: вектор = мешок слов. Проверяет механику фильтра (фраза за/против + контекст);
    что rubert-tiny2 и правда различает «вчерашнюю битву» от «ворвался разбойник» — сквозные тесты.
    «мирн» — спокойное слово НЕ из ключевых: фраза про битву в спокойном изложении ближе к calm."""
    VOCAB = ["спокойн", "мирн", "страх", "битв", "ворвал"]

    def encode(self, texts):
        out = []
        for t in texts:
            v = np.array([t.lower().count(w) for w in self.VOCAB], dtype=float) + 0.01
            out.append(v / np.linalg.norm(v))
        return np.array(out)


def gated_tracker():
    """Трекер настроения с фильтром контекста (context_gate=True), как make_mood_tracker."""
    moods = [
        Scene("calm", "calm", ["спокойно и мирно"], [parse_pattern("спокойн*")]),
        Scene("tense", "tense", ["страх и ужас"],
              [parse_pattern("страх*"), parse_pattern("ворвал*"), parse_pattern("битв*")]),
    ]
    t = SceneTracker(moods, [], embedder=MoodVecEmbedder(), context_gate=True)
    t.current = "calm"
    return t


def test_mood_past_event_deferred_and_expires():
    """«…мирно мимо поля, где вчера шла битва» — слово «битва» есть, но фраза спокойная и контекст
    спокойный: музыку не дергаем. За CONTEXT_PENDING_PHRASES подтверждения нет — забыли (D-019)."""
    t = gated_tracker()
    t.add_utterance("было спокойно и мирно")
    t.add_utterance("спокойно шли дальше")
    t.add_utterance("мирно мимо поля где вчера шла битва")     # слово есть, поворота нет
    assert t.current == "calm"
    for _ in range(config.CONTEXT_PENDING_PHRASES + 1):
        t.add_utterance("спокойно и мирно шли дальше")
    assert t.current == "calm"
    t.add_utterance("снова мирно мимо поля битвы")             # новое упоминание — снова только отложено
    assert t.current == "calm"


def test_mood_turn_confirmed_by_repeat():
    """Отложенное настроение, которое назвали снова, — настоящий поворот: переключаемся."""
    t = gated_tracker()
    t.add_utterance("было спокойно и мирно")
    t.add_utterance("спокойно шли дальше")
    t.add_utterance("мирно мимо поля где вчера шла битва")     # отложено
    assert t.current == "calm"
    changes = t.add_utterance("и вдруг ворвался страх")        # повтор темы — подтверждение
    assert t.current == "tense"
    assert changes and "подтверждено" in changes[0].reason


def test_mood_switch_now_when_phrase_prefers():
    """Сама фраза — про новое настроение («ворвался разбойник»): контекст ещё спокойный,
    но переключаемся сразу — музыка не должна отставать (живой тест 2026-11-17)."""
    t = gated_tracker()
    t.add_utterance("было спокойно и мирно")
    t.add_utterance("спокойно шли дальше")
    t.add_utterance("вдруг страх ворвался в лагерь")           # фраза сама тревожная
    assert t.current == "tense"
