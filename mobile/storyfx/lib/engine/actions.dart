/// Звуки действий по смыслу фразы — порт prototype/src/storyfx/actions.py.
///
/// 1. Фраза режется на части по союзам. 2. В части с якорем темы ждём контекст.
/// 3. Классификатор темы по смыслу выбирает вариант («прискакала» → gallop, «погладил» → snort).
library;

import 'dart:math' as math;

import 'package:yaml/yaml.dart';

import 'config.dart';
import 'textnorm.dart';

const none = '_none';

class Variant {
  final String id;
  final List<String> examples;
  final List<Pattern> cues; // слова-подсказки (оружие): есть в отрывке — уверенность × cueBoost
  const Variant(this.id, this.examples, [this.cues = const []]);
}

class ActionGroup {
  final String id;
  final List<Pattern> topic;
  final List<Variant> variants;
  final double cooldown;
  const ActionGroup(this.id, this.topic, this.variants,
      [this.cooldown = defaultCooldownS]);

  List<String> get sounds => [for (final v in variants) if (v.id != none) v.id];
}

class Decision {
  final String group;
  final String? sfx; // null — тема упомянута, но звук не нужен (или запрещён)
  final double confidence;
  final String context;
  final String note;
  const Decision(this.group, this.sfx, this.confidence, this.context, [this.note = '']);
}

List<ActionGroup> loadActions(String yamlText) {
  final raw = loadYaml(yamlText) as YamlMap;
  final groups = <ActionGroup>[];
  for (final entry in raw.entries) {
    final gid = entry.key as String;
    final g = entry.value as YamlMap;
    final variants = <Variant>[];
    for (final ve in (g['variants'] as YamlMap).entries) {
      final vid = ve.key as String;
      final v = ve.value as YamlMap;
      variants.add(Variant(
          vid,
          [for (final e in v['examples'] as YamlList) e.toString()],
          [for (final c in (v['cues'] as YamlList? ?? const [])) parsePattern(c.toString())]));
    }
    groups.add(ActionGroup(
        gid,
        [for (final p in g['topic'] as YamlList) parsePattern(p.toString())],
        variants,
        (g['cooldown'] as num?)?.toDouble() ?? defaultCooldownS));
  }
  return groups;
}

// ---------- классификаторы ----------
class SoftmaxClassifier {
  /// Многоклассовая логистическая регрессия, обучается за доли секунды (как в Python).
  late final List<String> classes;
  late final List<List<double>> w; // [dim][nClasses]
  late final List<double> b;

  SoftmaxClassifier(List<List<double>> x, List<String> labels,
      {int iters = 1500, double lr = 1.5, double l2 = 1e-3}) {
    classes = labels.toSet().toList()..sort();
    final dim = x[0].length, nc = classes.length, n = labels.length;
    final y = [for (final l in labels) classes.indexOf(l)];
    w = [for (var i = 0; i < dim; i++) List<double>.filled(nc, 0)];
    b = List<double>.filled(nc, 0);
    for (var it = 0; it < iters; it++) {
      // p = softmax(X @ W + b)
      final p = <List<double>>[];
      for (var r = 0; r < n; r++) {
        final z = List<double>.filled(nc, 0);
        for (var c = 0; c < nc; c++) {
          var s = b[c];
          for (var d = 0; d < dim; d++) {
            s += x[r][d] * w[d][c];
          }
          z[c] = s;
        }
        p.add(_softmax(z));
        p[r][y[r]] -= 1;
      }
      // W -= lr * (Xᵀ p / n + l2 W); b -= lr * mean(p)
      for (var d = 0; d < dim; d++) {
        for (var c = 0; c < nc; c++) {
          var g = l2 * w[d][c];
          for (var r = 0; r < n; r++) {
            g += x[r][d] * p[r][c] / n;
          }
          w[d][c] -= lr * g;
        }
      }
      for (var c = 0; c < nc; c++) {
        var m = 0.0;
        for (var r = 0; r < n; r++) {
          m += p[r][c];
        }
        b[c] -= lr * m / n;
      }
    }
  }

  static List<double> _softmax(List<double> z) {
    final mx = z.reduce(math.max);
    var sum = 0.0;
    final e = [for (final v in z) math.exp(v - mx)];
    for (final v in e) {
      sum += v;
    }
    return [for (final v in e) v / sum];
  }

  List<double> probs(List<double> xVec) {
    final z = List<double>.filled(classes.length, 0);
    for (var c = 0; c < classes.length; c++) {
      var s = b[c];
      for (var d = 0; d < xVec.length; d++) {
        s += xVec[d] * w[d][c];
      }
      z[c] = s;
    }
    return _softmax(z);
  }

  (String, double) predict(List<double> xVec) {
    final p = probs(xVec);
    var i = 0;
    for (var c = 1; c < p.length; c++) {
      if (p[c] > p[i]) i = c;
    }
    return (classes[i], p[i]);
  }
}

class LexicalClassifier {
  /// Запасной вариант без модели смысла: у кого больше общих основ слов с примерами.
  final List<(String, Set<String>)> examples;
  LexicalClassifier(ActionGroup group)
      : examples = [
          for (final v in group.variants)
            for (final e in v.examples)
              (v.id, {for (final t in tokenize(e)) t.stem})
        ];

  (String, double) predictText(String text) {
    final stems = {for (final t in tokenize(text)) t.stem};
    var best = none, bestScore = 0.0;
    for (final (vid, ex) in examples) {
      final score = stems.intersection(ex).length / (math.sqrt(ex.length) + 1e-9);
      if (score > bestScore) {
        best = vid;
        bestScore = score;
      }
    }
    return (best, math.min(1.0, bestScore));
  }
}

/// Векторы смысла — абстракция над rubert-tiny2 (на телефоне — ONNX).
abstract class Embedder {
  List<List<double>> encode(List<String> texts);
}

// ---------- разбор фразы ----------
/// Части фразы между союзами: (начало, конец включительно, закрыта ли союзом справа).
List<(int, int, bool)> splitClauses(List<Token> tokens) {
  final out = <(int, int, bool)>[];
  var start = 0;
  for (var i = 0; i < tokens.length; i++) {
    // «так и не зарычал»: союз перед отрицанием не делит фразу
    final nxt = i + 1 < tokens.length ? tokens[i + 1].word : '';
    if (clauseBreaks.contains(tokens[i].word) && !negations.contains(nxt)) {
      if (i > start) out.add((start, i - 1, true));
      start = i + 1;
    }
  }
  if (start < tokens.length) out.add((start, tokens.length - 1, false));
  return out;
}

class ActionMatcher {
  final List<ActionGroup> groups;
  final Embedder? embedder;
  final double Function() clock;
  final bool useDeadlines; // речь: решать не позже ~1 с (D-011). Набор текста: false
  final Set<(int, String, String, int)> _seen = {};
  final Set<(int, String, String)> _silent = {};
  final Map<String, double> _lastFired = {};
  final Map<String, Object> _clf = {}; // SoftmaxClassifier | LexicalClassifier
  final Map<(int, String, String, int, String), double> _firstSeen = {};
  Map<String, (String, double)> _carry = {}; // тема → (хвост прошлой фразы, когда кончилась)

  ActionMatcher(this.groups, {this.embedder, required this.clock, this.useDeadlines = true}) {
    if (embedder != null) {
      final texts = [for (final g in groups) for (final v in g.variants) ...v.examples];
      final x = embedder!.encode(texts);
      var i = 0;
      for (final g in groups) {
        final labels = [for (final v in g.variants) for (var k = 0; k < v.examples.length; k++) v.id];
        _clf[g.id] = SoftmaxClassifier(x.sublist(i, i + labels.length), labels);
        i += labels.length;
      }
    } else {
      for (final g in groups) {
        _clf[g.id] = LexicalClassifier(g);
      }
    }
  }

  (String, double) classify(ActionGroup group, String text) {
    final clf = _clf[group.id]!;
    if (clf is LexicalClassifier) return clf.predictText(text);
    final sc = clf as SoftmaxClassifier;
    final p = sc.probs(embedder!.encode([text])[0]);
    // Подсказки: «чем бьют» решает звук (булава — грохот, кинжал — укол), а маленькая модель
    // редкие слова чувствует слабо. Решает всё равно смысл — подсказка лишь перевешивает.
    final tokens = tokenize(text);
    for (final v in group.variants) {
      if (v.cues.isNotEmpty &&
          sc.classes.contains(v.id) &&
          v.cues.any((c) => findMatches(c, tokens).isNotEmpty)) {
        p[sc.classes.indexOf(v.id)] *= cueBoost;
      }
    }
    final sum = p.reduce((a, b) => a + b);
    var i = 0;
    for (var c = 1; c < p.length; c++) {
      if (p[c] > p[i]) i = c;
    }
    return (sc.classes[i], p[i] / sum);
  }

  List<Decision> process(String text, int utteranceId, bool final_) {
    final base = tokenize(text);
    final decisions = <Decision>[];
    final now = clock();
    final carryNext = <String, (String, double)>{};
    for (final g in groups) {
      // Задача 27: пауза разрезала событие — хвост прошлой фразы с якорем «без звука»
      // становится началом этой (один раз, если фраза началась скоро и в ней нет своего слова темы).
      List<Token> tokens;
      int nCarry;
      final carried = _carry[g.id];
      if (carried != null &&
          now - carried.$2 <= actionCarryS &&
          !g.topic.any((p) => findMatches(p, base).isNotEmpty)) {
        tokens = tokenize('${carried.$1} $text');
        nCarry = tokens.length - base.length;
      } else {
        tokens = base;
        nCarry = 0;
      }
      if (tokens.isEmpty) continue;
      final clauses = splitClauses(tokens);
      // части фразы, где есть якорь этой темы: (начало, конец, якоря)
      final anchored = <(int, int, List<int>)>[];
      for (final (start, end, _) in clauses) {
        final clause = tokens.sublist(start, end + 1);
        final anchors = <int>{};
        for (final p in g.topic) {
          for (final m in findMatches(p, clause)) {
            anchors.add(start + m.start);
          }
        }
        if (anchors.isNotEmpty) {
          final sorted = anchors.toList()..sort();
          anchored.add((start, end, sorted));
        }
      }
      for (var k = 0; k < anchored.length; k++) {
        final (start, end, anchors) = anchored[k];
        // Ключ — слово-якорь и его номер среди одинаковых слов фразы, а не позиция:
        // распознаватель переписывает начало фразы, позиции сдвигаются.
        final aw = tokens[anchors[0]].word;
        var awIndex = 0;
        for (var t = 0; t < anchors[0]; t++) {
          if (tokens[t].word == aw) awIndex++;
        }
        final key = (utteranceId, g.id, aw, awIndex);
        if (_seen.contains(key)) continue;
        // повтор того же слова-якоря в той же фразе — то же событие (контрольная №4)
        if (_silent.contains((utteranceId, g.id, aw))) {
          _seen.add(key);
          final rep = tokens.sublist(
              math.max(start, anchors[0] - contextBefore),
              math.min(tokens.length - 1, anchors.last + contextAfter) + 1);
          decisions.add(Decision(g.id, null, 1.0,
              rep.map((t) => t.word).join(' '), 'повтор слова — то же событие'));
          continue;
        }
        var limit = k + 1 < anchored.length ? anchored[k + 1].$1 - 2 : tokens.length - 1;
        // после «а/но» уже другой герой, не наш контекст
        int? stop;
        for (var i = anchors.last + 1; i <= limit; i++) {
          if (contextStop.contains(tokens[i].word)) {
            stop = i;
            break;
          }
        }
        if (stop != null) limit = stop - 1;
        final hi = math.min(limit, anchors.last + contextAfter);
        final ready = final_ ||
            k + 1 < anchored.length ||
            stop != null ||
            tokens.length - 1 >= anchors.last + contextAfter;
        var lo = math.max(start, anchors[0] - contextBefore);
        if (anchors[0] - start <= contextClauseStart) lo = start;
        final ctxTokens = tokens.sublist(lo, hi + 1);
        final ctx = ctxTokens.map((t) => t.word).join(' ');
        final negated = anchors.any((a) => isNegated(tokens, a));
        final simile = anchors.every((a) => isComparison(tokens, a));
        String? label;
        double? conf;
        if (!ready) {
          final bare = tokens.length - 1 <= anchors.last; // после якоря ещё ни слова
          if (negated || simile || pendingWords.contains(tokens.last.word)) continue;
          if (!useDeadlines) {
            // набор текста: только ранний выстрел, когда за якорем уже есть слово и смысл ясен
            if (bare) continue;
            (label, conf) = classify(g, ctx);
            if (label == none || conf < actionEarlyConf) continue;
          } else {
            // D-011: звук ≤ 1 с. Чем дольше ждём, тем меньше уверенности нужно.
            final fsKey = (utteranceId, g.id, aw, awIndex, tokens[anchors.last].word);
            final waited = now - _firstSeen.putIfAbsent(fsKey, () => now);
            if (waited < actionSoftDeadlineS && bare) continue;
            (label, conf) = classify(g, ctx);
            var need = waited < actionSoftDeadlineS
                ? actionEarlyConf
                : waited < actionHardDeadlineS
                    ? actionSoftConf
                    : actionLateConf;
            if (bare) {
              if (label == none) continue;
              need = math.max(need, actionBareConf);
            }
            // «без звука» не спешим: тишина не опаздывает, а дальше может прийти смысл
            if (label == none || conf < need) continue;
          }
        }
        _seen.add(key);
        if (negated) {
          decisions.add(Decision(g.id, null, 1.0, ctx, 'отрицание'));
          continue;
        }
        if (simile) {
          decisions.add(Decision(g.id, null, 1.0, ctx, 'сравнение'));
          continue;
        }
        label ??= (() {
          final r = classify(g, ctx);
          conf = r.$2;
          return r.$1;
        })();
        final variant = g.variants.where((v) => v.id == label).firstOrNull;
        final silent = label == none ||
            variant == null ||
            conf! < actionMinConf ||
            (ctxTokens.length <= anchors.length && conf! < actionBareConf);
        if (silent &&
            final_ &&
            useDeadlines &&
            k + 1 == anchored.length &&
            stop == null &&
            anchors[0] >= nCarry &&
            tokens.length - 1 - anchors.last < contextAfter &&
            tokens.length - nCarry <= actionCarryWords) {
          // короткий обрывок кончился сразу за якорем — продолжение, возможно, в следующей
          carryNext[g.id] = (tokens.sublist(lo).map((t) => t.word).join(' '), now);
        }
        if (label == none || variant == null) {
          _silent.add((utteranceId, g.id, aw));
          decisions.add(Decision(g.id, null, conf!, ctx, 'по смыслу без звука'));
        } else if (conf! < actionMinConf) {
          decisions.add(Decision(g.id, null, conf!, ctx, 'не уверен ($label)'));
        } else if (ctxTokens.length <= anchors.length && conf! < actionBareConf) {
          decisions.add(Decision(g.id, null, conf!, ctx, 'одно слово, не уверен ($label)'));
        } else if (now - (_lastFired[label] ?? -1e9) < g.cooldown) {
          decisions.add(Decision(g.id, null, conf!, ctx, 'кулдаун ($label)'));
        } else {
          _lastFired[label] = now;
          decisions.add(Decision(g.id, label, conf!, ctx));
        }
      }
    }
    if (final_) {
      _carry = carryNext;
      _seen.removeWhere((k) => k.$1 == utteranceId);
      _silent.removeWhere((k) => k.$1 == utteranceId);
      _firstSeen.removeWhere((k, v) => k.$1 == utteranceId);
    }
    return decisions;
  }
}
