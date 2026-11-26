/// Сборка движка из assets (как на телефоне): все YAML, все звенья.
/// Реальный event loop — в testWidgets (FakeAsync) rootBundle зависает.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:storyfx/engine/engine.dart';
import 'package:storyfx/engine/load.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('loadEngine собирает движок из assets (лексический режим)', () async {
    final events = _E();
    final engine = await loadEngine(audio: _A(), events: events);
    expect(engine.mood, 'calm');
    // движок живой: фраза про лес переключает сцену
    engine.onText(const TextEvent('отряд вошёл в густой лес', true));
    expect(events.list, contains(('scene', 'forest')));
  });
}

class _A implements AudioOut {
  @override
  void playSfx(String id) {}
  @override
  void setScene(String? a) {}
  @override
  void setOverlays(List<String> a) {}
  @override
  void setMusic(String? m) {}
  @override
  void setMix((double, double, double, double) l) {}
}

class _E implements EngineEvents {
  final List<(String, String)> list = [];
  @override
  void onEvent(String kind, String id) => list.add((kind, id));
  @override
  void onLog(String m) {}
}
