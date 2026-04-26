import type { JobStatusResponse, MediaKind } from "./types";

export type Language = "en" | "ru";

export const LANGUAGE_STORAGE_KEY = "sbaradio-ytdlp-language";

export const languageOptions: Array<{ code: Language; label: string; shortLabel: string }> = [
  { code: "en", label: "English", shortLabel: "EN" },
  { code: "ru", label: "Русский", shortLabel: "RU" }
];

const en = {
  languageLabel: "Language",
  youtubeLink: "YouTube link",
  preview: "Preview",
  appSubtitle: "YouTube video and playlist downloader",
  selected: "Selected",
  termsAccepted: "I have the right to download this media.",
  startDownload: "Start download",
  playlistLimitWarning: (limit: number) =>
    `The first ${limit} items are selected by default. Reduce the playlist selection before starting.`,
  itemCount: (count: number) => `${count} item${count === 1 ? "" : "s"}`,
  selectAtMost: (limit: number) => `Select at most ${limit} playlist items.`,
  previousDownloadMissing: "Previous download is no longer available.",
  liveProgressDisconnected: "Live progress disconnected. Polling is still active.",
  validYouTubeUrl: "Enter a valid YouTube URL.",
  requestFailed: "Request failed.",
  somethingWentWrong: "Something went wrong.",
  serverStatus: {
    checking: "Checking server",
    online: "Server online",
    degraded: "Server degraded",
    offline: "Server offline"
  },
  serverDetail: {
    lastCheckFailed: (seconds: number, message: string) => `Last check failed. Retrying every ${seconds} seconds. ${message}`,
    waiting: "Waiting for the first server check.",
    activeJobs: (active: number, max: number) => `${active}/${max} active jobs`,
    refreshing: " Refreshing now.",
    uptime: (uptime: string) => `Uptime ${uptime}.`
  },
  uptime: {
    hoursMinutes: (hours: number, minutes: number) => `${hours}h ${minutes}m`,
    minutesSeconds: (minutes: number, seconds: number) => `${minutes}m ${seconds}s`,
    seconds: (seconds: number) => `${seconds}s`
  },
  mediaKind: {
    playlist: "Playlist",
    video: "Video"
  },
  entries: {
    count: (count: number) => `${count} item${count === 1 ? "" : "s"}`,
    selectFirst: (count: number) => `Select first ${count}`,
    clear: "Clear",
    selected: (count: number) => `${count} selected`,
    tableAria: "Playlist entries",
    title: "Title",
    duration: "Duration",
    selectEntry: (title: string) => `Select ${title}`
  },
  controls: {
    format: "Format",
    quality: "Quality",
    qualityBest: {
      mp4: "Best available",
      mp3: "Best audio"
    } satisfies Record<MediaKind, string>
  },
  downloads: {
    available: "Available downloads",
    readyCount: (count: number) => `${count} ready`,
    tableAria: "Available downloads",
    file: "File",
    ready: "Ready",
    actions: "Actions",
    playlistArchive: "Playlist archive",
    mediaFile: "Media file",
    zip: "ZIP",
    media: "Media",
    download: "Download",
    clear: "Clear",
    downloadReady: (isArchive: boolean) => `Download ${isArchive ? "ZIP" : "file"}`
  },
  progress: {
    working: "Working",
    cancel: "Cancel",
    done: (completed: number, total: number) => `${completed} / ${total} done`
  },
  jobStatus: {
    queued: "Queued",
    metadata: "Reading media",
    downloading: "Downloading",
    converting: "Converting",
    archiving: "Creating archive",
    ready: "Ready",
    failed: "Failed",
    cancelled: "Cancelled"
  } satisfies Record<JobStatusResponse["status"], string>,
  backendMessages: {
    queued: "Queued",
    readingMedia: "Reading media information",
    startingDownload: "Starting download",
    converting: "Converting or merging media",
    creatingArchive: "Creating ZIP archive",
    readyToDownload: "Ready to download",
    cancelled: "Cancelled",
    cancelling: "Cancelling",
    downloadFailed: "Download failed",
    downloadingOf: (current: number, total: number) => `Downloading ${current} of ${total}`,
    eta: (value: string) => `ETA ${value}`
  },
  backendErrors: {
    confirmRights: "Confirm that you have the right to download this media.",
    jobNotFound: "Job not found.",
    downloadNotReady: "Download is not ready yet.",
    temporaryFileMissing: "The temporary file is no longer available.",
    invalidYouTubeUrl: "Enter a valid YouTube URL.",
    videoOrPlaylistUrl: "Enter a YouTube video or playlist URL.",
    unsupportedQuality: (kind: string, choices: string) => `Unsupported ${kind} quality. Choose one of: ${choices}.`,
    durationLimit: "This item is longer than the configured duration limit.",
    couldNotReadMedia: "Could not read media information.",
    notDownloadableList: "This link does not contain downloadable videos. Paste a YouTube video or playlist URL.",
    notDownloadableLink: "This link is not a downloadable YouTube video or playlist.",
    noSelectedItems: "No selected playlist items were found.",
    anotherDownloadRunning: "Another download is already running.",
    botVerification:
      "YouTube asked for sign-in/bot verification. Configure APP_YTDLP_COOKIE_FILE with exported browser cookies, or APP_YTDLP_COOKIES_FROM_BROWSER where available, then retry."
  },
  healthMessages: {
    tempRootWritable: "Temp root is writable",
    redisDisabled: "Redis check disabled",
    redisPackageMissing: "Redis package is not installed",
    redisPingSucceeded: "Redis ping succeeded",
    tempRootNotWritable: "Temp root is not writable",
    redisNotReachable: "Redis is not reachable"
  }
};

const ru: typeof en = {
  languageLabel: "Язык",
  youtubeLink: "Ссылка YouTube",
  preview: "Проверить",
  appSubtitle: "Загрузка видео и плейлистов YouTube",
  selected: "Выбрано",
  termsAccepted: "Я имею право скачать этот медиафайл.",
  startDownload: "Начать загрузку",
  playlistLimitWarning: (limit) => `По умолчанию выбраны первые ${limit} элементов. Уменьшите выборку перед запуском.`,
  itemCount: (count) => `${count} ${russianPlural(count, "элемент", "элемента", "элементов")}`,
  selectAtMost: (limit) => `Выберите не более ${limit} элементов плейлиста.`,
  previousDownloadMissing: "Предыдущая загрузка больше недоступна.",
  liveProgressDisconnected: "Онлайн-прогресс отключился. Опрос сервера продолжает работать.",
  validYouTubeUrl: "Введите корректную ссылку YouTube.",
  requestFailed: "Запрос не выполнен.",
  somethingWentWrong: "Что-то пошло не так.",
  serverStatus: {
    checking: "Проверка сервера",
    online: "Сервер доступен",
    degraded: "Сервер работает с ограничениями",
    offline: "Сервер недоступен"
  },
  serverDetail: {
    lastCheckFailed: (seconds, message) => `Последняя проверка не удалась. Повтор каждые ${seconds} сек. ${message}`,
    waiting: "Ожидание первой проверки сервера.",
    activeJobs: (active, max) => `${active}/${max} активных задач`,
    refreshing: " Обновляется сейчас.",
    uptime: (uptime) => `Время работы: ${uptime}.`
  },
  uptime: {
    hoursMinutes: (hours, minutes) => `${hours} ч ${minutes} мин`,
    minutesSeconds: (minutes, seconds) => `${minutes} мин ${seconds} с`,
    seconds: (seconds) => `${seconds} с`
  },
  mediaKind: {
    playlist: "Плейлист",
    video: "Видео"
  },
  entries: {
    count: (count) => `${count} ${russianPlural(count, "элемент", "элемента", "элементов")}`,
    selectFirst: (count) => `Выбрать первые ${count}`,
    clear: "Очистить",
    selected: (count) => `${count} ${russianPlural(count, "выбран", "выбрано", "выбрано")}`,
    tableAria: "Элементы плейлиста",
    title: "Название",
    duration: "Длительность",
    selectEntry: (title) => `Выбрать ${title}`
  },
  controls: {
    format: "Формат",
    quality: "Качество",
    qualityBest: {
      mp4: "Лучшее доступное",
      mp3: "Лучшее аудио"
    }
  },
  downloads: {
    available: "Доступные загрузки",
    readyCount: (count) => `${count} ${russianPlural(count, "готова", "готовы", "готово")}`,
    tableAria: "Доступные загрузки",
    file: "Файл",
    ready: "Готово",
    actions: "Действия",
    playlistArchive: "Архив плейлиста",
    mediaFile: "Медиафайл",
    zip: "ZIP",
    media: "Медиа",
    download: "Скачать",
    clear: "Очистить",
    downloadReady: (isArchive) => `Скачать ${isArchive ? "ZIP" : "файл"}`
  },
  progress: {
    working: "Выполняется",
    cancel: "Отменить",
    done: (completed, total) => `${completed} / ${total} готово`
  },
  jobStatus: {
    queued: "В очереди",
    metadata: "Чтение медиа",
    downloading: "Загрузка",
    converting: "Конвертация",
    archiving: "Создание архива",
    ready: "Готово",
    failed: "Ошибка",
    cancelled: "Отменено"
  },
  backendMessages: {
    queued: "В очереди",
    readingMedia: "Чтение информации о медиа",
    startingDownload: "Запуск загрузки",
    converting: "Конвертация или объединение медиа",
    creatingArchive: "Создание ZIP-архива",
    readyToDownload: "Готово к скачиванию",
    cancelled: "Отменено",
    cancelling: "Отмена",
    downloadFailed: "Загрузка не удалась",
    downloadingOf: (current, total) => `Загрузка ${current} из ${total}`,
    eta: (value) => `Осталось ${value}`
  },
  backendErrors: {
    confirmRights: "Подтвердите, что у вас есть право скачать этот медиафайл.",
    jobNotFound: "Задача не найдена.",
    downloadNotReady: "Загрузка еще не готова.",
    temporaryFileMissing: "Временный файл больше недоступен.",
    invalidYouTubeUrl: "Введите корректную ссылку YouTube.",
    videoOrPlaylistUrl: "Введите ссылку на видео или плейлист YouTube.",
    unsupportedQuality: (kind, choices) => `Качество ${kind} не поддерживается. Выберите одно из: ${choices}.`,
    durationLimit: "Этот элемент длиннее настроенного ограничения длительности.",
    couldNotReadMedia: "Не удалось прочитать информацию о медиа.",
    notDownloadableList: "В этой ссылке нет загружаемых видео. Вставьте ссылку на видео или плейлист YouTube.",
    notDownloadableLink: "Эта ссылка не является загружаемым видео или плейлистом YouTube.",
    noSelectedItems: "Выбранные элементы плейлиста не найдены.",
    anotherDownloadRunning: "Другая загрузка уже выполняется.",
    botVerification:
      "YouTube запросил вход или проверку на бота. Настройте APP_YTDLP_COOKIE_FILE с экспортированными cookie браузера или APP_YTDLP_COOKIES_FROM_BROWSER, если доступно, затем повторите попытку."
  },
  healthMessages: {
    tempRootWritable: "Временная папка доступна для записи",
    redisDisabled: "Проверка Redis отключена",
    redisPackageMissing: "Пакет Redis не установлен",
    redisPingSucceeded: "Ping Redis выполнен",
    tempRootNotWritable: "Временная папка недоступна для записи",
    redisNotReachable: "Redis недоступен"
  }
};

export const translations: Record<Language, typeof en> = {
  en,
  ru
};

export type Translation = typeof en;

export function isLanguage(value: string | null): value is Language {
  return value === "en" || value === "ru";
}

function russianPlural(count: number, one: string, few: string, many: string): string {
  const absolute = Math.abs(count);
  const mod10 = absolute % 10;
  const mod100 = absolute % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return one;
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return few;
  }
  return many;
}
