package app.storyfx.storyfx

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executor

/**
 * Слух storyfx на телефоне (D-018, D-020): системный распознаватель в режиме
 * «на устройстве». Поведение перенесено из mobile/asr_check v0.3 (прогоны 2026-11-26):
 * один распознаватель на весь сеанс, один таймер перезапуска, BUSY/CLIENT на живой
 * сессии не перезапускают, backoff 1000 мс на разрывах сервиса.
 *
 * Dart <-> Kotlin:
 *  - MethodChannel app.storyfx/hearing: start(), stop(), info()
 *  - EventChannel  app.storyfx/hearing/events: {type, ...} —
 *    state (слушаю/готов/речь началась/речь кончилась/стоп), partial, phrase, error, engine.
 */
class MainActivity : FlutterActivity() {

    private val handler = Handler(Looper.getMainLooper())
    private val mainExecutor = Executor { command -> handler.post(command) }

    private var recognizer: SpeechRecognizer? = null
    private var running = false
    private var wantStart = false
    private var sessionLive = false  // живая сессия: BUSY/CLIENT на ней не перезапускаем
    private var events: EventChannel.EventSink? = null
    private var pendingResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "app.storyfx/hearing")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "start" -> {
                        if (running) { result.success(true); return@setMethodCallHandler }
                        if (ensureMicPermission()) { startSession(); result.success(true) }
                        else { wantStart = true; pendingResult = result }
                    }
                    "stop" -> { stopSession(); result.success(true) }
                    "info" -> result.success(deviceInfo())
                    else -> result.notImplemented()
                }
            }

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, "app.storyfx/hearing/events")
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, sink: EventChannel.EventSink) { events = sink }
                override fun onCancel(arguments: Any?) { events = null }
            })
    }

    private fun deviceInfo(): Map<String, Any> {
        val onDevice = Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this)
        return mapOf(
            "device" to "${Build.MANUFACTURER} ${Build.MODEL}",
            "android" to "${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
            "onDevice" to onDevice,
            "anyRecognizer" to SpeechRecognizer.isRecognitionAvailable(this),
        )
    }

    // ---------- сеанс ----------

    private fun startSession() {
        running = true
        ensureRecognizer()  // распознаватель создаётся один раз — пересоздание рвёт сервис (прогон 2026-11-26)
        listen()
    }

    private fun stopSession() {
        running = false
        handler.removeCallbacks(restartRunnable)
        try { recognizer?.stopListening() } catch (_: Exception) {}
        emit(mapOf("type" to "state", "state" to "стоп"))
    }

    private fun ensureRecognizer() {
        if (recognizer != null) return
        recognizer = if (Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this)) {
            emit(mapOf("type" to "engine", "engine" to "на устройстве"))
            SpeechRecognizer.createOnDeviceSpeechRecognizer(this)
        } else {
            emit(mapOf("type" to "engine", "engine" to "системный по умолчанию — может уходить в облако"))
            SpeechRecognizer.createSpeechRecognizer(this)
        }
        recognizer?.setRecognitionListener(listener)
    }

    private fun recognizerIntent(): Intent =
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, packageName)
            putExtra(RecognizerIntent.EXTRA_MASK_OFFENSIVE_WORDS, false)
            // рассказ — длинная речь; просим не рвать на коротких паузах (подсказки, система может игнорировать)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 30000L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L)
        }

    private fun listen() {
        try {
            recognizer?.startListening(recognizerIntent())
            emit(mapOf("type" to "state", "state" to "слушаю"))
        } catch (e: Exception) {
            emit(mapOf("type" to "error", "error" to "startListening: ${e.message}"))
            scheduleRestart()
        }
    }

    private val restartRunnable = Runnable { if (running) listen() }

    private fun scheduleRestart(delayMs: Long = 300) {
        if (!running) return
        handler.removeCallbacks(restartRunnable)  // один таймер — иначе гонка и параллельные сессии
        handler.postDelayed(restartRunnable, delayMs)
    }

    private val listener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {
            if (!running) return
            sessionLive = true
            handler.removeCallbacks(restartRunnable)
            emit(mapOf("type" to "state", "state" to "готов"))
        }

        override fun onBeginningOfSpeech() {
            if (!running) return
            handler.removeCallbacks(restartRunnable)
            emit(mapOf("type" to "state", "state" to "речь"))
        }

        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}

        override fun onEndOfSpeech() {
            if (!running) return
            emit(mapOf("type" to "state", "state" to "тишина"))
        }

        override fun onError(error: Int) {
            if (!running) return
            emit(mapOf("type" to "error", "error" to errorName(error)))
            when (error) {
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY,
                SpeechRecognizer.ERROR_CLIENT -> {
                    if (!sessionLive) scheduleRestart(1000)
                }
                SpeechRecognizer.ERROR_SERVER_DISCONNECTED,
                SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> {
                    sessionLive = false
                    scheduleRestart(1000)
                }
                else -> {
                    sessionLive = false
                    scheduleRestart(300)
                }
            }
        }

        override fun onPartialResults(partialResults: Bundle?) {
            if (!running) return
            val text = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
            if (text.isBlank()) return
            emit(mapOf("type" to "partial", "text" to text))
        }

        override fun onResults(results: Bundle?) {
            if (!running) return
            sessionLive = false
            val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
            if (text.isNotBlank()) {
                emit(mapOf("type" to "phrase", "text" to text, "t" to System.currentTimeMillis()))
            }
            scheduleRestart()
        }

        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    private fun emit(event: Map<String, Any>) {
        handler.post { events?.success(event) }
    }

    private fun errorName(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_AUDIO -> "AUDIO"
        SpeechRecognizer.ERROR_CLIENT -> "CLIENT"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "INSUFFICIENT_PERMISSIONS"
        SpeechRecognizer.ERROR_NETWORK -> "NETWORK"
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "NETWORK_TIMEOUT"
        SpeechRecognizer.ERROR_NO_MATCH -> "NO_MATCH"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "BUSY"
        SpeechRecognizer.ERROR_SERVER -> "SERVER"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "SPEECH_TIMEOUT"
        SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> "TOO_MANY_REQUESTS"
        SpeechRecognizer.ERROR_SERVER_DISCONNECTED -> "SERVER_DISCONNECTED"
        SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED -> "LANGUAGE_NOT_SUPPORTED"
        SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE -> "LANGUAGE_UNAVAILABLE"
        SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT -> "CANNOT_CHECK_SUPPORT"
        else -> "#$code"
    }

    // ---------- разрешение на микрофон ----------

    private fun ensureMicPermission(): Boolean {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) return true
        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        return false
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1) {
            val granted = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
            if (granted && wantStart) {
                wantStart = false
                startSession()
            }
            pendingResult?.let { it.success(granted); pendingResult = null }
            if (!granted) emit(mapOf("type" to "error", "error" to "нет разрешения на микрофон"))
        }
    }

    override fun onDestroy() {
        running = false
        handler.removeCallbacks(restartRunnable)
        recognizer?.destroy()
        recognizer = null
        super.onDestroy()
    }
}
