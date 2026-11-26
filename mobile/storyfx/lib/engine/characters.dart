/// Персонажи: звук при появлении в рассказе — порт prototype/src/storyfx/characters.py.
library;

import 'package:yaml/yaml.dart';

import 'actions.dart';
import 'config.dart';
import 'textnorm.dart';
import 'world.dart';

class Character {
  final String id;
  final String sound;
  final List<Pattern> names;
  final String title;
  final List<String> quietMoods; // в этих настроениях голос молчит
  final List<Pattern> quietWords; // с этими словами в фразе голос молчит
  final List<String> voicedBy;    // звуки действий, которые и есть его голос
  const Character(this.id, this.sound, this.names,
      [this.title = '', this.quietMoods = const [], this.quietWords = const [], this.voicedBy = const []]);

  bool isQuietIn(String text) {
    final tokens = tokenize(text);
    return quietWords.any((p) => findMatches(p, tokens).isNotEmpty);
  }
}

class CharactersData {
  final List<Character> characters;
  final List<Pattern> leaveWords;
  final Set<String> leaveSpeakers;
  final Set<String> witnessBefore;
  final List<Pattern> witnessAfter;
  const CharactersData(this.characters, this.leaveWords, this.leaveSpeakers,
      this.witnessBefore, this.witnessAfter);
}

CharactersData loadCharacters(String yamlText) {
  final raw = loadYaml(yamlText) as YamlMap;
  final characters = <Character>[];
  for (final e in (raw['characters'] as YamlMap).entries) {
    final c = e.value as YamlMap;
    characters.add(Character(
        e.key as String,
        c['sound'] as String,
        [for (final n in c['names'] as YamlList) parsePattern(n.toString())],
        (c['title'] as String?) ?? e.key as String,
        [for (final m in (c['quiet_moods'] as YamlList? ?? const [])) m.toString()],
        [for (final w in (c['quiet_words'] as YamlList? ?? const [])) parsePattern(w.toString())],
        [for (final v in (c['voiced_by'] as YamlList? ?? const [])) v.toString()]));
  }
  final witness = (raw['leave_witness'] as YamlMap?) ?? YamlMap();
  return CharactersData(
      characters,
      [for (final p in (raw['leave'] as YamlList? ?? const [])) parsePattern(p.toString())],
      {for (final s in (raw['leave_speakers'] as YamlList? ?? const [])) s.toString()},
      {for (final s in (witness['before'] as YamlList? ?? const [])) s.toString()},
      [for (final p in (witness['after'] as YamlList? ?? const [])) parsePattern(p.toString())]);
}

/// «медведя в лесу не было», «волка нигде нет» — персонажа нет. «медведь не спал» — есть.
bool _absentAfter(List<Token> tokens, int end, [int window = 4]) {
  final after = tokens.sublist(end + 1, (end + 1 + window).clamp(0, tokens.length)).map((t) => t.word).toList();
  if (after.contains('нет')) return true;
  for (var i = 0; i + 1 < after.length; i++) {
    if (after[i] == 'не' && after[i + 1].startsWith('был')) return true;
  }
  return false;
}

/// «что ты наделал, старый пёс» — обращение к собеседнику: это не появление собаки.
bool _isAddress(List<Token> tokens, int start) {
  final from = start - addressWindow < 0 ? 0 : start - addressWindow;
  return tokens.sublist(from, start).any((t) => addressWords.contains(t.word));
}

class Appearance {
  final Character character;
  final String word;
  final int position;
  const Appearance(this.character, this.word, this.position);
}

class _Mention {
  Character character;
  String word;
  int position;
  bool leaving = false;
  bool cameFirst = false;
  bool obj;
  bool address;
  _Mention(this.character, this.word, this.position,
      {this.obj = false, this.address = false});
}

/// Наблюдатель: кого упомянули во фразе и уходит ли он. Кто на сцене — решает WorldState (D-011).
class CharacterTracker {
  final List<Character> characters;
  final CharactersData data;
  final WorldState world;
  late final List<(Pattern, Character)> _names;

  CharacterTracker(this.characters, this.data, this.world) {
    // все имена всех персонажей, длинные и точные — первыми
    _names = [for (final c in characters) for (final p in c.names) (p, c)]
      ..sort((a, b) {
        final sa = a.$1.specificity, sb = b.$1.specificity;
        return sb.$1 != sa.$1 ? sb.$1.compareTo(sa.$1) : sb.$2.compareTo(sa.$2);
      });
  }

  /// Финальная фраза → упоминания персонажей (первое на каждого), с пометкой «уходит».
  List<Mention> observe(String text) {
    final tokens = tokenize(text);
    final leaveClauses = <(int, int)>[];
    for (final (s, e, _) in splitClauses(tokens)) {
      final clause = tokens.sublist(s, e + 1);
      if (data.leaveWords.any((p) => findMatches(p, clause).isNotEmpty)) {
        leaveClauses.add((s, e));
      }
    }
    final taken = <int>{};
    final found = <String, _Mention>{};
    for (final (pattern, ch) in _names) {
      for (final m in findMatches(pattern, tokens)) {
        final span = {for (var i = m.start; i <= m.end; i++) i};
        if (span.any(taken.contains)) continue; // слово занято более длинным именем
        taken.addAll(span);
        if (isNegated(tokens, m.start, end: m.end) ||
            _absentAfter(tokens, m.end) ||
            isComparison(tokens, m.start) ||
            isReported(tokens, m.start)) {
          continue; // «медведя не было», «сильный, как медведь», «рассказывал про волка»
        }
        final newM = _Mention(ch, tokens[m.start].word, m.start,
            obj: m.start > 0 && objectPrepositions.contains(tokens[m.start - 1].word),
            address: _isAddress(tokens, m.start));
        final old = found[ch.id];
        // одно упоминание на персонажа: прямое важнее косвенного
        if (old == null || ((old.obj || old.address) && !(newM.obj || newM.address))) {
          found[ch.id] = newM;
        }
      }
    }
    final mentions = found.values.toList()..sort((a, b) => a.position.compareTo(b.position));
    for (final (s, e) in leaveClauses) {
      final inClause = mentions.where((m) => m.position >= s && m.position <= e).toList();
      // «я у дедушки ушёл» — дедушка дополнение (после «у»), уходит не он
      var leaving = inClause.where((m) => !m.obj && !m.address).toList();
      final speakers = [for (var i = s; i <= e; i++) if (data.leaveSpeakers.contains(tokens[i].word)) i];
      if (speakers.isNotEmpty) {
        // «не ешь меня серый волк я от волка ушёл» — уходит «я»
        leaving = leaving.where((m) => m.position > speakers.last).toList();
      } else if (inClause.isEmpty) {
        // «заяц испугался и убежал» — уходит последний названный до этой части
        leaving = mentions.where((m) => m.position < s && !m.obj && !m.address).toList();
        if (leaving.length > 1) leaving = [leaving.last];
        for (final m in leaving) {
          m.cameFirst = true;
        }
      }
      for (final m in leaving) {
        if (!_isWitness(tokens, m.position)) m.leaving = true;
      }
    }
    return [
      for (final m in mentions)
        Mention(m.character.id, m.word, m.position,
            leaving: m.leaving, cameFirst: m.cameFirst, obj: m.obj, address: m.address)
    ];
  }

  /// «…укатился, только медведь его и видел» — медведь смотрит вслед, уходит не он.
  bool _isWitness(List<Token> tokens, int pos) {
    if (pos == 0 || !data.witnessBefore.contains(tokens[pos - 1].word)) return false;
    final after = tokens.sublist(pos + 1, (pos + 4).clamp(0, tokens.length));
    return data.witnessAfter.any((p) => findMatches(p, after).isNotEmpty);
  }

  /// Удобство без движка: кто появился (по миру).
  List<Appearance> process(String text) {
    final mentions = {for (final m in observe(text)) m.characterId: m};
    return [
      for (final c in world.observeCharacters(mentions.values.toList()))
        if (c.kind == 'enter')
          Appearance(
              characters.firstWhere((x) => x.id == c.id), c.word, mentions[c.id]!.position)
    ];
  }
}
