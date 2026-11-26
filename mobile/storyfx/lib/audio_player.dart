/// Плеер звука (звено 3, AudioOut): фон сцены, погодные слои, эффекты, музыка.
/// Кроссфейды и уровни — по config.dart (crossfadeMs / musicCrossfadeMs / микс).
library;

import 'dart:async';

import 'package:flutter_soloud/flutter_soloud.dart';

import 'engine/config.dart';
import 'engine/engine.dart';

class SoloudAudio implements AudioOut {
  final void Function(String message)? onLog;
  final SoLoud _so = SoLoud.instance;

  bool _ready = false;
  Future<void> _queue = Future.value();

  final Map<String, AudioSource> _sources = {};

  // Постоянные голоса: фон сцены, слои погоды, музыка.
  SoundHandle? _scene;
  final Map<String, SoundHandle> _overlays = {};
  SoundHandle? _music;
  String? _sceneId;
  String? _musicId;
  int _generation = 0; // защита от гонок при быстрой смене сцены

  // Уровни микса (фон, слои, действия, музыка) — обновляет setMix.
  var _levels = (mixCalm.$1, mixCalm.$2, mixCalm.$3, mixCalm.$4);
  final Set<SoundHandle> _fading = {};

  SoloudAudio({this.onLog});

  Future<void> init() async {
    await _so.init();
    _ready = true;
  }

  Future<void> dispose() async {
    if (_ready) _so.deinit();
  }

  /// Команды AudioOut синхронные, SoLoud — нет: выстраиваем работу в очередь.
  void _enqueue(Future<void> Function() job) {
    _queue = _queue.then((_) => job()).catchError((Object e) {
      onLog?.call('плеер: $e');
    });
  }

  Future<AudioSource?> _source(String path) async {
    final cached = _sources[path];
    if (cached != null) return cached;
    try {
      final src = await _so.loadAsset(path);
      _sources[path] = src;
      return src;
    } catch (e) {
      onLog?.call('плеер: нет файла $path ($e)');
      return null;
    }
  }

  /// Плавно вывести голос и остановить. Пока идёт фейд, setMix его не трогает.
  void _fadeOutAndStop(SoundHandle h, int ms) {
    _fading.add(h);
    _so.fadeVolume(h, 0, Duration(milliseconds: ms));
    Timer(Duration(milliseconds: ms + 100), () {
      _fading.remove(h);
      if (_ready) _so.stop(h);
    });
  }

  Future<void> _playLoop(String path, double volume, int fadeMs,
      void Function(SoundHandle) assign) async {
    final src = await _source(path);
    if (src == null || !_ready) return;
    final h = _so.play(src, volume: 0, looping: true);
    _fading.add(h);
    assign(h);
    _so.fadeVolume(h, volume, Duration(milliseconds: fadeMs));
    Timer(Duration(milliseconds: fadeMs + 100), () => _fading.remove(h));
  }

  // ---------- AudioOut ----------

  @override
  void playSfx(String sfx) {
    _enqueue(() async {
      if (!_ready) return;
      final src = await _source('assets/sounds/sfx/$sfx.wav');
      if (src == null) return;
      _so.play(src, volume: _levels.$3);
    });
  }

  @override
  void setScene(String? ambience) {
    if (ambience == _sceneId) return;
    _sceneId = ambience;
    final gen = ++_generation;
    _enqueue(() async {
      if (!_ready || gen != _generation) return;
      final old = _scene;
      _scene = null;
      if (old != null) _fadeOutAndStop(old, crossfadeMs);
      if (ambience != null && gen == _generation) {
        await _playLoop('assets/sounds/ambience/$ambience.wav', _levels.$1,
            crossfadeMs, (h) => _scene = h);
      }
    });
  }

  @override
  void setOverlays(List<String> ambiences) {
    final want = ambiences.toSet();
    _enqueue(() async {
      if (!_ready) return;
      // лишние — плавно убрать
      for (final id in _overlays.keys.toList()) {
        if (!want.contains(id)) {
          final h = _overlays.remove(id)!;
          _fadeOutAndStop(h, crossfadeMs);
        }
      }
      // новые — плавно добавить
      for (final id in want) {
        if (_overlays.containsKey(id)) continue;
        await _playLoop('assets/sounds/ambience/$id.wav', _levels.$2,
            crossfadeMs, (h) => _overlays[id] = h);
      }
    });
  }

  @override
  void setMusic(String? music) {
    if (music == _musicId) return;
    _musicId = music;
    final gen = ++_generation;
    _enqueue(() async {
      if (!_ready || gen != _generation) return;
      final old = _music;
      _music = null;
      if (old != null) _fadeOutAndStop(old, musicCrossfadeMs);
      if (music != null && gen == _generation) {
        await _playLoop('assets/sounds/music/$music.wav', _levels.$4,
            musicCrossfadeMs, (h) => _music = h);
      }
    });
  }

  @override
  void setMix((double, double, double, double) levels) {
    _levels = levels;
    if (!_ready) return;
    // Живые голоса перенастраиваем, голоса в фейде не трогаем — доведут сами.
    void set(SoundHandle? h, double v) {
      if (h != null && !_fading.contains(h)) _so.setVolume(h, v);
    }

    set(_scene, levels.$1);
    for (final h in _overlays.values) {
      set(h, levels.$2);
    }
    set(_music, levels.$4);
  }
}
