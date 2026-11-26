package app.storyfx.asrcheck

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.View
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executor

/**
 * Проверка слуха storyfx на телефоне (D-018, D-020): системный распознаватель
 * в режиме «на устройстве». Меряет:
 *  1) доступен ли on-device режим и русский пакет;
 *  2) непрерывность: распознаватель останавливается на паузах — перезапускаем,
 *     считаем перезапуски (на стыках могут теряться слова, на части телефонов звучит сигнал);
 *  3) задержки: начало речи → первый частичный результат; конец речи → итоговая фраза
 *     (для D-011 звук должен успевать за ~1 с);
 *  4) точность: читаете вслух выбранную сказку — WER против эталонного текста.
 *  Весь сеанс пишется в журнал, «Экспорт» кладёт его в Загрузки.
 */
class MainActivity : Activity() {

    private lateinit var statusText: TextView
    private lateinit var referenceText: TextView
    private lateinit var partialText: TextView
    private lateinit var statsText: TextView
    private lateinit var logText: TextView
    private lateinit var logScroll: ScrollView
    private lateinit var btnToggle: Button
    private lateinit var storySpinner: Spinner

    private val handler = Handler(Looper.getMainLooper())
    private val mainExecutor = Executor { command -> handler.post(command) }
    private val timeFmt = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)

    private var recognizer: SpeechRecognizer? = null
    private var running = false
    private var wantStart = false
    private var engine = "—"
    private var restarts = 0
    private var phrases = 0
    private var noMatch = 0          // сколько раз распознаватель не смог разобрать речь (фраза потеряна целиком)

    private var tSpeechStart = 0L
    private var tSpeechEnd = 0L
    private var gotPartial = false
    private var endLogged = false    // Xiaomi шлёт onEndOfSpeech дважды — пишем один раз (живой прогон 2026-11-26)
    private var sessionLive = false  // живая сессия слушания: ошибки BUSY/CLIENT на ней не перезапускаем (шторм 626 перезапусков, прогон 2026-11-26)
    private val firstPartialLat = ArrayList<Long>()
    private val finalLat = ArrayList<Long>()

    private val hypothesis = StringBuilder()
    private val sessionLog = StringBuilder()

    private var stories = listOf<Pair<String, String>>()   // название → текст
    private var reference = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        referenceText = findViewById(R.id.referenceText)
        partialText = findViewById(R.id.partialText)
        statsText = findViewById(R.id.statsText)
        logText = findViewById(R.id.logText)
        logScroll = findViewById(R.id.logScroll)
        btnToggle = findViewById(R.id.btnToggle)
        storySpinner = findViewById(R.id.storySpinner)

        stories = loadStories()
        storySpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, stories.map { it.first })
        storySpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                reference = stories[position].second
                referenceText.text = if (reference.isBlank()) "Свободный рассказ: эталона нет, WER не считается." else reference
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        btnToggle.setOnClickListener {
            if (running) stopSession() else {
                if (ensureMicPermission()) startSession() else wantStart = true
            }
        }
        findViewById<Button>(R.id.btnSupport).setOnClickListener { checkRussianSupport() }
        findViewById<Button>(R.id.btnExport).setOnClickListener { exportLog() }

        log("устройство: ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        val onDevice = Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this)
        log(if (onDevice) "распознавание на устройстве: доступно"
            else "распознавание на устройстве: НЕТ (нужен Android 12+ со свежими сервисами)")
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            log("ВНИМАНИЕ: на устройстве вообще нет распознавателя речи")
        }
        updateStatus()
        updateStats()
    }

    override fun onDestroy() {
        running = false
        recognizer?.destroy()
        recognizer = null
        super.onDestroy()
    }

    // ---------- сеанс ----------

    private fun startSession() {
        running = true
        restarts = 0
        phrases = 0
        noMatch = 0
        hypothesis.setLength(0)
        firstPartialLat.clear()
        finalLat.clear()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        btnToggle.text = "Стоп"

        ensureRecognizer()   // распознаватель создаётся один раз — пересоздание рвёт сервис (SERVER_DISCONNECTED, прогон 2026-11-26)
        log("старт сеанса, слух: $engine")
        listen()
        updateStatus()
    }

    private fun stopSession() {
        running = false
        try { recognizer?.stopListening() } catch (_: Exception) {}
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        btnToggle.text = "Старт"
        partialText.text = ""
        log("стоп сеанса")
        log("итог: фраз $phrases, перезапусков $restarts, NO_MATCH $noMatch; " +
            "речь→первый частичный ${fmtMs(median(firstPartialLat))}, " +
            "конец речи→фраза ${fmtMs(median(finalLat))} (макс ${fmtMs(finalLat.maxOrNull())})")
        reportWer()
        updateStatus()
        updateStats()
    }

    private fun ensureRecognizer() {
        if (recognizer == null) createRecognizer()
    }

    private fun createRecognizer() {
        recognizer?.destroy()
        recognizer = if (Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this)) {
            engine = "на устройстве (on-device)"
            SpeechRecognizer.createOnDeviceSpeechRecognizer(this)
        } else {
            engine = "системный по умолчанию — ВНИМАНИЕ: может уходить в облако"
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
            log("слушаю…")
        } catch (e: Exception) {
            log("startListening: ${e.message}")
            scheduleRestart()
        }
    }

    private val restartRunnable = Runnable { if (running) listen() }

    private fun scheduleRestart(delayMs: Long = 300) {
        if (!running) return
        restarts++
        updateStatus()
        handler.removeCallbacks(restartRunnable)   // один таймер перезапуска — иначе гонка и параллельные сессии (прогон 2026-11-26)
        handler.postDelayed(restartRunnable, delayMs)
    }

    private val listener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {
            if (!running) return
            sessionLive = true
            handler.removeCallbacks(restartRunnable)   // сессия жива — отложенный перезапуск не нужен
            log("готов к речи")
        }

        override fun onBeginningOfSpeech() {
            if (!running) return
            handler.removeCallbacks(restartRunnable)
            tSpeechStart = System.currentTimeMillis()
            gotPartial = false
            endLogged = false
            log("речь началась")
        }

        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}

        override fun onEndOfSpeech() {
            if (!running) return
            tSpeechEnd = System.currentTimeMillis()
            if (!endLogged) {
                endLogged = true
                log("речь кончилась")
            }
        }

        override fun onError(error: Int) {
            if (!running) return
            if (error == SpeechRecognizer.ERROR_NO_MATCH) noMatch++
            log("ошибка: ${errorName(error)}")
            when (error) {
                // на живой сессии BUSY/CLIENT — это наши же гоночные startListening; перезапускать не надо
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY,
                SpeechRecognizer.ERROR_CLIENT -> {
                    if (!sessionLive) scheduleRestart(1000)
                    else log("— сессия жива, не перезапускаю")
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
            if (!gotPartial && tSpeechStart > 0) {
                gotPartial = true
                firstPartialLat.add(System.currentTimeMillis() - tSpeechStart)
            }
            partialText.text = "… $text"
        }

        override fun onResults(results: Bundle?) {
            if (!running) return
            sessionLive = false
            val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
            if (text.isNotBlank()) {
                val now = System.currentTimeMillis()
                if (tSpeechEnd >= tSpeechStart && tSpeechEnd > 0) finalLat.add(now - tSpeechEnd)
                phrases++
                hypothesis.append(' ').append(text)
                log("фраза: «$text»")
                partialText.text = ""
                updateStats()
            }
            scheduleRestart()
        }

        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    // ---------- диагностика русского на устройстве ----------

    @SuppressLint("NewApi")
    private fun checkRussianSupport() {
        if (Build.VERSION.SDK_INT < 33) {
            log("проверка языкового пакета — только Android 13+; у вас API ${Build.VERSION.SDK_INT}")
            return
        }
        // распознаватель создаём по требованию один раз — кнопка работает и до «Старта» (живой прогон 2026-11-26)
        ensureRecognizer()
        val r = recognizer!!
        val intent = recognizerIntent().apply {
            putExtra(RecognizerIntent.EXTRA_SUPPORTED_LANGUAGES, arrayListOf("ru-RU"))
        }
        r.checkRecognitionSupport(intent, mainExecutor, object : android.speech.RecognitionSupportCallback {
            override fun onSupportResult(support: android.speech.RecognitionSupport) {
                val onDevice = support.supportedOnDeviceLanguages
                log("языки с распознаванием на устройстве: $onDevice")
                if (!onDevice.contains("ru-RU")) {
                    log("русского пакета на устройстве НЕТ — скачать: Настройки → Система → Языки → Распознавание речи (или голосовой ввод клавиатуры)")
                }
            }
            override fun onError(error: Int) {
                log("проверка поддержки: ошибка ${errorName(error)}")
            }
        })
    }

    // ---------- отчёты ----------

    private fun reportWer() {
        if (reference.isBlank() || hypothesis.isBlank()) return
        val r = Wer.compute(reference, hypothesis.toString())
        val line = "WER: %.1f%% — эталон %d слов, услышано %d; замен %d, пропусков %d, лишних %d"
            .format(Locale.US, r.wer * 100, r.refWords, r.hypWords, r.subs, r.dels, r.ins)
        log(line)
        if (r.confusions.isNotEmpty()) {
            log("частые путаницы: " + r.confusions.joinToString(", ") { (k, v) -> "$k ×$v" })
        }
    }

    private fun updateStatus() {
        statusText.text = "слух: $engine   |   " + (if (running) "СЛУШАЮ" else "стоп") + "   |   перезапусков: $restarts"
    }

    private fun updateStats() {
        val medFirst = median(firstPartialLat)
        val medFinal = median(finalLat)
        val maxFinal = finalLat.maxOrNull()
        statsText.text = "фраз: $phrases   |   речь→первый частичный: ${fmtMs(medFirst)}   |   конец речи→фраза: ${fmtMs(medFinal)} (макс ${fmtMs(maxFinal)})"
    }

    private fun median(xs: List<Long>): Long? =
        if (xs.isEmpty()) null else xs.sorted()[xs.size / 2]

    private fun fmtMs(v: Long?): String = v?.let { "${it} мс" } ?: "—"

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

    // ---------- журнал ----------

    private fun log(msg: String) {
        val line = timeFmt.format(Date()) + "  " + msg
        sessionLog.append(line).append('\n')
        logText.append(line + "\n")
        logScroll.post { logScroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun exportLog() {
        val name = "asr_check_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date()) + ".log"
        val content = sessionLog.toString()
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, "text/plain")
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: error("MediaStore вернул null")
                contentResolver.openOutputStream(uri)!!.use { it.write(content.toByteArray(Charsets.UTF_8)) }
                toast("Журнал сохранён: Загрузки/$name")
            } else {
                val dir = getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)
                val f = java.io.File(dir, name)
                f.writeText(content)
                toast("Журнал: ${f.absolutePath}")
            }
            log("экспорт → $name")
        } catch (e: Exception) {
            toast("Не удалось сохранить журнал: ${e.message}")
            log("экспорт не удался: ${e.message}")
        }
    }

    // ---------- данные и разрешение ----------

    private fun loadStories(): List<Pair<String, String>> {
        val list = mutableListOf("Свободный рассказ" to "")
        assets.list("stories")?.sorted()?.forEach { name ->
            val text = assets.open("stories/$name").bufferedReader().use { it.readText() }
            list.add(name.removeSuffix(".txt") to text)
        }
        return list
    }

    private fun ensureMicPermission(): Boolean {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) return true
        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        return false
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            if (wantStart) { wantStart = false; startSession() }
        } else {
            toast("Без микрофона проверка невозможна")
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
}
