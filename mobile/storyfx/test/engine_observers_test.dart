/// Поведение наблюдателей движка — порт ключевых pytest из prototype/tests/
/// (test_actions.py, test_scenes.py, test_characters.py, test_engine.py).
/// Данные — те же YAML, что у Python-прототипа.
library;

import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:storyfx/engine/actions.dart';
import 'package:storyfx/engine/characters.dart';
import 'package:storyfx/engine/config.dart';
import 'package:storyfx/engine/engine.dart';
import 'package:storyfx/engine/scenes.dart';
import 'package:storyfx/engine/textnorm.dart';
import 'package:storyfx/engine/world.dart';

// ---------- общие приспособления ----------

class FakeClock {
  double t = 1000.0;
  double call() => t;
  void advance(double dt) => t += dt;
}

String readData(String name) =>
    File('../../prototype/data/$name').readAsStringSync();

/// Фейковая модель смысла: вектор = мешок опорных слов (как KeywordishEmbedder в pytest).
class KeywordishEmbedder implements Embedder {
  static const vocab = [
    'лес', 'дерев', 'птиц', 'мор', 'волн', 'корабл', 'таверн', 'эль', 'пещер', 'темн'
  ];

  @override
  List<List<double>> encode(List<String> texts) => [for (final t in texts) _vec(t)];

  List<double> _vec(String text) {
    final low = text.toLowerCase();
    final v = [for (final w in vocab) _count(low, w) + 0.01];
    final norm = sqrt(v.fold<double>(0, (s, x) => s + x * x));
    return [for (final x in v) x / norm];
  }

  int _count(String text, String sub) {
    var n = 0, i = 0;
    while ((i = text.indexOf(sub, i)) >= 0) {
      n++;
      i += sub.length;
    }
    return n;
  }
}

late List<ActionGroup> actions;
late SceneData sceneData;
late CharactersData charData;

ActionMatcher matcher(FakeClock clock) =>
    ActionMatcher(List.of(actions), clock: clock.call);

List<String?> sounds(List<Decision> ds) =>
    [for (final d in ds) if (d.sfx != null) d.sfx];

SceneTracker tracker({Embedder? embedder}) =>
    SceneTracker(List.of(sceneData.scenes), List.of(sceneData.overlays),
        embedder: embedder, data: sceneData);

List<(String, String?)> kinds(List<Change> changes) =>
    [for (final c in changes) (c.kind, c.id)];

CharacterTracker charTracker() =>
    CharacterTracker(List.of(charData.characters), charData,
        WorldState(clock: FakeClock().call));

List<String> ids(CharacterTracker t, String text) =>
    [for (final a in t.process(text)) a.character.id];

void main() {
  setUpAll(() {
    actions = loadActions(readData('actions.yaml'));
    sceneData = loadScenes(readData('scenes.yaml'));
    charData = loadCharacters(readData('characters.yaml'));
  });

  // ---------- действия ----------

  group('действия', () {
    test('разрез фразы на части по союзам', () {
      final toks = tokenize('воин выхватил меч и ударил орка а потом убежал');
      final parts = [
        for (final (s, e, _) in splitClauses(toks))
          toks.sublist(s, e + 1).map((t) => t.word).join(' ')
      ];
      expect(parts, ['воин выхватил меч', 'ударил орка', 'убежал']);
    });

    test('частичный текст ждёт контекст, финал решает сразу', () {
      final clock = FakeClock();
      final m = matcher(clock);
      expect(m.process('орк упал', 0, false), isEmpty); // мало слов после якоря — ждём
      expect(sounds(m.process('орк упал на землю с грохотом', 0, false)),
          contains('fall'));
      final m2 = matcher(clock);
      expect(sounds(m2.process('орк упал', 1, true)), contains('fall'));
    });

    test('внутри одной фразы событие звучит один раз', () {
      final clock = FakeClock();
      final m = matcher(clock);
      final fired = <String?>[];
      for (final p in [
        'орк упал на землю с',
        'орк упал на землю с грохотом',
        'орк упал на землю с грохотом прямо'
      ]) {
        fired.addAll(sounds(m.process(p, 0, false)));
        clock.advance(5);
      }
      fired.addAll(
          sounds(m.process('орк упал на землю с грохотом прямо', 0, true)));
      expect(fired, ['fall']);
    });

    test('два события одной темы во фразе', () {
      final m = matcher(FakeClock());
      final ds = m
          .process('воин выхватил меч и ударил мечом по щиту', 0, true)
          .where((d) => d.group == 'fight')
          .toList();
      expect(ds.length, 2);
    });

    test('повтор якоря — то же событие: «дождь шёл и шёл» ≠ шаги', () {
      final m = matcher(FakeClock());
      final ds = m.process(
          'дождь всё шёл и шёл, и собака тряхнула мокрой шерстью', 0, true);
      expect(sounds(ds), isNot(contains('footsteps')));
      // контроль: настоящая ходьба звучит
      final m2 = matcher(FakeClock());
      expect(sounds(m2.process('они шли и шли по каменным плитам', 0, true)),
          contains('footsteps'));
    });

    test('«слушали, как…» — не сравнение, но и не мороз', () {
      final m = matcher(FakeClock());
      final ds = m.process('слушали, как трещат дрова в печи', 0, true);
      expect(sounds(ds), isNot(contains('frost_crackle')));
      expect(ds.any((d) => d.note == 'сравнение'), isFalse);
      final m2 = matcher(FakeClock());
      expect(sounds(m2.process('мороз пуще затрещал', 0, true)),
          contains('frost_crackle'));
    });

    test('контекст переживает союз', () {
      final m = matcher(FakeClock());
      final ds = m
          .process('девочка подошла к лошадке и ласково погладила', 0, true)
          .where((d) => d.group == 'horse')
          .toList();
      expect(ds, isNotEmpty);
      expect(ds.first.context, contains('погладила'));
    });

    test('отрицание действует в своей части фразы', () {
      final clock = FakeClock();
      final m = matcher(clock);
      expect(sounds(m.process('рыцарь не упал', 0, true)), isEmpty);
      clock.advance(5);
      expect(sounds(m.process('орк упал на землю и больше не встал', 1, true)),
          contains('fall'));
      expect(sounds(m.process('дракон так и не зарычал', 2, true)), isEmpty);
      clock.advance(5);
      expect(sounds(m.process('орк упал и не встал', 3, true)),
          contains('fall'));
    });

    test('кулдаун', () {
      final clock = FakeClock();
      final m = matcher(clock);
      expect(sounds(m.process('орк упал на землю', 0, true)), contains('fall'));
      clock.advance(0.5);
      expect(sounds(m.process('орк упал на землю', 1, true)),
          isNot(contains('fall')));
      clock.advance(5);
      expect(sounds(m.process('орк упал на землю', 2, true)), contains('fall'));
    });

    test('ложные друзья молчат', () {
      final m = matcher(FakeClock());
      final texts = [
        'он громко сказал',
        'совсем стемнело',
        'огромный зал',
        'во дворе было тихо'
      ];
      for (var i = 0; i < texts.length; i++) {
        expect(sounds(m.process(texts[i], i, true)), isEmpty,
            reason: texts[i]);
      }
    });

    test('выстрел — не тема стрелы', () {
      final m = matcher(FakeClock());
      final groups =
          m.process('он выстрелил и не попал', 0, true).map((d) => d.group);
      expect(groups, isNot(contains('arrow')));
      expect(groups, contains('gun'));
      expect(
          m.process('лучник прицелился', 1, true).map((d) => d.group),
          contains('arrow'));
    });

    test('якоря из живого журнала', () {
      final m = matcher(FakeClock());
      Set<String> groups(String text, int i) =>
          m.process(text, i, true).map((d) => d.group).toSet();
      final g = groups('музыканты заиграли на скрипке', 0);
      expect(g, isNot(contains('door')));
      expect(g, contains('music'));
      expect(groups('калитка тихо скрипнула', 1), contains('door'));
      expect(groups('все стулья уронил', 2), contains('fall'));
      expect(groups('все столы перевернул', 3), contains('fall'));
      expect(groups('бросился в реку', 4), contains('water'));
    });

    test('сравнение — не действие', () {
      final clock = FakeClock();
      final m = matcher(clock);
      expect(
          sounds(m.process('голос у трактирщика был громкий как гром', 0, true)),
          isEmpty);
      clock.advance(10);
      expect(sounds(m.process('вдруг загремел гром', 1, true)),
          contains('thunder'));
    });

    test('переписанное начало фразы — решётка звучит один раз', () {
      final clock = FakeClock();
      final m = matcher(clock);
      final fired = <String?>[];
      for (final text in [
        'опустилась железная решётка и он',
        'вдруг опустилась железная решётка и он',
        'вдруг сверху опустилась железная решётка и он отпер'
      ]) {
        clock.advance(3);
        fired.addAll(sounds(m
            .process(text, 0, false)
            .where((d) => d.group == 'trap')
            .toList()));
      }
      clock.advance(3);
      fired.addAll(sounds(m
          .process('вдруг сверху опустилась железная решётка и он отпер', 0, true)
          .where((d) => d.group == 'trap')
          .toList()));
      expect(fired.length, lessThanOrEqualTo(1), reason: '$fired');
    });
  });

  // ---------- сцены и погода ----------

  group('сцены', () {
    test('точное ключевое слово переключает сразу', () {
      final t = tracker();
      expect(kinds(t.addUtterance('отряд вошёл в густой лес')),
          contains(('scene', 'forest')));
      expect(kinds(t.addUtterance('герои зашли в таверну')),
          contains(('scene', 'tavern')));
      expect(t.current, 'tavern');
    });

    test('сказочные сцены по ключевым словам', () {
      final t = tracker();
      expect(kinds(t.addUtterance('жили-были дед да баба в деревне')),
          contains(('scene', 'village')));
      expect(kinds(t.addUtterance('бабушка испекла пирожки в печи')),
          contains(('scene', 'home')));
      expect(kinds(t.addUtterance('стрела упала прямо в болото')),
          contains(('scene', 'swamp')));
      expect(kinds(t.addUtterance('Иван пришёл во дворец')),
          contains(('scene', 'castle'))); // «дворец» — не «двор»
    });

    test('смена по смыслу требует подтверждения', () {
      final t = tracker(embedder: KeywordishEmbedder());
      t.addUtterance('отряд вошёл в густой лес');
      t.debugSetWindow('кругом шумели волны и качался корабль волны волны'.split(' '));
      t.debugSetSinceSwitch(sceneMinDwell); // выдержка после смены прошла
      final tries = [for (var i = 0; i < sceneConfirm; i++) t.evaluate()];
      expect(tries.sublist(0, tries.length - 1).every((c) => c == null), isTrue);
      expect(tries.last, isNotNull);
      expect(tries.last!.id, 'sea');
    });

    test('смена по смыслу игнорирует короткий текст', () {
      final t = tracker(embedder: KeywordishEmbedder());
      t.debugSetWindow(['волны', 'корабль']);
      for (var i = 0; i < 5; i++) {
        expect(t.evaluate(), isNull);
      }
    });

    test('после смены сцену по смыслу некоторое время не трогаем', () {
      final t = tracker(embedder: KeywordishEmbedder());
      t.addUtterance('отряд вошёл в густой лес'); // ключевое слово — сразу
      t.debugSetWindow('кругом шумели волны и качался корабль волны волны'.split(' '));
      for (var i = 0; i < 5; i++) {
        expect(t.evaluate(), isNull); // фраз после смены ещё нет
      }
      for (var i = 0; i < sceneMinDwell; i++) {
        t.debugAdvanceSwitch(1);
      }
      final tries = [for (var i = 0; i < sceneConfirm; i++) t.evaluate()];
      expect(tries.any((c) => c != null), isTrue);
    });

    test('сло́й включается и выключается', () {
      final t = tracker();
      expect(kinds(t.addUtterance('начался сильный дождь')),
          contains(('overlay_on', 'rain')));
      expect(t.activeOverlays, contains('rain'));
      expect(kinds(t.addUtterance('наконец дождь закончился')),
          contains(('overlay_off', 'rain')));
      expect(t.activeOverlays, isNot(contains('rain')));
    });

    test('сравнение — не погода и не место', () {
      final t = tracker();
      t.addUtterance('тут старуха как гроза разразилась');
      expect(t.activeOverlays, isNot(contains('storm')));
      t.addUtterance('глаза у неё как море');
      expect(t.current, isNot('sea'));
      t.addUtterance('разразилась гроза');
      expect(t.activeOverlays, contains('storm'));
    });

    test('отрицанная погода не включается', () {
      final t = tracker();
      t.addUtterance('дождя не было, ни ветерка');
      expect(t.activeOverlays, isEmpty);
      t.addUtterance('снега нет');
      expect(t.activeOverlays, isEmpty);
    });

    test('не больше двух слоёв, новый важнее старого', () {
      final t = tracker();
      t.addUtterance('пошёл дождь');
      t.addUtterance('подул сильный ветер');
      t.addUtterance('наступила ночь');
      expect(t.activeOverlays.length, 2);
      expect(t.activeOverlays, isNot(contains('rain')));
    });

    test('битва и гроза доступны всегда', () {
      final t = tracker();
      t.addUtterance('началась битва');
      expect(t.current, 'battle');
      t.addUtterance('разразилась гроза');
      expect(t.activeOverlays, contains('storm'));
    });
  });

  // ---------- персонажи ----------

  group('персонажи', () {
    test('имена и ложные совпадения', () {
      final cases = <String, List<String>>{
        'жили-были дед да баба': ['old_man', 'old_woman'],
        'вдруг выскочил серый волк': ['wolf'],
        'пришёл Дед Мороз': ['frost'], // длинное имя важнее «деда»
        'прилетела Баба-яга в ступе': ['witch'], // не бабушка
        'Соловей-разбойник засвистел': ['nightingale'], // не разбойник
        'Иван поймал жар-птицу': ['magic'], // не просто птица
        'Змей Горыныч прилетел': ['dragon'],
        'у пса была будка': ['dog'],
        'ёжик шёл в тумане': ['hedgehog'],
        'Машенька заблудилась': ['child'],
        'козлята заперли дверь': ['goat'],
        'бабка-ёжка костяная ножка': ['witch'],
        // ложные совпадения
        'дед курил трубку': ['old_man'], // «курил» — не курица
        'густой лес шумел': [], // не гуси
        'совсем стемнело': [], // не сова
        'путник ослабел': [], // не осёл
        'это был конец пути': [], // не конь
        'бабушка собирала ягоды': ['old_woman'], // «ягоды» — не Яга
        'конь вороной': ['horse'], // масть, не ворона
        'пришла змея': [], // «змея» — не Змей Горыныч
        'и говорит бармен': ['innkeeper'],
        'вдруг ворвался злой колдун': ['villain'],
        'музыканты на сцене': ['bard'],
      };
      for (final e in cases.entries) {
        expect(ids(charTracker(), e.key), e.value, reason: e.key);
      }
    });

    test('отрицание — не появление', () {
      expect(ids(charTracker(), 'медведя в лесу не было'), isEmpty);
      expect(ids(charTracker(), 'волка нигде нет'), isEmpty);
      expect(ids(charTracker(), 'лиса в норе не спала'), ['fox']); // «не» у другого слова
      expect(ids(charTracker(), 'тут пришёл медведь'), ['bear']);
    });

    test('присутствие — по фразам: после 30 фраз молчания появляется заново', () {
      final t = charTracker();
      expect(ids(t, 'пришёл медведь'), ['bear']);
      expect(ids(t, 'медведь рассердился'), isEmpty); // уже здесь
      for (var i = 0; i < characterReintroPhrases - 2; i++) {
        ids(t, 'шёл дождь');
      }
      expect(ids(t, 'медведь зарычал'), isEmpty); // 28 фраз — всё ещё здесь
      for (var i = 0; i < characterReintroPhrases; i++) {
        ids(t, 'шёл дождь');
      }
      expect(ids(t, 'и снова явился медведь'), ['bear']); // появился заново
    });

    test('сравнение — не появление', () {
      expect(ids(charTracker(), 'силён он был, как медведь'), isEmpty);
      expect(ids(charTracker(), 'старуха визжала, словно лиса'), ['old_woman']);
    });

    test('пересказ — не появление', () {
      expect(
          ids(charTracker(), 'егор рассказывал, как испугался при встрече с волком'),
          isEmpty);
      expect(ids(charTracker(), 'дед поведал, что в чаще живёт медведь'),
          ['old_man']); // дед здесь, медведь — в пересказе
      expect(ids(charTracker(), 'тут из чащи вышел волк'), ['wolf']); // контроль
    });

    test('«смотрел, как…» — придаточное, не сравнение', () {
      expect(ids(charTracker(), 'стоял и смотрел, как медведь пил воду из реки'),
          ['bear']);
      expect(ids(charTracker(), 'силён он был, как медведь'), isEmpty);
    });

    test('обращение — не появление', () {
      expect(ids(charTracker(), 'что ты наделал, старый пёс'), isEmpty);
      final t = charTracker();
      expect(ids(t, 'во двор вбежал пёс'), ['dog']);
      expect(ids(t, 'ну что ты лаешь, пёс'), isEmpty); // пёс здесь — к нему обращаются
    });

    test('не больше двух персонажей за фразу', () {
      expect(ids(charTracker(), 'пришли волк лиса заяц и медведь'),
          ['wolf', 'fox']);
    });

    test('злодеи звучат всегда', () {
      expect(ids(charTracker(), 'прилетел Змей Горыныч'), ['dragon']);
      expect(ids(charTracker(), 'злой Кощей Бессмертный'), ['villain']);
    });
  });

  // ---------- движок целиком ----------

  group('движок', () {
    late FakeClock clock;
    late FakeAudio audio;
    late FakeEvents events;
    late StoryEngine engine;

    void feed(String text, {double step = 0.3}) {
      for (final sent
          in text.split(RegExp(r'[.!?]+')).where((s) => s.trim().isNotEmpty)) {
        final words = sent.trim().split(RegExp(r'\s+'));
        for (var i = 1; i <= words.length; i++) {
          engine.onText(TextEvent(words.sublist(0, i).join(' '), false));
          clock.advance(step);
        }
        engine.onText(TextEvent(words.join(' '), true));
        clock.advance(1.0);
      }
    }

    void makeEngine({bool withCharacters = false}) {
      clock = FakeClock();
      audio = FakeAudio();
      events = FakeEvents();
      final world = WorldState(clock: clock.call);
      engine = StoryEngine(
        actions: ActionMatcher(List.of(actions), clock: clock.call),
        scenes: tracker(),
        audio: audio,
        events: events,
        clock: clock.call,
        world: world,
        characters: withCharacters
            ? CharacterTracker(List.of(charData.characters), charData, world)
            : null,
      );
    }

    test('звуковые команды: дождь, лес, падение', () {
      makeEngine();
      feed('Начался дождь. Герои вошли в лес. Орк упал на землю.');
      expect(events.list, contains(('overlay_on', 'rain')));
      expect(events.list, contains(('scene', 'forest')));
      expect(events.list, contains(('sfx', 'fall')));
    });

    test('голоса персонажей при появлении', () {
      makeEngine(withCharacters: true);
      feed('Жили-были дед да баба.');
      expect(events.list, contains(('char', 'old_man')));
      expect(events.list, contains(('char', 'old_woman')));
      expect(audio.sfx, contains('old_man_grunt'));
      expect(audio.sfx, contains('old_woman_sigh'));
    });

    test('голос персонажа ждёт, пока отзвучит звук действия', () {
      makeEngine(withCharacters: true);
      feed('Орк упал на землю.'); // звук действия только что
      // финальная фраза сразу — звук падения ещё звучит (окно characterAfterActionS)
      engine.onText(const TextEvent('Пришёл медведь', true));
      expect(events.list, isNot(contains(('char', 'bear')))); // ждёт
      clock.advance(characterAfterActionS + 0.1);
      engine.tick(); // рассказчик замолчал — доигрываем отложенное
      expect(events.list, contains(('char', 'bear')));
    });
  });
}

class FakeAudio implements AudioOut {
  final List<String> sfx = [];
  final List<String?> scene = [];
  final List<List<String>> overlays = [];
  final List<String?> music = [];

  @override
  void playSfx(String id) => sfx.add(id);
  @override
  void setScene(String? ambience) => scene.add(ambience);
  @override
  void setOverlays(List<String> ambiences) => overlays.add(ambiences);
  @override
  void setMusic(String? m) => music.add(m);
  @override
  void setMix((double, double, double, double) levels) {}
}

class FakeEvents implements EngineEvents {
  final List<(String, String)> list = [];
  final List<String> logs = [];

  @override
  void onEvent(String kind, String id) => list.add((kind, id));
  @override
  void onLog(String message) => logs.add(message);
}
