/// Настроение рассказа (спокойное / весёлое / тревожное / динамичное) → фоновая музыка.
/// Порт prototype/src/storyfx/mood.py.
library;

import 'package:yaml/yaml.dart';

import 'actions.dart';
import 'config.dart';
import 'scenes.dart';
import 'textnorm.dart';

(List<Scene>, String) loadMoods(String yamlText) {
  final raw = loadYaml(yamlText) as YamlMap;
  final moods = <Scene>[];
  for (final e in (raw['moods'] as YamlMap).entries) {
    final m = e.value as YamlMap;
    moods.add(Scene(
        e.key as String,
        m['music'] as String,
        [for (final d in (m['descriptions'] as YamlList? ?? const [])) d.toString()],
        [for (final k in (m['keywords'] as YamlList? ?? const [])) parsePattern(k.toString())]));
  }
  final defaultMood = (raw['default'] as String?) ?? moods.first.id;
  if (!moods.any((m) => m.id == defaultMood)) {
    throw ArgumentError('moods.yaml: default="$defaultMood" нет среди настроений');
  }
  return (moods, defaultMood);
}

/// Настроение меняется реже сцены: музыка, прыгающая каждые полминуты, мешает.
/// Ключевое слово — сразу; по смыслу — свои порог, подтверждения и выдержка.
SceneTracker makeMoodTracker(List<Scene> moods, String defaultMood, SceneData data,
    {Embedder? embedder}) {
  final t = SceneTracker(List.of(moods), [],
      embedder: embedder,
      data: data,
      threshold: moodThreshold,
      margin: moodMargin,
      confirm: moodConfirm,
      minWords: sceneMinWords,
      minDwell: moodMinDwell,
      intensity: moodIntensity, // напряжение растёт — без выдержки
      contextGate: true);       // D-019: «поле, где вчера шла битва» ≠ динамичная музыка
  t.current = defaultMood;
  return t;
}
