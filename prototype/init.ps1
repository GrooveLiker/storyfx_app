# Установка окружения прототипа с нуля + быстрая проверка.
# Запуск из папки prototype:  ./init.ps1
# Повторный запуск безопасен: уже сделанные шаги пропускаются.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python.exe"

Write-Host "1/6 Виртуальное окружение (.venv)"
if (-not (Test-Path $py)) { python -m venv .venv }

Write-Host "2/6 Зависимости (requirements.txt)"
& $py -m pip install --upgrade pip -q
& $py -m pip install -r requirements.txt -q
& $py -m pip install -e . --no-deps -q

Write-Host "3/6 Модель распознавания Vosk (русская, ~45 МБ)"
$vosk = "models\vosk-model-small-ru-0.22"
if (-not (Test-Path $vosk)) {
    New-Item -ItemType Directory -Force models | Out-Null
    Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip" -OutFile models\vosk-ru.zip
    Expand-Archive models\vosk-ru.zip -DestinationPath models
    Remove-Item models\vosk-ru.zip
}

Write-Host "4/6 Модель смысла rubert-tiny2 (~120 МБ, Hugging Face)"
& $py -c "from storyfx.scenes import RuBertEmbedder; RuBertEmbedder(); print('  ok')"

Write-Host "5/6 Звуки: выбранные с Freesound (если есть ключ), остальное — заглушки; тестовые WAV"
if ((Test-Path sounds\chosen.yaml) -and ((Test-Path .freesound_key) -or $env:FREESOUND_API_KEY)) {
    & $py tools\fetch_freesound.py --chosen
} elseif (Test-Path sounds\chosen.yaml) {
    Write-Host "  нет ключа Freesound — вместо настоящих звуков будут заглушки (docs/sounds.md)"
}
& $py tools\gen_sounds.py
& $py tools\gen_music.py
& $py tools\make_test_wavs.py --stories   # и сказки — для прогона голосом (tests/test_stories.py)

Write-Host "6/6 Быстрые тесты"
& $py -m pytest -m "not slow" -q
if ($LASTEXITCODE -ne 0) { throw "быстрые тесты не прошли" }

Write-Host ""
Write-Host "Готово. Полная проверка: ./verify.ps1"
Write-Host "Запуск с микрофоном:     .\.venv\Scripts\python -m storyfx"
