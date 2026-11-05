"""Пути и настраиваемые константы прототипа."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # папка prototype/
DATA_DIR = ROOT / "data"
SOUNDS_DIR = ROOT / "sounds"
MODELS_DIR = ROOT / "models"

VOSK_MODEL_DIR = MODELS_DIR / "vosk-model-small-ru-0.22"
EMBED_MODEL_NAME = "cointegrated/rubert-tiny2"
HF_CACHE_DIR = MODELS_DIR / "hf"

SAMPLE_RATE = 16000          # Vosk
BLOCK_SECONDS = 0.1          # размер блока звука с микрофона

# Триггеры действий
DEFAULT_COOLDOWN_S = 1.5
MAX_GAP_WORDS = 2            # лишних слов между словами фразы
NEGATION_WINDOW = 2          # слов перед совпадением, где ищем «не»
NEGATIONS = {"не", "нет", "ни", "без"}

# Сцены
SCENE_WINDOW_WORDS = 40      # сколько последних слов анализируем
SCENE_INTERVAL_S = 3.0       # как часто переоценивать сцену на частичных результатах
SCENE_THRESHOLD = 0.30       # минимальная оценка, чтобы сменить сцену
SCENE_MARGIN = 0.03          # насколько новая сцена должна обогнать текущую
SCENE_CONFIRM = 2            # сколько оценок подряд должна выиграть новая сцена
KEYWORD_BONUS = 0.15         # бонус к оценке за ключевое слово сцены в окне
MAX_OVERLAYS = 2             # одновременно активных наложений (дождь, ночь…)

# Звук
CROSSFADE_MS = 2500
VOLUMES = {                  # режим: (фон, наложения, действия)
    "dnd": (0.45, 0.40, 0.90),
    "kids": (0.35, 0.30, 0.60),
}
