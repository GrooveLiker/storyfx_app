"""Схемы архитектуры StoryFX → PNG рядом с этим файлом (docs/img).
Запуск: python docs/img/make_diagrams.py  (нужен matplotlib; шрифт Segoe UI — Windows).
Схемы используются в docs/solution.md и docs/StoryFX-architecture.docx."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.family"] = "Segoe UI"

FS = 1.3   # масштаб шрифтов: схемы вставляются в документ уменьшенными
INK = "#1F2933"
MUTED = "#5B6670"
C = {   # заливка, обводка
    "ear":   ("#E3EEFC", "#2F6FC9"),
    "world": ("#E3F4E8", "#2E8B4E"),
    "dir":   ("#FDEEDD", "#C8741E"),
    "data":  ("#EFE8FA", "#7652B8"),
    "dev":   ("#F2F3F5", "#8A939C"),
    "person": ("#FFFFFF", "#1F2933"),
    "warn":  ("#FDE8E8", "#C0392B"),
}


def canvas(w, h):
    fig = plt.figure(figsize=(w / 10, h / 10), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, title, sub=None, kind="world", dashed=False, size=11, round_=1.2, bold=True):
    face, edge = C[kind]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={round_}",
                                fc=face, ec=edge, lw=1.6, ls=(0, (4, 3)) if dashed else "-"))
    cx = x + w / 2
    if sub:
        ax.text(cx, y + h * 0.64, title, ha="center", va="center", fontsize=FS*size, color=INK,
                weight="bold" if bold else "normal")
        ax.text(cx, y + h * 0.30, sub, ha="center", va="center", fontsize=FS*size - 2.5, color=MUTED,
                linespacing=1.25)
    else:
        ax.text(cx, y + h / 2, title, ha="center", va="center", fontsize=FS*size, color=INK,
                weight="bold" if bold else "normal", linespacing=1.25)
    return (x, y, w, h)


def frame(ax, x, y, w, h, label, kind, dashed=False):
    face, edge = C[kind]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=2",
                                fc=face, ec=edge, lw=1.2, alpha=0.45, ls=(0, (5, 4)) if dashed else "-"))
    ax.text(x + 1.5, y + h - 1.6, label, ha="left", va="top", fontsize=FS*10.5, color=edge, weight="bold")


def arrow(ax, p, q, label=None, dashed=False, color=INK, lw=1.5, rad=0.0, lpos=0.5, loff=(0, 1.3), lsize=8.5):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=13, lw=lw, color=color,
                                 ls=(0, (4, 3)) if dashed else "-", connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=2, shrinkB=2))
    if label:
        mx = p[0] + (q[0] - p[0]) * lpos + loff[0]
        my = p[1] + (q[1] - p[1]) * lpos + loff[1]
        ax.text(mx, my, label, ha="center", va="center", fontsize=FS*lsize, color=MUTED,
                bbox=dict(fc="white", ec="none", pad=1.2, alpha=0.9))


def title(ax, w, h, text):
    ax.text(2, h - 2, text, ha="left", va="top", fontsize=FS*14, color=INK, weight="bold")


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, facecolor="white")
    plt.close(fig)


# ---------- 1. Общая схема ----------
def overview():
    W, H = 160, 74
    fig, ax = canvas(W, H)
    title(ax, W, H, "StoryFX — общая схема")
    box(ax, 3, 36, 18, 11, "Рассказчик", "говорит вслух", "person")
    frame(ax, 27, 22, 106, 45, "УСТРОЙСТВО — всё локально, без облака", "dev")
    b1 = box(ax, 31, 38, 26, 15, "1 · Слух", "Vosk: речь → текст\n(слова каждые ~0,2 с)", "ear")
    b2 = box(ax, 67, 38, 26, 15, "2 · Модель мира", "где мы, кто здесь,\nчто случилось, настроение", "world")
    b3 = box(ax, 103, 38, 26, 15, "3 · Звукорежиссёр", "что, когда и\nкак громко звучит", "dir")
    box(ax, 55, 25, 52, 9, "Данные: YAML (слова, сцены, персонажи) · звуки WAV · модели", None, "data", size=9.5, bold=False)
    box(ax, 139, 36, 18, 11, "Колонки", "фон · голоса ·\nдействия · музыка", "person")
    arrow(ax, (21, 41.5), (31, 45.5), "голос")
    arrow(ax, (57, 45.5), (67, 45.5), "текст")
    arrow(ax, (93, 45.5), (103, 45.5), "изменения")
    arrow(ax, (129, 45.5), (139, 41.5), "звук")
    arrow(ax, (81, 34), (80, 38), color=C["data"][1])
    arrow(ax, (100, 34), (114, 38), color=C["data"][1])
    frame(ax, 27, 2, 106, 16, "ТОЛЬКО ПРИ РАЗРАБОТКЕ", "dev", dashed=True)
    box(ax, 31, 4, 30, 9, "Freesound (CC0)", "звуки с понятной лицензией", "dev", dashed=True, size=10)
    box(ax, 66, 4, 30, 9, "Каталог звуков", "послушать · выбрать · выключить", "dev", dashed=True, size=10)
    box(ax, 101, 4, 30, 9, "Облачная модель", "сгенерировать примеры фраз", "dev", dashed=True, size=10)
    arrow(ax, (61, 8.5), (66, 8.5), dashed=True, color=MUTED)
    arrow(ax, (81, 13), (75, 25), dashed=True, color=MUTED)
    arrow(ax, (116, 13), (95, 25), dashed=True, color=MUTED)
    save(fig, "1_overview.png")


# ---------- 2. Конвейер ----------
def pipeline():
    W, H = 160, 95
    fig, ax = canvas(W, H)
    title(ax, W, H, "Конвейер реального времени: три звена")
    # Слух
    frame(ax, 3, 66, 154, 22, "ЗВЕНО 1 · СЛУХ", "ear")
    box(ax, 8, 70, 30, 11, "Микрофон / WAV / текст", None, "ear", size=10)
    box(ax, 50, 70, 52, 11, "asr.py · Vosk", "черновик фразы ~5 раз в с · итог фразы на паузе", "ear")
    arrow(ax, (38, 75.5), (50, 75.5))
    # Мир
    frame(ax, 3, 30, 154, 33, "ЗВЕНО 2 · МОДЕЛЬ МИРА", "world")
    obs = [("Действия", "по смыслу фразы"), ("Место и погода", "слова + смысл"),
           ("Персонажи", "появился / ушёл"), ("Настроение", "→ музыка"), ("Реплика героя?", "не меняет место")]
    xs = [8, 37, 66, 95, 124]
    for (t, s), x in zip(obs, xs):
        box(ax, x, 46, 26, 10, t, s, "world", size=10)
    box(ax, 40, 33, 80, 9, "WorldState: где мы · погода · настроение · кто на сцене · история", None, "world", size=10)
    for x in xs[:4]:
        arrow(ax, (x + 13, 46), (min(max(x + 13, 46), 114), 42), color=C["world"][1], lw=1.2)

    # стрелки из слуха
    arrow(ax, (58, 70), (21, 56), "черновик фразы: сразу", lpos=0.5, loff=(-6, 0))
    ax.plot([86, 86], [70, 60], color=INK, lw=1.5)
    ax.plot([50, 137], [60, 60], color=INK, lw=1.5)
    for x in xs[1:]:
        arrow(ax, (x + 13, 60), (x + 13, 56))
    ax.text(88, 65, "итог фразы", fontsize=FS*8.5, color=MUTED, va="center")
    # Режиссёр
    frame(ax, 3, 2, 154, 25, "ЗВЕНО 3 · ЗВУКОРЕЖИССЁР", "dir")
    box(ax, 8, 6, 46, 13, "engine.py", "изменение мира → звук · отложенные голоса\n· кулдауны · выключенные звуки", "dir", size=10)
    box(ax, 60, 6, 40, 13, "mixer.py", "напряжённость = настроение + темп\n→ громкость слоёв", "dir", size=10)
    box(ax, 106, 6, 46, 13, "audio.py", "фон (плавная смена) · погода ·\nмузыка · короткие звуки", "dir", size=10)
    arrow(ax, (54, 12.5), (60, 12.5))
    arrow(ax, (100, 12.5), (106, 12.5))
    arrow(ax, (80, 33), (31, 19), "изменения мира", lpos=0.55, loff=(4, 1))
    # темп речи: обходим справа и сверху звена 3
    dash = dict(color=MUTED, lw=1.3, ls=(0, (4, 3)))
    ax.plot([102, 155], [75.5, 75.5], **dash)
    ax.plot([155, 155], [75.5, 23], **dash)
    ax.plot([155, 80], [23, 23], **dash)
    arrow(ax, (80, 23), (80, 19), dashed=True, color=MUTED)
    ax.text(153.5, 45, "темп речи", fontsize=FS*8.5, color=MUTED, rotation=90, va="center", ha="right")
    save(fig, "2_pipeline.png")


# ---------- 3. Фраза во времени ----------
def timeline():
    W, H = 160, 62
    fig, ax = canvas(W, H)
    title(ax, W, H, "Одна фраза во времени: «Воин выхватил меч и вошёл в таверну»")
    ax.plot([8, 152], [44, 44], color=INK, lw=1.4)
    ax.add_patch(FancyArrowPatch((150, 44), (155, 44), arrowstyle="-|>", mutation_scale=13, color=INK))
    ax.text(155, 41, "время", fontsize=FS*9, color=MUTED, ha="right")
    words = [("воин", 14), ("выхватил", 30), ("меч", 48), ("и", 60), ("вошёл", 72), ("в", 84), ("таверну", 96)]
    for w, x in words:
        ax.plot([x, x], [43, 45], color=INK, lw=1)
        ax.text(x, 47, w, ha="center", fontsize=FS*10.5, color=INK)
    ax.text(8, 53, "Рассказчик говорит:", fontsize=FS*9.5, color=MUTED)
    ax.add_patch(FancyBboxPatch((104, 42.5), 14, 3, boxstyle="round,pad=0,rounding_size=1", fc="#EEE", ec="#BBB"))
    ax.text(111, 47, "пауза", ha="center", fontsize=FS*9, color=MUTED)
    # события
    ev = [   # (откуда стрелка, центр блока, вид, заголовок, пояснение)
        (30, 26, "ear", "Якорь «выхватил»", "тема «бой» — ждём\nследующие слова"),
        (50, 54, "dir", "Звук меча", "уверенность 0,9 — сразу,\n≤ 1 с от слова"),
        (120, 100, "world", "Персонажи", "итог фразы:\nникого не названо"),
        (120, 130, "dir", "Фон: таверна", "итог фразы → место,\nплавная смена 4 с"),
    ]
    for x0, cx, k, t, s_ in ev:
        box(ax, cx - 13, 18, 26, 13, t, s_, k, size=10)
        arrow(ax, (x0, 43), (cx, 31.2), color=C[k][1], lw=1.2)
    ax.text(8, 8, "Правило: голос персонажа, названного вместе с действием, звучит после звука действия "
                  "(не поверх него); если рассказчик замолчал — доигрывается в тишине.",
            fontsize=FS*9.5, color=MUTED, wrap=True)
    save(fig, "3_timeline.png")


# ---------- 4. Решение по смыслу ----------
def decision():
    W, H = 160, 58
    fig, ax = canvas(W, H)
    title(ax, W, H, "Как выбирается звук действия: по смыслу, а не по слову")
    y = 34
    steps = [
        (3, "Часть фразы", "режем по «и», «а»,\n«потом»…", "ear"),
        (30, "Есть якорь темы?", "меч, лошадь,\nдверь, лук…", "world"),
        (57, "Нет отрицания\nи сравнения?", None, "world"),
        (84, "Контекст", "2 слова до …\n4 после якоря", "world"),
        (111, "Смысл → вариант", "rubert-tiny2 +\nклассификатор темы", "world"),
    ]
    for x, t, s, k in steps:
        box(ax, x, y, 23, 14, t, s, k, size=10)
    for i in range(len(steps) - 1):
        arrow(ax, (steps[i][0] + 23, y + 7), (steps[i + 1][0], y + 7))
    box(ax, 138, 41, 19, 11, "звук", "вариант уверен", "dir", size=10)
    box(ax, 138, 27, 19, 11, "тишина", "«_none»: тема есть,\nзвука не нужно", "dev", size=10)
    arrow(ax, (134, 43), (138, 46.5))
    arrow(ax, (134, 39), (138, 32.5))
    box(ax, 30, 12, 23, 10, "нет → тишина", None, "dev", size=9.5, bold=False)
    box(ax, 57, 12, 23, 10, "есть → тишина", None, "dev", size=9.5, bold=False)
    arrow(ax, (41.5, 34), (41.5, 22), color=MUTED)
    arrow(ax, (68.5, 34), (68.5, 22), color=MUTED)
    box(ax, 98, 6, 50, 15, "Срок и уверенность", "до 0,45 с — нужно 0,8 · до 0,6 с — 0,6\nпозже — 0,5 · конец фразы — 0,4\nподсказки (чем бьют) ×3",
        "data", size=10)
    arrow(ax, (122.5, 21), (122.5, 34), color=C["data"][1])
    ax.text(3, 26, "Примеры для обучения — в\nactions.yaml (6–15 фраз на звук);\nклассификатор учится за ~1 с\nпри запуске.",
            fontsize=FS*9, color=MUTED, va="top")
    save(fig, "4_decision.png")


# ---------- 5. Инструменты и проверка ----------
def tooling():
    W, H = 160, 75
    fig, ax = canvas(W, H)
    title(ax, W, H, "Вокруг конвейера: звуки, каталог, проверка")
    frame(ax, 3, 42, 154, 28, "ЗВУКИ", "data")
    xs = [7, 37, 67, 97, 127]
    items = [("Запросы", "freesound_queries\n.yaml"), ("Скачать", "fetch_freesound.py\nтолько CC0"),
             ("Выбрать", "каталог / pick_sounds\n+ свои записи"), ("Лицензии", "chosen.yaml\nLICENSES.md"),
             ("Готовые WAV", "громкость\nвыровнена")]
    for (t, s), x in zip(items, xs):
        box(ax, x, 46, 26, 13, t, s, "data", size=10)
    for i in range(4):
        arrow(ax, (xs[i] + 26, 52.5), (xs[i + 1], 52.5))
    frame(ax, 3, 2, 74, 36, "КАТАЛОГ · run_catalog.cmd · :8765", "dir")
    box(ax, 7, 20, 30, 11, "Страница каталога", "слушать · оставить ·\nне нужен · найти другие", "dir", size=10)
    box(ax, 43, 20, 30, 11, "«Тест озвучки»", "текст или диктовка →\nнастоящий движок", "dir", size=10)
    box(ax, 25, 5, 30, 10, "Журнал", "что прозвучало и почему", "dir", size=10)
    arrow(ax, (58, 20), (48, 15))
    arrow(ax, (37, 25.5), (43, 25.5))
    frame(ax, 83, 2, 74, 36, "ПРОВЕРКА · verify.ps1 (готово = зелёный)", "ear")
    box(ax, 87, 23, 66, 8, "1 · Статика: код компилируется, YAML читается", None, "ear", size=9.5, bold=False)
    box(ax, 87, 14, 66, 8, "2 · Поведение: правила на тексте, фейковое аудио", None, "ear", size=9.5, bold=False)
    box(ax, 87, 4, 66, 9, "3 · Сквозная: синтез речи → Vosk → звуки;\nсмысл ≥ 85% · задержка ≤ 1 с · сказки целиком", None, "ear", size=9.5, bold=False)
    dash = dict(color=MUTED, lw=1.3, ls=(0, (4, 3)))
    ax.plot([140, 140], [46, 40.5], **dash)
    ax.plot([140, 58], [40.5, 40.5], **dash)
    arrow(ax, (58, 40.5), (58, 31), dashed=True, color=MUTED)
    ax.text(100, 40.5, "готовые звуки", fontsize=FS*8.5, color=MUTED, ha="center", va="center", bbox=dict(fc="white", ec="none", pad=1.2))
    arrow(ax, (55, 5), (87, 8.5), "разбор журнала →\nправка данных → тест", dashed=True, color=MUTED, lpos=0.5, loff=(0, 4))
    save(fig, "5_tooling.png")


# ---------- 6. Путь к мобильной ----------
def mobile():
    W, H = 160, 51
    fig, ax = canvas(W, H)
    title(ax, W, H, "Путь к мобильной версии")
    box(ax, 4, 20, 34, 18, "Прототип · ПК", "Python · pygame\nпроверка идеи", "ear")
    frame(ax, 50, 6, 106, 40, "ТЕЛЕФОН · Flutter", "dir")
    box(ax, 55, 26, 30, 12, "Слух", "Vosk Android/iOS или\nсистемный офлайн", "dir", size=10)
    box(ax, 90, 26, 30, 12, "Смысл", "rubert-tiny2 → ONNX\n+ веса классификаторов", "dir", size=10)
    box(ax, 125, 26, 28, 12, "Звук", "звуковой движок +\nподавление эха", "dir", size=10)
    box(ax, 70, 9, 66, 10, "Переносится как есть: YAML-данные · звуки · правила модели мира", None, "data", size=9.5, bold=False)
    arrow(ax, (38, 29), (50, 29), "переписать\nна Dart", lpos=0.5, loff=(0, 5))
    arrow(ax, (95, 19), (100, 26), color=C["data"][1])
    arrow(ax, (125, 19), (135, 26), color=C["data"][1])
    save(fig, "6_mobile.png")


for f in (overview, pipeline, timeline, decision, tooling, mobile):
    f()
print("ok", sorted(p.name for p in OUT.glob("*.png")))

