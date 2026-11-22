"""Сквозные проверки с настоящими моделями. Запуск: pytest -m slow"""
import time
from pathlib import Path

import pytest

from conftest import TESTS, check_expectations, feed_text, make_engine
from storyfx import config

pytestmark = pytest.mark.slow
WAV_DIR = TESTS / "wav"




def test_scenarios_text_with_embedder(actions, scene_data, scenarios, clock, embedder):
    errors = []
    for name, sc in scenarios.items():
        eng = make_engine(actions, scene_data, clock, embedder)
        feed_text(eng, sc["text"], clock)
        errors += check_expectations(name, sc, eng.events)
    assert not errors, "\n".join(errors)


# Фразы, которых нет в примерах data/actions.yaml: (текст, тема, ожидаемый звук или None)
MEANING_CASES = [
    ("гонец на вороном коне промчался через площадь", "horse", "horse_gallop"),
    ("всадники пронеслись мимо деревни", "horse", "horse_gallop"),
    ("мальчик протянул коню кусочек сахара", "horse", "horse_snort"),
    ("старая кобыла устало фыркнула", "horse", "horse_snort"),
    ("в конюшне у барона было десять лошадей", "horse", None),
    ("гном с размаху рубанул секирой по вражескому щиту", "fight", "sword_clash"),
    ("наёмник неторопливо вытащил из ножен длинный меч", "fight", "sword_swing"),
    ("трактирщик со всей силы двинул пьяницу кулаком", "fight", "punch"),
    ("меч деда хранился в сундуке", "fight", None),
    ("кто-то тихо постучался в окно", "door", "door_knock"),
    ("дверь подвала со скрипом приоткрылась", "door", "door_creak"),
    ("жрец положил руки на рану и исцелил воина", "magic", "heal"),
    ("волшебница взмахнула посохом и заморозила озеро", "magic", "ice"),
    ("в полночь завыл одинокий волк", "beast", "wolf_howl"),
    ("огромный медведь угрожающе зарычал", "beast", "roar"),
    ("утром в саду запели птицы", "birds", "bird"),
    ("стражник медленно прошёл по коридору", "steps", "footsteps"),
    ("прошло много лет", "steps", None),
    ("мальчишка с разбегу прыгнул в озеро", "water", "splash"),
    ("лучник натянул тетиву и выстрелил", "arrow", "arrow"),
    ("егерь вскинул ружьё и выстрелил по кабану", "gun", "gunshot"),
    ("ружьё пылилось за печкой", "gun", None),
    ("рыбак размахнулся и закинул невод в озеро", "water", "splash"),
    ("лошадка весело везла сани по сугробам", "sleigh", "sleigh_bells"),
    ("ночью лёд на озере трещал от мороза", "frost", "frost_crackle"),
    # --- ДнД (задача 24) ---
    ("варвар с размаху опустил боевой молот на шлем скелета", "fight", "heavy_hit"),
    ("убийца бесшумно воткнул нож стражнику под рёбра", "fight", "stab"),
    ("волшебник поднял руку, и вокруг друзей вспыхнул защитный купол", "magic", "magic_shield"),
    ("тёмный жрец призвал из земли толпу мертвецов", "magic", "summon"),
    ("чародейка шагнула в сияющий портал и пропала", "magic", "teleport"),
    ("гном одним махом осушил кружку", "drink", "drink"),
    ("в этой таверне подавали отличный эль", "drink", None),
    ("воровка ловко вскрыла замок тонкой отмычкой", "lock", "lock_click"),
    ("герои увидели вдали величественный замок", "lock", None),
    ("едва паладин наступил на плиту, щёлкнула ловушка", "trap", "trap_click"),
    ("варвар рывком открыл сундук", "chest", "chest_open"),
    ("орки с диким воплем кинулись на отряд", "shout", "war_cry"),
    ("своды пещеры затряслись и обрушились", "collapse", "rockfall"),
    ("в темнице загремели цепи", "chains", "chains"),
    ("жрица чиркнула огнивом и зажгла факел", "torch", "torch_light"),
    # живой тест 2026-11-17 (новые формулировки, не из примеров)
    ("скрипач в углу заиграл плясовую", "music", "fiddle"),
    ("бродячий бард взял лютню и заиграл", "music", "lute"),
    ("в драке он уронил тяжёлую скамью", "fall", "fall"),
    ("мужик бросился в холодную реку", "water", "splash"),
    ("разбойник бежал следом и махал топором", "fight", "sword_swing"),
    ("разбойник стреляет в него из лука", "arrow", "arrow"),
    ("старик медленно ведёт свою лошадку по дороге", "horse", "horse_snort"),
    # живой тест 2026-11-22
    ("дед запряг коня и отправился в город", "horse", "horse_gallop"),
    ("над пристанью с криком кружили чайки", "birds", "gull"),
    ("услышав шутку, все дружно засмеялись", "laugh", "laugh"),
]


def test_event_split_by_pause(actions, clock, embedder):
    """Живой тест 2026-11-22 (задача 27): пауза резала событие на фразы, и звук терялся.
    «старый сундук | открыли и» — хвост с якорем переходит в следующую фразу;
    «…лежал свиток эльфы | развернул его» — «без звука» не решаем раньше конца фразы."""
    from storyfx.actions import ActionMatcher
    m = ActionMatcher(list(actions), embedder=embedder, clock=clock)
    fired = []
    for i, text in enumerate(["в склепе друзья нашли", "старый сундук", "открыли и"]):
        clock.advance(1.5)
        fired += [d.sfx for d in m.process(text, i, final=True) if d.sfx]
    assert "chest_open" in fired
    fired = []
    for text, final in [("в сундуке лежал свиток", False), ("в сундуке лежал свиток эльфы", False),
                        ("в сундуке лежал свиток эльфы развернул", False),
                        ("в сундуке лежал свиток эльфы развернул его", True)]:
        clock.advance(0.7)                              # срок «без звука» давно прошёл
        fired += [d.sfx for d in m.process(text, 10, final=final) if d.sfx]
    assert "paper" in fired
    # перенос — один раз и только скоро: через 10 с «открыли» — уже не про сундук
    clock.advance(10)
    m.process("старый сундук", 20, final=True)
    clock.advance(10)
    assert not [d for d in m.process("открыли окно", 21, final=True) if d.group == "chest"]


def test_actions_by_meaning(actions, clock, embedder):
    """Главная проверка задачи «по смыслу, а не по слову». Порог — 85% верных."""
    from storyfx.actions import ActionMatcher
    m = ActionMatcher(list(actions), embedder=embedder, clock=clock)
    misses = []
    for i, (text, group, want) in enumerate(MEANING_CASES):
        clock.advance(10)
        ds = [d for d in m.process(text, i, final=True) if d.group == group]
        got_all = [d.sfx for d in ds if d.sfx]            # в одной фразе может быть 2 события темы
        got = (want if want in got_all else (got_all[0] if got_all else None)) if ds else "нет решения"
        if got != want:
            misses.append(f"{text!r}: {got} вместо {want} ({ds[0].note if ds else ''} {ds[0].confidence if ds else 0:.2f})")
    acc = 1 - len(misses) / len(MEANING_CASES)
    print(f"точность по смыслу: {acc:.0%}")
    assert acc >= 0.85, "\n".join([f"точность {acc:.0%}"] + misses)


@pytest.mark.parametrize("text,expected", [
    ("путники долго пробирались сквозь бурелом, над головой шумели сосны и пели птицы", "forest"),
    ("корабль качало на волнах, солёные брызги летели на палубу", "sea"),
    ("с потолка капала вода, и каждый шаг отдавался гулким эхом в сыром туннеле", "cave"),
    ("за столами пили эль и громко смеялись, трактирщик протирал кружки", "tavern"),
    # сказочные сцены (docs/fairytales.md) — фразы без ключевых слов сцены
    ("старушка сидела у тёплой лежанки, тикали ходики, а кот мурлыкал на лавке", "home"),
    ("с утра закукарекал петух, закудахтали куры и замычала бурёнка", "village"),
    ("лягушки громко квакали, под ногами хлюпала вязкая жижа и пахло гнилью", "swamp"),
])
def test_embedder_guesses_scene(scene_data, embedder, text, expected):
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays), embedder=embedder)
    t._words = text.split()
    t.evaluate()
    best = max(t.last_scores, key=t.last_scores.get)
    assert best == expected, f"{best} вместо {expected}: {sorted(t.last_scores.items(), key=lambda kv: -kv[1])[:3]}"


FAIRYTALE_SCENE_CASES = {   # фразы не взяты из описаний сцен; порог низкий — модель смысла маленькая
    "village": ["бабка вышла кормить кур, а у плетня залаял пёс", "мужик запряг лошадь в телегу и поехал по селу",
                "у колодца собрались бабы с вёдрами, гуси щипали траву", "дед пошёл в хлев доить корову",
                "поросёнок вырвался из загона и побежал по огороду"],
    "home": ["дед с бабкой сидели на лавке у окна и пили чай", "мышка пробежала по полу и юркнула под лавку",
             "козлята заперли дверь и сидели тихо", "бабушка вязала носки у тёплой лежанки"],
    "swamp": ["царевич брёл по кочкам, под ногами чавкала вода", "цапля стояла на одной ноге среди осоки",
              "лягушка сидела на листе кувшинки"],
}


def test_fairytale_scene_accuracy(scene_data, embedder):
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    misses, n = [], 0
    for want, phrases in FAIRYTALE_SCENE_CASES.items():
        for p in phrases:
            t = SceneTracker(list(scenes), list(overlays), embedder=embedder)
            t._words = p.split()
            t.evaluate()
            best = max(t.last_scores, key=t.last_scores.get)
            n += 1
            if best != want:
                misses.append(f"{p!r}: {best} вместо {want}")
    acc = 1 - len(misses) / n
    print(f"сказочные сцены: {acc:.0%}")
    assert acc >= 0.75, "\n".join([f"точность {acc:.0%}"] + misses)


def test_scene_accuracy_on_stories(embedder):
    """Задача 25: доля фраз размеченных сказок (tests/scene_labels.yaml), где играет фон того места, где герой.
    Текстом: 72% по ключевым словам и смыслу окна → 86% с классификатором сцены по фразе (2026-11-22);
    контрольная сказка holdout_kuznets (размечена до прогона): 62% → 76%."""
    import sys
    sys.path.insert(0, str(TESTS.parent / "tools"))
    import scene_eval
    import story_run
    res = scene_eval.evaluate(engine=lambda c, log: story_run.build(c, log, embedder=embedder))
    acc = scene_eval.summary(res)
    print(f"сцены на сказках: {acc:.0%}")
    assert acc >= 0.84, {k: f"{v[0]}/{v[1]}" for k, v in res.items()}


MOOD_CASES = {   # фразы не из описаний moods.yaml; почти без ключевых слов настроения
    "calm": ["солнце садилось, старик сидел на завалинке и смотрел на закат", "кот дремал на печке, бабушка вязала",
             "путники брели по тропинке, никуда не торопясь", "река медленно несла свои воды"],
    "cheerful": ["зайчата кувыркались на траве и хохотали", "гости пели песни и хлопали в ладоши",
                 "колобок катился и весело распевал свою песенку", "дети водили хоровод вокруг ёлки"],
    "tense": ["в чаще завыл волк, и у Маши задрожали коленки", "дверь медленно со скрипом отворилась, а за ней никого",
              "из темноты на них смотрели два горящих глаза", "что-то зашуршало в кустах, и все замерли"],
    "action": ["богатырь вскочил на коня и поскакал наперерез врагу", "волк бросился вдогонку, а заяц петлял между деревьями",
               "меч сверкнул, и чудище рухнуло", "Иван схватил перо жар-птицы и кинулся бежать"],
}


def test_mood_accuracy(mood_data, embedder):
    from storyfx.mood import make_mood_tracker
    moods, default = mood_data
    misses, n = [], 0
    for want, phrases in MOOD_CASES.items():
        for p in phrases:
            t = make_mood_tracker(moods, default, embedder=embedder)
            t._words = p.split()
            t.evaluate()
            best = max(t.last_scores, key=t.last_scores.get)
            n += 1
            if best != want:
                misses.append(f"{p!r}: {best} вместо {want}")
    acc = 1 - len(misses) / n
    print(f"настроение: {acc:.0%}")
    assert acc >= 0.75, "\n".join([f"точность {acc:.0%}"] + misses)


def test_scene_eval_is_fast(scene_data, embedder):
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays), embedder=embedder)
    t._words = ("герои шли по лесу " * 10).split()
    t0 = time.perf_counter()
    for _ in range(5):
        t.evaluate()
    per_call = (time.perf_counter() - t0) / 5
    assert per_call < 0.2, f"оценка сцены {per_call * 1000:.0f} мс — слишком медленно"


def test_place_does_not_revert(actions, scene_data, clock, embedder):
    """D-011: ушли из деревни в лес — слова о деревне больше не тянут сцену назад (раньше откатывалось)."""
    eng = make_engine(actions, scene_data, clock, embedder)
    feed_text(eng, "Жили-были дед да баба в деревне. Испекла баба колобок и положила на окошко. "
                   "Покатился колобок в лес. А медведя в лесу не было. Колобок катился дальше по тропинке.", clock)
    scenes = [i for k, i in eng.events if k == "scene"]
    assert scenes[:2] == ["village", "forest"] and eng.world.place == "forest", scenes
    # короткие фразы (найдено в браузере): «…в деревне. Покатился колобок в лес. …дождь» — не назад в деревню
    eng = make_engine(actions, scene_data, clock, embedder)
    feed_text(eng, "Жили-были дед да баба в деревне. Покатился колобок в лес. Навстречу вышел заяц. "
                   "Вдруг начался сильный дождь.", clock)
    scenes = [i for k, i in eng.events if k == "scene"]
    assert scenes == ["village", "forest"] and ("overlay_on", "rain") in eng.events, scenes


def test_action_latency(actions, scene_data, scenarios, clock, embedder):
    """D-011: звук действия — не позже 1 с от конца слова-якоря (по времени в записи, Vosk включён)."""
    import wave

    from storyfx.asr import VoskStream
    from storyfx.audio import NullAudio
    from storyfx.textnorm import find_matches, tokenize

    class TimedAudio(NullAudio):
        def play_sfx(self, sfx):
            super().play_sfx(sfx)
            self.played.append((sfx, clock()))

    topics = {v.id: g.topic for g in actions for v in g.variants}
    worst, report = 0.0, []
    for name in scenarios:
        eng = make_engine(actions, scene_data, clock, embedder)       # без персонажей: меряем только действия
        eng.audio = TimedAudio()
        eng.audio.played = []
        t_start, words = clock(), []
        stream = VoskStream(word_times=True)
        with wave.open(str(WAV_DIR / f"{name}.wav"), "rb") as w:
            block = int(config.SAMPLE_RATE * config.BLOCK_SECONDS)
            while data := w.readframes(block):
                clock.advance(len(data) / 2 / config.SAMPLE_RATE)    # время в записи
                for ev in stream.feed(data):
                    eng.on_text(ev)
                    if ev.final:
                        words += stream.last_words
            for ev in stream.flush():
                eng.on_text(ev)
                words += stream.last_words
        toks = tokenize(" ".join(wd["word"] for wd in words))
        for sfx, t_play in eng.audio.played:
            ends = [words[m.end]["end"] for p in topics.get(sfx, []) for m in find_matches(p, toks)
                    if words[m.end]["end"] <= t_play - t_start + 0.05]
            if not ends:
                continue
            lat = (t_play - t_start) - max(ends)
            worst = max(worst, lat)
            report.append(f"{name}: {sfx} {lat:.2f} с")
    print("\n".join(["задержка действий:"] + report + [f"худшая: {worst:.2f} с"]))
    assert report, "ни одного звука действия — проверьте сценарии"
    assert worst <= 1.0, "\n".join(report)


def test_wav_through_vosk(actions, scene_data, scenarios, clock, embedder):
    from storyfx.asr import wav_events
    if not config.VOSK_MODEL_DIR.exists():
        pytest.fail("нет модели Vosk — запустите init.ps1")
    missing = [n for n in scenarios if not (WAV_DIR / f"{n}.wav").exists()]
    if missing:
        pytest.fail(f"нет тестовых WAV {missing} — запустите tools/make_test_wavs.py")
    errors, transcripts = [], []
    for name, sc in scenarios.items():
        eng = make_engine(actions, scene_data, clock, embedder)
        finals = []
        for ev in wav_events(WAV_DIR / f"{name}.wav", realtime=False):
            clock.advance(0.1)
            eng.on_text(ev)
            if ev.final:
                finals.append(ev.text)
        transcripts.append(f"{name}: {' | '.join(finals)}")
        errors += check_expectations(name, sc, eng.events)
    assert not errors, "\n".join(errors + ["", "Распознано:"] + transcripts)


def test_scene_by_phrase(scene_data, embedder):
    """Задача 25: сцена по смыслу одной фразы — без ключевого слова; место «вдали» классификатор не переспорит."""
    from storyfx.scenes import SceneTracker, load_scene_examples
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays), embedder=embedder, examples=load_scene_examples())
    t.add_utterance("пошёл мельник к синему морю")
    assert t.current == "sea"
    t.add_utterance("воротился мельник к жене")
    assert t.current == "home"
    t.add_utterance("вдалеке пропали они за тёмным лесом")
    assert t.current == "home"
