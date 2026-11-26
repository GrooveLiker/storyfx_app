/// Настраиваемые константы движка — порт prototype/src/storyfx/config.py.
/// Пути (DATA_DIR, SOUNDS_DIR…) на телефоне решаются assets/каталогом приложения.
library;

// Звуки действий (actions)
const defaultCooldownS = 1.5;
const contextBefore = 2; // слов до якоря темы в классификатор
const contextClauseStart = 4; // но если начало части фразы не дальше — берём от него
const contextStop = {'а', 'но', 'однако', 'зато'};
const contextAfter = 4; // слов после якоря: ждём их на частичных результатах
const actionCarryS = 4.0; // хвост фразы с якорем «без звука» переходит в следующую
const actionCarryWords = 6; // …и только из короткой фразы-обрывка
const cueBoost = 3.0; // во столько раз растёт уверенность варианта при его подсказке
const actionMinConf = 0.40;
const actionEarlyConf = 0.80;
const actionSoftDeadlineS = 0.45;
const actionSoftConf = 0.60;
const actionHardDeadlineS = 0.60;
const actionLateConf = 0.50;
const actionBareConf = 0.60;
const pendingWords = {'и', 'а', 'но', 'так', 'не', 'ни', 'вдруг'};
const clauseBreaks = {'и', 'а', 'но', 'потом', 'затем', 'тогда', 'когда', 'пока', 'однако', 'зато', 'вдруг'};
const maxGapWords = 2;
const negationWindow = 2;
const negations = {'не', 'нет', 'ни', 'без'};
const simileWords = {'как', 'словно', 'будто', 'точно', 'подобно', 'вроде'};
const similePerception = ('слуша', 'слыш', 'смотр', 'гляд', 'вид', 'виж');
const objectPrepositions = {'у', 'от', 'из', 'к', 'ко', 'за', 'про', 'о', 'об', 'до', 'для'};
const addressWords = {'ты', 'вы', 'тебя', 'тебе', 'вас'};
const addressWindow = 3;

// Персонажи
const characterReintroPhrases = 30;
const characterDeferMaxS = 8.0;
const characterAfterActionS = 2.0;
const maxCharactersPerPhrase = 2;

// Сцены
const sceneWindowWords = 40;
const sceneKeepAfterSwitch = 8;
const sceneIntervalS = 3.0;
const sceneThreshold = 0.80;
const sceneMargin = 0.08;
const sceneConfirm = 3;
const sceneMinWords = 8;
const sceneMinDwell = 3;
const sceneClfConf = 0.45;
const sceneClfMargin = 0.15;
const sceneClfMinWords = 3;
// Медленный контекст рассказа (D-019)
const contextSlowAlpha = 0.25;
const contextContradict = 0.0;
const contextPendingPhrases = 2;
// Настроение
const moodThreshold = 0.60;
const moodMargin = 0.03;
const moodConfirm = 3;
const moodMinDwell = 8;
const keywordBonus = 0.15;
const maxOverlays = 2;

// Звук
const crossfadeMs = 2500;
const musicCrossfadeMs = 4000;
const mixCalm = (0.50, 0.42, 0.65, 0.11);
const mixIntense = (0.32, 0.32, 1.00, 0.17);
const moodIntensity = {'calm': 0.15, 'cheerful': 0.45, 'tense': 0.65, 'action': 0.95};
const tempoWindowS = 10.0;
const tempoMinWords = 6;
const tempoSlow = 1.8;
const tempoFast = 3.6;
const tempoWeight = 0.35;
const intensityTauS = 3.0;
