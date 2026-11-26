/// Три звена (D-011): текст → наблюдатели пишут в модель мира → звукорежиссёр.
/// Порт prototype/src/storyfx/engine.py.
library;

import 'actions.dart';
import 'characters.dart';
import 'config.dart';
import 'mixer.dart';
import 'scenes.dart';
import 'speech.dart';
import 'textnorm.dart';
import 'world.dart';

class TextEvent {
  final String text;
  final bool final_;
  final List<bool>? speech; // для текста: какие слова (как в tokenize) — в реплике героя
  const TextEvent(this.text, this.final_, [this.speech]);
}

/// Аудио-выход: реализация — платформа (плеер слоёв/эффектов/музыки).
abstract class AudioOut {
  void playSfx(String sfx);
  void setScene(String? ambience);
  void setOverlays(List<String> ambiences);
  void setMusic(String? music);
  void setMix((double, double, double, double) levels);
}

/// Приёмник событий движка (журнал UI, тесты).
abstract class EngineEvents {
  void onEvent(String kind, String id); // sfx | char | leave | scene | overlay_on | overlay_off | mood
  void onLog(String message);
}

class StoryEngine {
  final ActionMatcher actions;
  final SceneTracker scenes;
  final AudioOut audio;
  final EngineEvents events;
  final bool verbose;
  final double Function() clock;
  final SceneTracker? moods;
  final CharacterTracker? characters;
  final SoundMixer? mixer;
  final WorldState world;
  final SpeechCues? speechCues;
  final Set<String> muted; // выключенные звуки «kind/id» (muted.yaml)
  bool musicOn;

  double _saidIntensity = -1.0;
  double? _lastActionT;
  String _phrase = '';
  String? _lastActionSound;
  final List<(double, String, String)> _pendingVoices = [];
  int _utt = 0;
  double _lastEval = 0;
  final double _t0;

  StoryEngine({
    required this.actions,
    required this.scenes,
    required this.audio,
    required this.events,
    required this.clock,
    this.moods,
    this.characters,
    this.mixer,
    this.speechCues,
    this.muted = const {},
    this.verbose = true,
    this.musicOn = false,
    WorldState? world,
  })  : world = world ?? WorldState(clock: clock),
        _t0 = clock() {
    _lastEval = _t0;
    if (moods != null) {
      this.world.mood = moods!.current;
    }
    if (musicOn) setMusicEnabled(true);
  }

  void _say(String msg) =>
      events.onLog('[${(clock() - _t0).toStringAsFixed(1).padLeft(6)}s] $msg');

  String? get mood => moods == null ? null : (world.mood ?? moods!.current);

  void setMusicEnabled(bool on) {
    musicOn = on && moods != null;
    audio.setMusic(musicOn ? moods!.ambienceFor(mood) : null);
    _say('МУЗЫКА   ${musicOn ? 'вкл: $mood' : 'выкл'}');
  }

  void onText(TextEvent ev) {
    mixer?.onWords(ev.text.split(' ').length, ev.final_);
    _flushVoices();
    _onText(ev);
    if (mixer != null) _mix();
  }

  void _mix() {
    final m = mood;
    if (m != null) mixer!.mood = m;
    final a = mixer!.update();
    audio.setMix(mixer!.levels());
    if ((a - _saidIntensity).abs() >= 0.1) {
      _saidIntensity = a;
      final tempo = mixer!.tempo();
      _say('ЗВУКООПЕРАТОР напряжение ${a.toStringAsFixed(1)} (настроение ${mixer!.mood}'
          '${tempo != null ? ', темп ${tempo.toStringAsFixed(1)} сл/с' : ''})');
    }
  }

  // ---------- звено 2: наблюдатели → мир ----------
  void _onText(TextEvent ev) {
    final w = world;
    for (final d in actions.process(ev.text, _utt, ev.final_)) {
      if (d.sfx != null) {
        _direct([w.action(d.sfx!, '«${d.context}» (${d.group}, ${d.confidence.toStringAsFixed(2)})')]);
      } else if (verbose) {
        _say('  тише   ${d.group.padRight(12)} ← «${d.context}» (${d.note}, ${d.confidence.toStringAsFixed(2)})');
      }
    }

    if (ev.final_) {
      _say('фраза: ${ev.text}');
      if (characters != null) {
        _phrase = ev.text;
        _direct(w.observeCharacters(characters!.observe(ev.text)));
      }
      _observeScene(scenes.addUtterance(ev.text, speech: _speech(ev)));
      if (moods != null) _observeMood(moods!.addUtterance(ev.text));
      _utt += 1;
      _lastEval = clock();
    } else if (clock() - _lastEval >= sceneIntervalS) {
      // длинная речь без пауз: периодически переоцениваем сцену с текущим частичным текстом
      _lastEval = clock();
      final c = scenes.evaluate(ev.text);
      if (c != null) _observeScene([c]);
      if (moods != null) {
        final m = moods!.evaluate(ev.text);
        if (m != null) _observeMood([m]);
      }
    }
  }

  List<bool>? _speech(TextEvent ev) {
    if (ev.speech != null || speechCues == null) return ev.speech;
    final mask = speechCues!.guess(tokenizeWords(ev.text));
    if (verbose && mask.any((m) => m)) {
      final words = tokenizeWords(ev.text);
      _say('  реплика «${[for (var i = 0; i < words.length; i++) if (mask[i]) words[i]].join(' ')}» — место и погоду не меняет');
    }
    return mask;
  }

  void _observeScene(List<Change> changes) {
    final out = <WorldChange>[];
    final weather = <(String, bool, String)>[];
    for (final c in changes) {
      if (c.kind == 'scene') {
        out.addAll(world.setPlace(c.id!, c.reason));
      } else {
        weather.add((c.id!, c.kind == 'overlay_on', c.reason));
      }
    }
    if (weather.isNotEmpty) {
      out.addAll(world.setWeather(scenes.activeOverlays, weather));
    }
    _direct(out);
  }

  void _observeMood(List<Change> changes) {
    for (final c in changes) {
      if (c.kind == 'scene') {
        _direct(world.setMood(c.id!, c.reason));
      }
    }
  }

  // ---------- звено 3: звукорежиссёр ----------
  bool _play(String sfx) {
    if (muted.contains('sfx/$sfx')) return false;
    audio.playSfx(sfx);
    return true;
  }

  String? _ambience(String? amb) =>
      amb != null && muted.contains('ambience/$amb') ? null : amb;

  bool _actionJustSounded() {
    final t = _lastActionT;
    return t != null && clock() - t <= characterAfterActionS;
  }

  void _voice(Character ch, String word, [String note = '']) {
    final played = _play(ch.sound);
    events.onEvent('char', ch.id);
    _say('ПЕРСОНАЖ ${ch.id.padRight(12)} ← «$word» (${ch.sound}${played ? '' : ', звук выключен'}$note)');
  }

  /// Время идёт и без слов: доиграть отложенные голоса, когда рассказчик замолчал.
  void tick() => _flushVoices();

  void _flushVoices() {
    if (_pendingVoices.isEmpty || _actionJustSounded()) return;
    final now = clock();
    final pending = List.of(_pendingVoices);
    _pendingVoices.clear();
    for (final (t, cid, word) in pending) {
      if (now - t > characterDeferMaxS) {
        _say('  тише   персонаж ${cid.padRight(9)} ← «$word» (ждал звука действия слишком долго)');
        continue;
      }
      final ch = characters!.characters.firstWhere((x) => x.id == cid);
      _voice(ch, word, ', после звука действия');
    }
  }

  void _direct(List<WorldChange> changes) {
    var weatherChanged = false;
    for (final c in changes) {
      switch (c.kind) {
        case 'action':
          final played = _play(c.id);
          _lastActionT = clock();
          _lastActionSound = c.id;
          events.onEvent('sfx', c.id);
          _say('ДЕЙСТВИЕ ${c.id.padRight(12)} ← ${c.reason}${played ? '' : ' — звук выключен'}');
        case 'enter':
          final ch = characters!.characters.firstWhere((x) => x.id == c.id);
          if (_actionJustSounded() &&
              ([...ch.voicedBy, ch.sound].contains(_lastActionSound))) {
            // «Морозко на ёлке потрескивает»: треск и был его голосом
            events.onEvent('char', c.id);
            _say('ПЕРСОНАЖ ${c.id.padRight(12)} ← «${c.word}» (голос уже прозвучал: $_lastActionSound)');
            continue;
          }
          if (ch.isQuietIn(_phrase)) {
            _say('  тише   персонаж ${c.id.padRight(9)} ← «${c.word}» (не к месту: слова фразы)');
            continue;
          }
          if (ch.quietMoods.contains(mood)) {
            _say('  тише   персонаж ${c.id.padRight(9)} ← «${c.word}» (не к настроению: $mood)');
            continue;
          }
          if (_actionJustSounded()) {
            // «гном зажёг факел»: звук действия только что был — голос позже (задача 24)
            _pendingVoices.add((clock(), c.id, c.word));
            _say('  позже  персонаж ${c.id.padRight(9)} ← «${c.word}» (сначала звук действия)');
            continue;
          }
          _voice(ch, c.word);
        case 'leave':
          events.onEvent('leave', c.id);
          _say('УШЁЛ     ${c.id.padRight(12)} ← «${c.word}»');
        case 'place':
          audio.setScene(_ambience(scenes.ambienceFor(c.id)));
          events.onEvent('scene', c.id);
          _say('СЦЕНА    ${c.id.padRight(12)} (${c.reason})');
        case 'weather_on' || 'weather_off':
          weatherChanged = true;
          events.onEvent(c.kind == 'weather_on' ? 'overlay_on' : 'overlay_off', c.id);
          _say('${c.kind == 'weather_on' ? '+' : '-'}СЛОЙ    ${c.id.padRight(12)} (${c.reason})');
        case 'mood':
          events.onEvent('mood', c.id);
          _say('НАСТРОЕНИЕ ${c.id.padRight(10)} (${c.reason})${musicOn ? '' : ' — музыка выкл'}');
          if (musicOn) audio.setMusic(moods!.ambienceFor(c.id));
      }
    }
    if (weatherChanged) {
      audio.setOverlays([
        for (final o in world.weather)
          ?_ambience(scenes.overlayAmbience(o))
      ]);
    }
  }
}
