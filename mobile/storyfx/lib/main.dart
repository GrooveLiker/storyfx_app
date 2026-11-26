import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'audio_player.dart';
import 'engine/engine.dart';
import 'engine/load.dart';

/// storyfx — живая озвучка рассказа.
/// Слух телефона (системный распознаватель на устройстве, D-018/D-020) → фразы →
/// движок (действия, сцены, персонажи, настроение) → звук (фон, слои, эффекты, музыка).
void main() => runApp(const StoryfxApp());

class StoryfxApp extends StatelessWidget {
  const StoryfxApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'storyfx',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF3A5A8C),
            brightness: Brightness.dark,
          ),
          useMaterial3: true,
        ),
        home: const HearingPage(),
      );
}

class HearingPage extends StatefulWidget {
  const HearingPage({super.key});

  @override
  State<HearingPage> createState() => _HearingPageState();
}

class _HearingPageState extends State<HearingPage> {
  static const _hearing = MethodChannel('app.storyfx/hearing');
  static const _events = EventChannel('app.storyfx/hearing/events');

  StreamSubscription? _sub;
  Timer? _ticker;
  StoryEngine? _engine;
  SoloudAudio? _player;

  bool _running = false;
  String _status = 'стоп';
  String _asrEngine = '—';
  String _partial = '';
  String _scene = '—';
  String _mood = '—';
  final Set<String> _overlays = {};
  final List<String> _phrases = [];
  final List<String> _log = [];

  @override
  void initState() {
    super.initState();
    _sub = _events.receiveBroadcastStream().listen(_onEvent, onError: _onStreamError);
    _loadInfo();
    _loadEngine();
  }

  Future<void> _loadInfo() async {
    try {
      final info = await _hearing.invokeMethod<Map>('info');
      if (info == null) return;
      final onDevice = info['onDevice'] == true;
      _addLog('устройство: ${info['device']}, Android ${info['android']}');
      _addLog(onDevice
          ? 'распознавание на устройстве: доступно'
          : 'распознавание на устройстве: НЕТ (нужен Android 12+)');
      if (info['anyRecognizer'] != true) {
        _addLog('ВНИМАНИЕ: на устройстве нет распознавателя речи');
      }
    } catch (e) {
      _addLog('info: $e');
    }
  }

  Future<void> _loadEngine() async {
    try {
      final player = SoloudAudio(onLog: _addLog);
      await player.init();
      _player = player;
      final engine = await loadEngine(audio: player, events: _UiEvents(this));
      if (!mounted) return;
      setState(() => _engine = engine);
      _addLog('движок и звук готовы (лексический режим)');
    } catch (e, st) {
      _addLog('движок: $e');
      debugPrint('$st');
    }
  }

  void _onEvent(dynamic raw) {
    if (raw is! Map) return;
    final type = raw['type'];
    setState(() {
      switch (type) {
        case 'engine':
          _asrEngine = '${raw['engine']}';
          _addLog('слух: $_asrEngine');
        case 'state':
          _status = '${raw['state']}';
        case 'partial':
          final text = '${raw['text']}';
          _partial = text;
          _engine?.onText(TextEvent(text, false));
        case 'phrase':
          final text = '${raw['text']}';
          if (text.trim().isNotEmpty) {
            _phrases.add(text);
            _partial = '';
            _addLog('фраза: «$text»');
            _engine?.onText(TextEvent(text, true));
          }
        case 'error':
          _addLog('ошибка: ${raw['error']}');
      }
    });
  }

  void _onStreamError(Object e) => _addLog('канал событий: $e');

  Future<void> _toggle() async {
    try {
      if (_running) {
        await _hearing.invokeMethod('stop');
        _ticker?.cancel();
        setState(() {
          _running = false;
          _status = 'стоп';
          _partial = '';
        });
      } else {
        final ok = await _hearing.invokeMethod<bool>('start') ?? false;
        setState(() {
          _running = ok;
          if (ok) {
            _phrases.clear();
            _status = 'слушаю';
          }
        });
        if (ok) {
          // время идёт и без слов: доигрывать отложенные голоса персонажей
          _ticker = Timer.periodic(
              const Duration(milliseconds: 500), (_) => _engine?.tick());
        }
      }
    } catch (e) {
      _addLog('${_running ? "stop" : "start"}: $e');
    }
  }

  void _onEngineEvent(String kind, String id) {
    setState(() {
      switch (kind) {
        case 'scene':
          _scene = id;
        case 'mood':
          _mood = id;
        case 'overlay_on':
          _overlays.add(id);
        case 'overlay_off':
          _overlays.remove(id);
      }
    });
  }

  void _addLog(String line) {
    final t = DateTime.now();
    final ts =
        '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';
    if (mounted) setState(() => _log.add('$ts  $line'));
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _sub?.cancel();
    if (_running) _hearing.invokeMethod('stop');
    _player?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('storyfx'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: Text(_asrEngine, style: theme.textTheme.bodySmall),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                FilledButton.icon(
                  onPressed: _toggle,
                  icon: Icon(_running ? Icons.stop : Icons.mic),
                  label: Text(_running ? 'Стоп' : 'Слушать'),
                  style: FilledButton.styleFrom(
                    backgroundColor:
                        _running ? theme.colorScheme.error : theme.colorScheme.primary,
                    padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                  ),
                ),
                const SizedBox(width: 16),
                Text(_status, style: theme.textTheme.titleMedium),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                'сцена: $_scene · настроение: $_mood'
                '${_overlays.isEmpty ? '' : ' · слои: ${_overlays.join(', ')}'}',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.secondary),
              ),
            ),
          ),
          if (_partial.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('… $_partial',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                      fontStyle: FontStyle.italic,
                    )),
              ),
            ),
          const Divider(),
          Expanded(
            child: _phrases.isEmpty
                ? Center(
                    child: Text(
                      _running ? 'Рассказывайте — фразы появятся здесь' : 'Нажмите «Слушать»',
                      style: theme.textTheme.bodyLarge
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    itemCount: _phrases.length,
                    itemBuilder: (context, i) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Text(_phrases[i], style: theme.textTheme.bodyLarge),
                    ),
                  ),
          ),
          const Divider(),
          SizedBox(
            height: 130,
            child: ListView.builder(
              reverse: true,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              itemCount: _log.length,
              itemBuilder: (context, i) => Text(
                _log[_log.length - 1 - i],
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Приёмник событий движка: статусная строка + журнал движка (он сам пишет по-русски).
class _UiEvents implements EngineEvents {
  final _HearingPageState _page;
  _UiEvents(this._page);

  @override
  void onEvent(String kind, String id) => _page._onEngineEvent(kind, id);

  @override
  void onLog(String message) => _page._addLog(message);
}

