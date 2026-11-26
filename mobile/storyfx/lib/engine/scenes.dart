/// Медленный слой: окно последних слов → сцена (фон) и наложения (погода, огонь, ночь).
/// Порт prototype/src/storyfx/scenes.py.
library;

import 'dart:math' as math;

import 'package:yaml/yaml.dart';

import 'actions.dart';
import 'config.dart';
import 'textnorm.dart';

class Scene {
  final String id;
  final String ambience;
  final List<String> descriptions;
  final List<Pattern> keywords;
  final bool indoor; // закрытое место: уличная погода там затихает быстрее (D-019)
  List<double>? centroid;
  Scene(this.id, this.ambience, this.descriptions, this.keywords, [this.indoor = false]);
}

class Overlay {
  final String id;
  final String ambience;
  final List<Pattern> keywords;
  final List<Pattern> stop;
  final int? decay;       // D-019: фраз без упоминания — слой затихает сам (null — только stop)
  final int? indoorDecay; // в закрытом месте — быстрее (null — как decay)
  const Overlay(this.id, this.ambience, this.keywords, this.stop, [this.decay, this.indoorDecay]);
}

class SceneData {
  final List<Scene> scenes;
  final List<Overlay> overlays;
  final Set<String> farWords;
  final List<Pattern> notPlaceNear;
  final Set<Set<String>> closeScenes;
  final Set<String> viaWords;
  const SceneData(this.scenes, this.overlays, this.farWords, this.notPlaceNear,
      this.closeScenes, this.viaWords);
}

SceneData loadScenes(String yamlText) {
  final raw = loadYaml(yamlText) as YamlMap;
  final scenes = <Scene>[];
  for (final e in (raw['scenes'] as YamlMap).entries) {
    final s = e.value as YamlMap;
    scenes.add(Scene(
        e.key as String,
        s['ambience'] as String,
        [for (final d in (s['descriptions'] as YamlList? ?? const [])) d.toString()],
        [for (final k in (s['keywords'] as YamlList? ?? const [])) parsePattern(k.toString())],
        s['indoor'] == true));
  }
  final overlays = <Overlay>[];
  for (final e in ((raw['overlays'] as YamlMap?) ?? YamlMap()).entries) {
    final o = e.value as YamlMap;
    overlays.add(Overlay(
        e.key as String,
        o['ambience'] as String,
        [for (final k in (o['keywords'] as YamlList? ?? const [])) parsePattern(k.toString())],
        [for (final k in (o['stop'] as YamlList? ?? const [])) parsePattern(k.toString())],
        o['decay'] as int?,
        o['indoor_decay'] as int?));
  }
  // текстnorm.isReported пользуется этими списками (в Python — lru_cache на том же yaml)
  reportedWords = [
    for (final w in (raw['reported_words'] as YamlList? ?? const [])) parsePattern(w.toString())
  ];
  reportedConnectors = {
    for (final c in (raw['reported_connectors'] as YamlList? ?? ['что'])) c.toString()
  };
  final close = <Set<String>>{};
  for (final grp in (raw['close_scenes'] as YamlList? ?? const [])) {
    final ids = {for (final x in grp as YamlList) x.toString()};
    for (final a in ids) {
      for (final b in ids) {
        if (a != b) close.add({a, b});
      }
    }
  }
  return SceneData(
      scenes,
      overlays,
      {for (final w in (raw['far_words'] as YamlList? ?? const [])) w.toString()},
      [for (final w in (raw['not_place_near'] as YamlList? ?? const [])) parsePattern(w.toString())],
      close,
      {for (final w in (raw['via_words'] as YamlList? ?? const [])) w.toString()});
}

/// Примеры «где герой сейчас» для классификатора сцены по фразе (задача 25).
Map<String, List<String>> loadSceneExamples(String yamlText) {
  final raw = loadYaml(yamlText) as YamlMap;
  final out = <String, List<String>>{};
  for (final e in ((raw['scenes'] as YamlMap?) ?? YamlMap()).entries) {
    out[e.key as String] = [for (final x in e.value as YamlList) x.toString()];
  }
  out[none] = [for (final x in (raw['none'] as YamlList? ?? const [])) x.toString()];
  return out;
}

bool _real(List<Token> tokens, Match m) =>
    !isNegated(tokens, m.start, end: m.end) && !isComparison(tokens, m.start);

class SceneTracker {
  final List<Scene> scenes;
  final List<Overlay> overlays;
  final Embedder? embedder;
  final SceneData data;
  String? current;
  final List<String> activeOverlays = [];
  // Смена ПО СМЫСЛУ (ключевое слово меняет сразу). Настроение — тот же трекер со своими числами.
  final double threshold;
  final double margin;
  final int confirm;
  final int minWords;
  final int minDwell;
  final Map<String, double>? intensity; // только настроение: переход к напряжённому — без выдержки
  final Map<String, List<String>>? examples; // классификатор сцены по фразе (задача 25)
  final bool contextGate; // D-019: медленный контекст откладывает смену без поддержки
  SoftmaxClassifier? _clf;
  List<String> _words = [];
  String? _candidate;
  int _candidateHits = 0;
  int _sinceSwitch = 1000000;
  int _phraseCount = 0;
  final Map<String, int> _overlaySince = {};
  List<double>? _slow;
  List<double>? _phraseVec;
  (String, int)? _pending;
  Map<String, double> lastScores = {};
  (String, double)? lastPhrase;

  SceneTracker(this.scenes, this.overlays,
      {this.embedder,
      required this.data,
      this.current,
      this.threshold = sceneThreshold,
      this.margin = sceneMargin,
      this.confirm = sceneConfirm,
      this.minWords = sceneMinWords,
      this.minDwell = sceneMinDwell,
      this.intensity,
      this.examples,
      this.contextGate = false}) {
    if (embedder != null) {
      for (final s in scenes) {
        if (s.descriptions.isNotEmpty) {
          final vs = embedder!.encode(s.descriptions);
          final v = List<double>.filled(vs[0].length, 0);
          for (final row in vs) {
            for (var i = 0; i < v.length; i++) {
              v[i] += row[i];
            }
          }
          for (var i = 0; i < v.length; i++) {
            v[i] /= vs.length;
          }
          s.centroid = _normalize(v);
        }
      }
      if (examples != null) {
        final known = {for (final s in scenes) s.id, none};
        final pairs = <(String, String)>[];
        for (final e in examples!.entries) {
          if (known.contains(e.key)) {
            for (final ex in e.value) {
              pairs.add((e.key, ex));
            }
          }
        }
        final x = embedder!.encode([for (final p in pairs) p.$2]);
        _clf = SoftmaxClassifier(x, [for (final p in pairs) p.$1]);
      }
    }
  }

  static List<double> _normalize(List<double> v) {
    final n = math.sqrt(v.fold<double>(0, (s, x) => s + x * x)) + 1e-9;
    return [for (final x in v) x / n];
  }

  // ---------- входы ----------

  /// Финальная фраза: обновить окно, наложения и сцену.
  /// speech — какие слова в репликах героев: они не меняют место и погоду.
  List<Change> addUtterance(String text, {List<bool>? speech}) {
    final tokens = tokenize(text);
    final spoken = (speech != null && speech.length == tokens.length)
        ? {for (var i = 0; i < tokens.length; i++) if (speech[i]) i}
        : <int>{};
    final narration = [for (var i = 0; i < tokens.length; i++) if (!spoken.contains(i)) tokens[i].word];
    _words = (_words + narration).length <= sceneWindowWords
        ? _words + narration
        : (_words + narration).sublist((_words + narration).length - sceneWindowWords);
    _sinceSwitch += 1;
    _phraseCount += 1;
    _updateContext(narration);
    final changes = _updateOverlays(tokens, spoken);
    // Отложенная смена (D-019): ждала, что рассказ подтвердит новое место
    if (_pending != null) {
      final (pid, until) = _pending!;
      if (_phraseCount > until) {
        _pending = null; // не подтвердилось — это был не переход
      } else if (_contextSupports(pid)) {
        _pending = null;
        _set(pid, keep: narration.length);
        changes.add(Change('scene', pid, 'контекст подтвердил отложенное'));
        return changes;
      }
    }
    // Явное ключевое слово сцены в последней фразе — сменить сразу («вошли в таверну»)
    var explicit = [
      for (final s in scenes)
        if (_hasPlace(s.keywords, tokens, spoken,
            others: [for (final o in scenes) if (o.id != s.id) ...o.keywords]))
          s
    ];
    final via = [for (final s in explicit) if (_isVia(s.keywords, tokens)) s];
    if (via.isNotEmpty && explicit.length > 1) explicit = via; // «домой через лес» — герой в лесу
    if (explicit.isNotEmpty) {
      final vec = _embed(_words.join(' '));
      explicit.sort((a, b) => _score(b, vec, tokens).compareTo(_score(a, vec, tokens)));
      final best = explicit.first;
      if (best.id != current) {
        final c = _propose(best.id, keep: narration.length, reason: 'ключевое слово');
        if (c != null) changes.add(c);
        return changes;
      }
    }
    // место названо, но правила решили «не здесь» — классификатор их не переспорит
    final named = scenes.any((s) => _hasMatch(s.keywords, tokens, spoken));
    if (!named) {
      final c = _byPhrase(narration);
      if (c != null) {
        changes.add(c);
        return changes;
      }
    }
    final c = evaluate();
    if (c != null) changes.add(c);
    return changes;
  }

  Change? _byPhrase(List<String> narration) {
    if (_clf == null || narration.length < sceneClfMinWords) return null;
    final p = _clf!.probs(_embed(narration.join(' '))!);
    final order = List<int>.generate(p.length, (i) => i)..sort((a, b) => p[b].compareTo(p[a]));
    final label = _clf!.classes[order[0]];
    final conf = p[order[0]], second = p[order[1]];
    lastPhrase = (label, conf);
    if (label == none || label == current || conf < sceneClfConf || conf - second < sceneClfMargin) {
      return null;
    }
    // близкие места (река и море) по одной фразе не различить — меняет только слово места
    if (data.closeScenes.any((pair) => pair.contains(label) && pair.contains(current))) {
      return null;
    }
    return _propose(label, keep: narration.length, reason: 'по фразе (${conf.toStringAsFixed(2)})');
  }

  // Хуки для тестов: подменить окно слов и счётчик фраз после смены (как в pytest).
  void debugSetWindow(List<String> words) => _words = words;
  void debugSetSinceSwitch(int n) => _sinceSwitch = n;
  void debugAdvanceSwitch(int n) => _sinceSwitch += n;

  /// Оценка по смыслу всего окна (с гистерезисом). Можно вызывать с текущим частичным текстом.
  Change? evaluate([String extraText = '']) {
    final words = _words + tokenizeWords(extraText);
    if (words.isEmpty) return null;
    final text = words.join(' ');
    final tokens = tokenize(text);
    final vec = _embed(text);
    final scores = {for (final s in scenes) s.id: _score(s, vec, tokens)};
    lastScores = scores;
    if (words.length < minWords) return null;
    final bestId = scores.keys.reduce((a, b) => scores[a]! >= scores[b]! ? a : b);
    if (_sinceSwitch < minDwell && !_escalates(bestId)) return null;
    final best = scores[bestId]!;
    final cur = current != null ? scores[current] ?? 0.0 : 0.0;
    if (bestId == current || best < threshold || best - cur < margin) {
      _candidate = null;
      _candidateHits = 0;
      return null;
    }
    if (bestId == _candidate) {
      _candidateHits += 1;
    } else {
      _candidate = bestId;
      _candidateHits = 1;
    }
    if (_candidateHits >= confirm) {
      _set(bestId);
      return Change('scene', bestId, 'по смыслу (${best.toStringAsFixed(2)})');
    }
    return null;
  }

  // ---------- внутреннее ----------

  bool _notAPlace(List<Token> tokens, int start, int end) {
    // «вскрыл замок отмычкой» — дверной замок, а не замок короля
    final near = [
      ...tokens.sublist(start - 3 < 0 ? 0 : start - 3, start),
      ...tokens.sublist(end + 1, (end + 4).clamp(0, tokens.length))
    ];
    return data.notPlaceNear.any((p) => findMatches(p, near).isNotEmpty);
  }

  bool _isVia(List<Pattern> patterns, List<Token> tokens) {
    // «…домой через тёмный лес» — место, по которому идёт герой
    for (final p in patterns) {
      for (final m in findMatches(p, tokens)) {
        final from = m.start - 2 < 0 ? 0 : m.start - 2;
        if (tokens.sublist(from, m.start).any((t) => data.viaWords.contains(t.word))) return true;
      }
    }
    return false;
  }

  bool _isFar(List<Token> tokens, int start) {
    // «пропали за тёмным лесом», «вдалеке за рекой» — место вдали, не то, где герой
    final from = start - 2 < 0 ? 0 : start - 2;
    return tokens.sublist(from, start).any((t) => data.farWords.contains(t.word));
  }

  bool _farChain(List<Token> tokens, int end, List<Pattern> others) {
    // «цветок растёт на болоте за рекой» — место, сразу за которым «за <другое место>», тоже вдали
    if (end + 1 >= tokens.length || !data.farWords.contains(tokens[end + 1].word)) return false;
    for (final p in others) {
      for (final m in findMatches(p, tokens)) {
        if (m.start >= end + 2 && m.start <= end + 3) return true;
      }
    }
    return false;
  }

  bool _hasPlace(List<Pattern> patterns, List<Token> tokens, Set<int> skip,
      {List<Pattern> others = const []}) {
    for (final p in patterns) {
      for (final m in findMatches(p, tokens)) {
        if (_real(tokens, m) &&
            !skip.contains(m.start) &&
            !_isFar(tokens, m.start) &&
            !_farChain(tokens, m.end, others) &&
            !isReported(tokens, m.start) &&
            !_notAPlace(tokens, m.start, m.end)) {
          return true;
        }
      }
    }
    return false;
  }

  bool _hasMatch(List<Pattern> patterns, List<Token> tokens, Set<int> skip) =>
      patterns.any((p) => findMatches(p, tokens).any((m) => _real(tokens, m) && !skip.contains(m.start)));

  bool _hasWeather(List<Pattern> patterns, List<Token> tokens, Set<int> skip) => patterns.any((p) =>
      findMatches(p, tokens)
          .any((m) => _real(tokens, m) && !skip.contains(m.start) && !isReported(tokens, m.start)));

  void _updateContext(List<String> narration) {
    // Медленный контекст (D-019): EMA векторов последних фраз. Нужен только при contextGate.
    if (!contextGate || embedder == null || narration.isEmpty) return;
    final v = _embed(narration.join(' '))!;
    _phraseVec = v;
    const a = contextSlowAlpha;
    _slow = _slow == null
        ? v
        : [for (var i = 0; i < v.length; i++) (1 - a) * _slow![i] + a * v[i]];
    _slow = _normalize(_slow!);
  }

  static double _dot(List<double> a, List<double> b) {
    var s = 0.0;
    for (var i = 0; i < a.length; i++) {
      s += a[i] * b[i];
    }
    return s;
  }

  bool _contextSupports(String target) {
    if (_slow == null || current == null) return true;
    final s = scenes.where((x) => x.id == target).firstOrNull;
    final c = scenes.where((x) => x.id == current).firstOrNull;
    if (s?.centroid == null || c?.centroid == null) return true;
    return _dot(_slow!, s!.centroid!) >= _dot(_slow!, c!.centroid!) - contextContradict;
  }

  bool _phrasePrefers(String target) {
    final p = _phraseVec;
    if (p == null || current == null) return false;
    final s = scenes.where((x) => x.id == target).firstOrNull;
    final c = scenes.where((x) => x.id == current).firstOrNull;
    if (s?.centroid == null || c?.centroid == null) return false;
    return _dot(p, s!.centroid!) > _dot(p, c!.centroid!);
  }

  Change? _propose(String sceneId, {required int keep, required String reason}) {
    // Смена места/настроения. Без фильтра — сразу. С фильтром (настроение): сразу, если фраза сама
    // ближе к новому или контекст не против; иначе откладываем на contextPendingPhrases фраз (D-019).
    if (sceneId == current) return null;
    if (!contextGate || _slow == null) {
      _set(sceneId, keep: keep);
      return Change('scene', sceneId, reason);
    }
    if (_pending != null && _pending!.$1 == sceneId) {
      _pending = null;
      _set(sceneId, keep: keep);
      return Change('scene', sceneId, '$reason (подтверждено)');
    }
    if (_phrasePrefers(sceneId) || _contextSupports(sceneId)) {
      _set(sceneId, keep: keep);
      return Change('scene', sceneId, reason);
    }
    _pending = (sceneId, _phraseCount + contextPendingPhrases);
    return null;
  }

  bool _escalates(String target) {
    if (intensity == null || current == null) return false;
    return (intensity![target] ?? 0.0) > (intensity![current] ?? 0.0);
  }

  void _set(String sceneId, {int? keep}) {
    current = sceneId;
    _candidate = null;
    _candidateHits = 0;
    _pending = null;
    _sinceSwitch = 0;
    // Перешли в новое место — слова о прежнем месте больше не голосуют (D-011).
    final n = keep ?? sceneKeepAfterSwitch;
    _words = n > 0
        ? (_words.length <= n ? _words : _words.sublist(_words.length - n))
        : [];
  }

  List<double>? _embed(String text) => embedder?.encode([text])[0];

  double _score(Scene scene, List<double>? vec, List<Token> tokens) {
    var sim = 0.0;
    if (vec != null && scene.centroid != null) sim = _dot(vec, scene.centroid!);
    // голосует слово, а не шаблон: «гнал» под три формы «гнался/гналась/гнались» — один голос
    final kw = <int>{};
    for (final p in scene.keywords) {
      for (final m in findMatches(p, tokens)) {
        if (_real(tokens, m)) {
          for (var i = m.start; i <= m.end; i++) {
            kw.add(i);
          }
        }
      }
    }
    return sim + math.min(kw.length, 3) * keywordBonus;
  }

  bool _indoor() {
    final s = scenes.where((x) => x.id == current).firstOrNull;
    return s?.indoor ?? false;
  }

  int? _lifetime(Overlay o) {
    if (o.decay == null) return null;
    if (_indoor() && o.indoorDecay != null) return o.indoorDecay;
    return o.decay;
  }

  Change _overlayOff(Overlay o, String reason) {
    activeOverlays.remove(o.id);
    _overlaySince.remove(o.id);
    return Change('overlay_off', o.id, reason);
  }

  /// Слои погоды — затухающая активация (D-019): упоминание подзаряжает слой, без подкрепления
  /// он затихает сам за `decay` фраз (в закрытом месте — за `indoorDecay`), стоп-фраза гасит сразу.
  List<Change> _updateOverlays(List<Token> tokens, Set<int> spoken) {
    final changes = <Change>[];
    for (final o in overlays) {
      final mentioned = _hasWeather(o.keywords, tokens, spoken);
      final stopped = _hasWeather(o.stop, tokens, spoken);
      if (activeOverlays.contains(o.id)) {
        if (stopped) {
          changes.add(_overlayOff(o, 'стоп-фраза'));
        } else if (mentioned) {
          _overlaySince[o.id] = _phraseCount; // снова назвали — отсчёт заново
        } else {
          final life = _lifetime(o);
          if (life != null && _phraseCount - (_overlaySince[o.id] ?? 0) >= life) {
            changes.add(_overlayOff(o, 'затихло: $life фраз без упоминания'));
          }
        }
      } else if (mentioned && !stopped) {
        _overlaySince[o.id] = _phraseCount;
        activeOverlays.add(o.id);
        changes.add(Change('overlay_on', o.id, 'ключевое слово'));
        while (activeOverlays.length > maxOverlays) {
          final old = overlays.firstWhere((x) => x.id == activeOverlays[0]);
          changes.add(_overlayOff(old, 'вытеснено новым'));
        }
      }
    }
    return changes;
  }

  String? ambienceFor(String? sceneId) =>
      scenes.where((s) => s.id == sceneId).map((s) => s.ambience).firstOrNull;

  String overlayAmbience(String overlayId) =>
      overlays.firstWhere((o) => o.id == overlayId).ambience;
}

class Change {
  final String kind; // scene | overlay_on | overlay_off
  final String? id;
  final String reason;
  const Change(this.kind, this.id, this.reason);
}
