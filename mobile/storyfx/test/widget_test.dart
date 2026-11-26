import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:storyfx/main.dart';

void main() {
  testWidgets('приложение стартует и показывает кнопку слуха', (tester) async {
    await tester.pumpWidget(const StoryfxApp());
    expect(find.text('storyfx'), findsOneWidget);
    expect(find.text('Слушать'), findsOneWidget);
    expect(find.byIcon(Icons.mic), findsOneWidget);
  });
}
