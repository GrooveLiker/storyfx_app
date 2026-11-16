# Полная проверка прототипа, 3 уровня по порядку. Зелёный вывод = задачу можно отмечать passing.
# Запуск из папки prototype:  ./verify.ps1   (сначала один раз ./init.ps1)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python.exe"

Write-Host "== 1/3 Статика: компиляция и загрузка данных"
& $py -m compileall -q src tools tests
if ($LASTEXITCODE -ne 0) { throw "ошибка компиляции" }
& $py -c "from storyfx.actions import load_actions; from storyfx.scenes import load_scenes; from storyfx.mood import load_moods; from storyfx.characters import load_characters; from storyfx.speech import load_speech_cues; sp=load_speech_cues(); a=load_actions(); s,o=load_scenes(); m,_=load_moods(); c=load_characters(); print(f'  тем действий: {len(a)}, звуков действий: {sum(len(g.sounds) for g in a)}, сцен: {len(s)}, наложений: {len(o)}, настроений музыки: {len(m)}, персонажей: {len(c)}, признаков реплики: {len(sp.pronouns)+len(sp.first_person)+len(sp.imperatives)}')"
if ($LASTEXITCODE -ne 0) { throw "ошибка в data/*.yaml" }

Write-Host "== 2/3 Поведение: быстрые тесты"
& $py -m pytest -m "not slow" -q
if ($LASTEXITCODE -ne 0) { throw "быстрые тесты не прошли" }

Write-Host "== 3/3 Сквозная: TTS-WAV -> Vosk -> события, модель смысла"
& $py -m pytest -m slow -q
if ($LASTEXITCODE -ne 0) { throw "сквозные тесты не прошли" }

Write-Host ""
Write-Host "ВСЁ ЗЕЛЁНОЕ. Не забудьте ручную проверку с микрофоном (PROGRESS.md, задача 7)."
