import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:storyfx/main.dart';

void main() {
  testWidgets('приложение стартует с экрана загрузки', (tester) async {
    await tester.pumpWidget(const StoryfxApp());
    expect(find.text('storyfx'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
  });

  testWidgets('после загрузки видна кнопка слуха', (tester) async {
    // движок в виджет-тесте пропускаем (FakeAsync не дружит с rootBundle;
    // сборка движка из assets проверяется в engine_load_test.dart)
    await tester.pumpWidget(const StoryfxApp(debugSkipEngineLoad: true));
    await tester.pump();
    expect(find.text('Слушать'), findsOneWidget);
    expect(find.byIcon(Icons.mic), findsOneWidget);
  });
}
