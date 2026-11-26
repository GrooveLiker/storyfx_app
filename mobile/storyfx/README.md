# storyfx — мобильное приложение (Flutter)

Целевой продукт: приложение слушает рассказчика (ведущий ДнД или родитель со сказкой) и в реальном времени озвучивает рассказ — фон места, голоса персонажей, звуки действий, музыку настроения.

Сейчас (задача 34) — **каркас**: слух телефона → фразы на экране. Движок (модель мира, звукорежиссёр) портируется из прототипа `prototype/` следующими шагами.

## Слух

Системный распознаватель Android в режиме «на устройстве» (D-018, D-020): Kotlin-код в `android/.../MainActivity.kt` перенесён из проверенного `mobile/asr_check` v0.3 (прогоны 2026-11-26, разбор `docs/review-2026-11-26-phone.md`):

- распознаватель создаётся один раз на сеанс (пересоздание рвёт сервис);
- один таймер перезапуска, отмена на живой сессии, backoff на разрывах;
- on-device подтверждён авиарежим-тестом (D-001: голос не покидает устройство).

Связь Dart ↔ Kotlin: `MethodChannel app.storyfx/hearing` (start/stop/info) + `EventChannel app.storyfx/hearing/events` (state/partial/phrase/error/engine).

## Сборка

```
flutter build apk --debug
```

Окружение на этой машине: Flutter SDK `C:\flutter`, Android SDK `C:\Android\Sdk`, JDK — изолированный Temurin 21 в `~/.android-app-building/toolchain/jdk-21` (для сборки задавать `ANDROID_HOME` и `JAVA_HOME`; JBR Android Studio не работает — см. README `mobile/asr_check`).

APK: `build/app/outputs/flutter-apk/app-debug.apk`.
