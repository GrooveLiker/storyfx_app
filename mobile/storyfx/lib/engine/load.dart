/// Сборка движка из YAML-данных приложения (assets/data/) — аналог cli.py:make_engine.
library;

import 'package:flutter/services.dart' show rootBundle;
import 'package:yaml/yaml.dart';

import 'actions.dart';
import 'characters.dart';
import 'engine.dart';
import 'mixer.dart';
import 'mood.dart';
import 'scenes.dart';
import 'speech.dart';
import 'world.dart';

/// Выключенные звуки (muted.yaml, формат «kind/id») — порт muted.py:load_muted.
Set<String> parseMuted(String yamlText) {
  final raw = loadYaml(yamlText);
  if (raw is! YamlMap) return {};
  return {for (final m in (raw['muted'] as YamlList? ?? const [])) m.toString()};
}

/// Монотонные часы движка (секунды с запуска).
double Function() monotonicClock() {
  final sw = Stopwatch()..start();
  return () => sw.elapsedMicroseconds / 1e6;
}

/// Готовый движок со всеми звеньями. Без [embedder] — лексический режим
/// (запасной классификатор по основам слов, сцены по ключевым словам).
Future<StoryEngine> loadEngine({
  required AudioOut audio,
  required EngineEvents events,
  Embedder? embedder,
  bool music = false,
  bool verbose = true,
}) async {
  Future<String> rd(String name) => rootBundle.loadString('assets/data/$name');

  final sceneData = loadScenes(await rd('scenes.yaml'));
  final (moods, defaultMood) = loadMoods(await rd('moods.yaml'));
  final charData = loadCharacters(await rd('characters.yaml'));
  final clock = monotonicClock();
  final world = WorldState(clock: clock);

  final engine = StoryEngine(
    actions: ActionMatcher(loadActions(await rd('actions.yaml')),
        embedder: embedder, clock: clock),
    scenes: SceneTracker(List.of(sceneData.scenes), List.of(sceneData.overlays),
        embedder: embedder,
        data: sceneData,
        examples: embedder != null
            ? loadSceneExamples(await rd('scene_examples.yaml'))
            : null),
    audio: audio,
    events: events,
    clock: clock,
    world: world,
    moods: makeMoodTracker(moods, defaultMood, sceneData, embedder: embedder),
    characters:
        CharacterTracker(List.of(charData.characters), charData, world),
    mixer: SoundMixer(clock: clock, mood: defaultMood),
    speechCues: loadSpeechCues(await rd('speech.yaml')),
    muted: parseMuted(await rd('muted.yaml')),
    verbose: verbose,
  );
  if (music) engine.setMusicEnabled(true);
  return engine;
}
