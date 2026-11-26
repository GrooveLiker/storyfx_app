package app.storyfx.asrcheck

/** Доля неверно распознанных слов (WER) с разбором замен — эталон против услышанного. */
object Wer {

    data class Result(
        val wer: Double,          // (замены + пропуски + лишние) / слова эталона
        val subs: Int,
        val dels: Int,
        val ins: Int,
        val refWords: Int,
        val hypWords: Int,
        val confusions: List<Pair<String, Int>>,  // "эталон→услышано", сколько раз
    )

    fun words(text: String): List<String> =
        text.lowercase()
            .replace('ё', 'е')
            .replace(Regex("[^0-9a-zа-я\\s-]"), " ")
            .split(Regex("\\s+"))
            .filter { it.isNotBlank() }
            .flatMap { token ->
                // «тридцать» эталона против «30» распознавателя — разворачиваем цифры в слова (прогон 2026-11-26)
                if (token.matches(Regex("\\d{1,3}"))) numberToWords(token.toInt()) else listOf(token)
            }

    private val UNITS = listOf("ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
    private val TEENS = listOf("десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
        "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать")
    private val TENS = listOf("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
        "семьдесят", "восемьдесят", "девяносто")
    private val HUNDREDS = listOf("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
        "семьсот", "восемьсот", "девятьсот")

    private fun numberToWords(n: Int): List<String> = when {
        n < 10 -> listOf(UNITS[n])
        n < 20 -> listOf(TEENS[n - 10])
        n < 100 -> if (n % 10 == 0) listOf(TENS[n / 10]) else listOf(TENS[n / 10], UNITS[n % 10])
        else -> if (n % 100 == 0) listOf(HUNDREDS[n / 100])
                else listOf(HUNDREDS[n / 100]) + numberToWords(n % 100)
    }

    fun compute(refText: String, hypText: String): Result {
        val ref = words(refText)
        val hyp = words(hypText)
        val n = ref.size
        val m = hyp.size

        // d[i][j] — расстояние ref[0..i) к hyp[0..j); back[i][j]: 0 совпало, 1 замена, 2 пропуск, 3 лишнее
        val d = Array(n + 1) { IntArray(m + 1) }
        val back = Array(n + 1) { IntArray(m + 1) }
        for (i in 0..n) { d[i][0] = i; back[i][0] = 2 }
        for (j in 0..m) { d[0][j] = j; back[0][j] = 3 }
        for (i in 1..n) {
            for (j in 1..m) {
                if (ref[i - 1] == hyp[j - 1]) {
                    d[i][j] = d[i - 1][j - 1]; back[i][j] = 0
                } else {
                    val sub = d[i - 1][j - 1] + 1
                    val del = d[i - 1][j] + 1
                    val ins = d[i][j - 1] + 1
                    when {
                        sub <= del && sub <= ins -> { d[i][j] = sub; back[i][j] = 1 }
                        del <= ins -> { d[i][j] = del; back[i][j] = 2 }
                        else -> { d[i][j] = ins; back[i][j] = 3 }
                    }
                }
            }
        }

        var subs = 0; var dels = 0; var ins = 0
        val pairs = HashMap<String, Int>()
        var i = n; var j = m
        while (i > 0 || j > 0) {
            when (back[i][j]) {
                0 -> { i--; j-- }
                1 -> {
                    subs++
                    val key = "${ref[i - 1]}→${hyp[j - 1]}"
                    pairs[key] = (pairs[key] ?: 0) + 1
                    i--; j--
                }
                2 -> { dels++; i-- }
                else -> { ins++; j-- }
            }
        }
        val wer = if (n > 0) (subs + dels + ins).toDouble() / n else 0.0
        val confusions = pairs.entries.sortedByDescending { it.value }.take(12).map { it.key to it.value }
        return Result(wer, subs, dels, ins, n, m, confusions)
    }
}
