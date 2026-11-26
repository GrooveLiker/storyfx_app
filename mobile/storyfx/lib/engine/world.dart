/// Модель мира (звено 2, D-011): где мы, погода, кто на сцене, настроение — одно состояние на всех.
/// Порт prototype/src/storyfx/world.py.
library;

import 'dart:collection';

import 'config.dart';

class WorldChange {
  final String kind; // place | weather_on | weather_off | enter | leave | mood | action
  final String id;
  final String reason;
  final String word; // как назвали в тексте (персонажи)
  const WorldChange(this.kind, this.id, [this.reason = '', this.word = '']);
}

class Mention {
  final String characterId;
  final String word;
  final int position;
  final bool leaving;
  final bool cameFirst; // назван в части фразы ДО ухода — сначала появился
  final bool obj;       // после предлога: «я у дедушки ушёл» — дедушка не уходит
  final bool address;   // обращение: «что ты наделал, старый пёс» — не появление
  const Mention(this.characterId, this.word, this.position,
      {this.leaving = false, this.cameFirst = false, this.obj = false, this.address = false});
}

class WorldState {
  final double Function() clock;
  String? place;
  List<String> weather = [];
  String? mood;
  final Map<String, int> present = {}; // персонаж → номер фразы последнего упоминания
  int phrase = 0;
  final Queue<(double, WorldChange)> history = Queue();

  WorldState({required this.clock});

  WorldChange _record(WorldChange ch) {
    history.addLast((clock(), ch));
    if (history.length > 200) history.removeFirst();
    return ch;
  }

  // ---------- место, погода, настроение ----------
  List<WorldChange> setPlace(String place, [String reason = '']) {
    if (place == this.place) return [];
    this.place = place;
    return [_record(WorldChange('place', place, reason))];
  }

  List<WorldChange> setWeather(List<String> active, List<(String, bool, String)> changes) {
    weather = List.of(active);
    return [
      for (final (wid, on, reason) in changes)
        _record(WorldChange(on ? 'weather_on' : 'weather_off', wid, reason))
    ];
  }

  List<WorldChange> setMood(String mood, [String reason = '']) {
    if (mood == this.mood) return [];
    this.mood = mood;
    return [_record(WorldChange('mood', mood, reason))];
  }

  WorldChange action(String sfx, [String reason = '']) =>
      _record(WorldChange('action', sfx, reason));

  // ---------- персонажи ----------
  /// На сцене — пока не ушёл и о нём говорили не больше characterReintroPhrases фраз назад.
  bool isPresent(String cid) {
    final seen = present[cid];
    return seen != null && phrase - seen < characterReintroPhrases;
  }

  List<WorldChange> observeCharacters(List<Mention> mentions) {
    phrase += 1;
    final out = <WorldChange>[];
    var entered = 0;
    final sorted = List.of(mentions)..sort((a, b) => a.position.compareTo(b.position));
    for (final m in sorted) {
      final cid = m.characterId;
      if (m.leaving) {
        if (m.cameFirst && !isPresent(cid) && entered < maxCharactersPerPhrase) {
          out.add(_record(WorldChange('enter', cid, 'появился', m.word)));
          entered += 1;
          present[cid] = phrase;
        }
        if (present.remove(cid) != null) {
          out.add(_record(WorldChange('leave', cid, 'ушёл', m.word)));
        }
        continue;
      }
      if (!isPresent(cid)) {
        if (m.address) continue;
        if (entered >= maxCharactersPerPhrase) continue;
        out.add(_record(WorldChange('enter', cid, 'появился', m.word)));
        entered += 1;
      }
      present[cid] = phrase;
    }
    return out;
  }

  List<String> onStage() => [for (final cid in present.keys) if (isPresent(cid)) cid];

  void reset() {
    place = null;
    weather = [];
    mood = null;
    present.clear();
    phrase = 0;
    history.clear();
  }

  Map<String, dynamic> snapshot() =>
      {'place': place, 'weather': List.of(weather), 'mood': mood, 'on_stage': onStage()};
}
