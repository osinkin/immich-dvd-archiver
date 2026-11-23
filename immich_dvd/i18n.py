from __future__ import annotations

import locale
import os

SUPPORTED = ("ru", "en")
LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}

_current = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "ru": {
        # application
        "app.title": "Immich DVD Archiver",
        # GUI: folders
        "gui.paths": "Папки",
        "gui.source": "Библиотека Immich:",
        "gui.dest": "Папка результата:",
        "gui.browse": "Обзор…",
        "gui.source_dialog": "Папка библиотеки Immich",
        "gui.dest_dialog": "Папка для результата",
        # GUI: options
        "gui.options": "Параметры",
        "gui.max_width": "Макс. ширина:",
        "gui.max_height": "Макс. высота:",
        "gui.quality": "Качество JPEG:",
        "gui.disc_size": "Лимит диска, ГиБ:",
        "gui.workers": "Потоков (0 = авто):",
        "gui.language": "Язык:",
        "gui.split": "Разбивать на диски",
        "gui.exif": "Сохранять EXIF",
        "gui.minimal_exif": "Минимальный EXIF (без MakerNotes/GPS)",
        "gui.skip_existing": "Пропускать уже готовые",
        # GUI: actions and progress
        "gui.estimate_btn": "Оценить",
        "gui.start_btn": "Старт",
        "gui.cancel_btn": "Отмена",
        "gui.progress": "Прогресс",
        "gui.log": "Журнал",
        "gui.ready": "Готов к работе",
        "gui.scanning": "Сканирование библиотеки: найдено {count} изображений…",
        "gui.stats": "{done} / {total} ({percent:.0f}%) · {size} · {speed:.1f} файл/с · осталось {eta}{disc}",
        "gui.disc_suffix": " · диск {disc}",
        "gui.current_file": "Текущий файл: …{name}",
        "gui.phase_estimate": "Оценка объёма…",
        "gui.phase_process": "Обработка…",
        "gui.cancelling": "Отмена…",
        "gui.cancel_requested": "Запрошена отмена, ожидаем завершения текущего файла…",
        "gui.cancelled": "Операция отменена.",
        "gui.cancelled_state": "Отменено",
        "gui.error_prefix": "ОШИБКА: {message}",
        "gui.error_title": "Ошибка",
        "gui.settings_title": "Проверка настроек",
        "gui.numbers_error": "Проверьте числовые параметры",
        "gui.max_range": "Максимальные размеры должны быть в диапазоне 64…20000",
        "gui.quality_range": "Качество JPEG должно быть от 50 до 95",
        "gui.disc_range": "Лимит диска должен быть от 0.1 до 100 ГиБ",
        "gui.workers_range": "Потоков: 0 (авто) или от 1 до 32",
        "gui.choose_dirs": "Выберите папку-источник и папку назначения",
        "gui.busy_title": "Идёт обработка",
        "gui.busy_close": (
            "Прервать обработку и закрыть программу?\n"
            "Уже записанные файлы останутся, повторный запуск продолжит с места остановки."
        ),
        "gui.finishing": "Завершение…",
        # GUI: estimate dialog
        "gui.estimate_title": "Оценка",
        "gui.estimate_text": (
            "Изображений в библиотеке: {files}\n"
            "К обработке: {remaining}\n"
            "Будет уменьшено: {resize}\n"
            "Будет скопировано как есть: {copy}\n"
            "Пропущено (RAW/видео): {skipped}\n"
            "Ожидаемый объём: ≈ {size}\n"
            "Дисков: {discs}\n"
            "Свободно в папке назначения: {free}"
        ),
        "gui.estimate_warning": "Внимание: ожидаемый объём больше свободного места.",
        "gui.estimate_saved": (
            "Список сохранён: кнопка «Старт» может использовать его без повторного сканирования."
        ),
        # GUI: summary dialog
        "gui.done_title": "Готово",
        "gui.done_text": (
            "Обработано файлов: {processed} из {total}\n"
            "Объём результата: {size}\n"
            "Дисков: {discs}\n"
            "Ошибок: {errors}\n"
            "Время: {time}"
        ),
        # GUI: reuse estimate
        "gui.reuse_title": "Список из оценки",
        "gui.reuse_text": (
            "Использовать список, полученный при оценке?\n\n"
            "Изображений: {count}\n"
            "Оценка сделана: {time}\n\n"
            "Файлы, добавленные или изменённые после оценки, учтены не будут.\n"
            "Выберите «Нет», чтобы просканировать библиотеку заново."
        ),
        # job
        "job.scanning": "Сканирование библиотеки…",
        "job.scan_done": (
            "Сканирование: изображений {files}, пропущено {skipped}, "
            "ошибок {errors} за {seconds:.0f} с"
        ),
        "job.use_estimate": (
            "Используется список из оценки: {count} изображений, повторное сканирование не нужно"
        ),
        "job.already_done": "Уже обработано ранее и пропущено: {count}",
        "job.processing": "Обработка {total} файлов в {workers} поток(ах)…",
        "job.cancelled_after": "Отменено после {done} из {total} файлов",
        "job.done": "Готово за {seconds:.0f} с, ошибок: {errors}",
        # scanner skip reasons
        "scan.raw": "RAW — не поддерживается",
        "scan.video": "видео — пропущено",
        "scan.unknown": "неизвестный формат ({ext})",
        "scan.unsupported": "формат не поддерживается ({ext})",
        "scan.empty": "пустой файл",
        "scan.no_ext": "без расширения",
        "scan.read_error": "не удалось прочитать изображение",
        # per-disc readme
        "disc.title": "Immich DVD Archive",
        "disc.disc": "Диск: {index} из {total}",
        "disc.disc_flat": "Диск: {index} из {total} (без разбивки)",
        "disc.files": "Файлов: {count}",
        "disc.size": "Объём: {size}",
        "disc.dates": "Даты съёмки: {first} … {last}",
        "disc.created": "Создано: {time}",
        "disc.source": "Источник: {path}",
        "disc.structure": "Структура: <год>/<год-месяц-день>/<дата_время_имя>.jpg",
        "disc.resized": (
            "Изображения уменьшены до рамки {width}×{height} (JPEG, качество {quality})."
        ),
        "disc.manifest": "Полный список файлов — в MANIFEST.csv рядом с этим файлом.",
        # global report
        "report.title": "Immich DVD Archive — отчёт",
        "report.created": "Создано: {time}",
        "report.source": "Источник: {path}",
        "report.dest": "Назначение: {path}",
        "report.files": "Файлов в архиве: {count}",
        "report.src_size": "Исходный объём: {size}",
        "report.out_size": "Объём результата: {size}",
        "report.saved": "Экономия: {size}",
        "report.discs": "Дисков: {count}",
        "report.skipped": "Пропущено файлов: {count} (см. skipped.csv)",
        "report.scan_errors": "Ошибок сканирования: {count}",
        "report.proc_errors": "Ошибок обработки: {count} (см. errors.csv)",
        "report.readonly": "Исходная библиотека не изменялась (доступ только на чтение).",
        # time
        "time.hours": "{hours} ч {minutes:02d} мин",
        "time.minutes": "{minutes} мин {seconds:02d} с",
        "time.seconds": "{seconds} с",
        # CLI
        "cli.err_no_source": "папка-источник не задана (используйте --source)",
        "cli.err_no_dest": "папка назначения не задана (используйте --dest)",
        "cli.err_quality": "--quality должна быть от 50 до 95",
        "cli.err_disc": "--disc-size должна быть положительной",
        "cli.err_workers": "--workers должна быть 0 или больше",
        "cli.scanning": "Сканирование… найдено {count}",
        "cli.cancel_wait": "Отмена, ждём завершения текущего файла…",
        "cli.cancelled": "Отменено. Запустите снова, чтобы продолжить с последнего записанного файла.",
        "cli.interrupted": "Прервано.",
        "cli.error": "Ошибка: {message}",
        "cli.done": (
            "Готово: {processed} из {total} файлов, {size}, дисков: {discs}, "
            "ошибок: {errors}, {seconds:.0f} с (всего {total_seconds:.0f} с)"
        ),
        "cli.progress": (
            "{done}/{total} ({percent:.0f}%) · {size} · {speed:.1f} файл/с · диск {disc}"
        ),
        "cli.est_source": "Источник: {value}",
        "cli.est_dest": "Назначение: {value}",
        "cli.est_files": "Изображений найдено: {value}",
        "cli.est_remaining": "К обработке: {value}",
        "cli.est_resize": "Будет уменьшено: {value}",
        "cli.est_copy": "Будет скопировано как есть: {value}",
        "cli.est_skipped": "Пропущено RAW/видео: {value}",
        "cli.est_scan_errors": "Ошибок сканирования: {value}",
        "cli.est_size": "Ожидаемый объём: ~{value}",
        "cli.est_discs": "Дисков: {value}",
        "cli.est_free": "Свободно: {value}",
        "cli.no_display": (
            "Графическое окружение не обнаружено.\n"
            "Используйте --no-gui с --source/--dest, например:\n"
            "  immich-dvd --no-gui --source /mnt/immich/library --dest /mnt/archive\n"
            "Все параметры: --help."
        ),
        "cli.tk_missing": (
            "Не удалось запустить GUI: {error}\n"
            "В Linux установите Tkinter (например, 'sudo apt install python3-tk') "
            "или запустите с --no-gui."
        ),
    },
    "en": {
        "app.title": "Immich DVD Archiver",
        "gui.paths": "Folders",
        "gui.source": "Immich library:",
        "gui.dest": "Output folder:",
        "gui.browse": "Browse…",
        "gui.source_dialog": "Immich library folder",
        "gui.dest_dialog": "Output folder",
        "gui.options": "Options",
        "gui.max_width": "Max width:",
        "gui.max_height": "Max height:",
        "gui.quality": "JPEG quality:",
        "gui.disc_size": "Disc size, GiB:",
        "gui.workers": "Workers (0 = auto):",
        "gui.language": "Language:",
        "gui.split": "Split into discs",
        "gui.exif": "Keep EXIF",
        "gui.minimal_exif": "Minimal EXIF (no MakerNotes/GPS)",
        "gui.skip_existing": "Skip already processed",
        "gui.estimate_btn": "Estimate",
        "gui.start_btn": "Start",
        "gui.cancel_btn": "Cancel",
        "gui.progress": "Progress",
        "gui.log": "Log",
        "gui.ready": "Ready",
        "gui.scanning": "Scanning library: {count} images found…",
        "gui.stats": "{done} / {total} ({percent:.0f}%) · {size} · {speed:.1f} files/s · ETA {eta}{disc}",
        "gui.disc_suffix": " · disc {disc}",
        "gui.current_file": "Current file: …{name}",
        "gui.phase_estimate": "Estimating…",
        "gui.phase_process": "Processing…",
        "gui.cancelling": "Cancelling…",
        "gui.cancel_requested": "Cancellation requested, waiting for the current file…",
        "gui.cancelled": "Operation cancelled.",
        "gui.cancelled_state": "Cancelled",
        "gui.error_prefix": "ERROR: {message}",
        "gui.error_title": "Error",
        "gui.settings_title": "Settings check",
        "gui.numbers_error": "Check the numeric parameters",
        "gui.max_range": "Maximum dimensions must be between 64 and 20000",
        "gui.quality_range": "JPEG quality must be between 50 and 95",
        "gui.disc_range": "Disc size must be between 0.1 and 100 GiB",
        "gui.workers_range": "Workers: 0 (auto) or 1 to 32",
        "gui.choose_dirs": "Choose the source and destination folders",
        "gui.busy_title": "Processing",
        "gui.busy_close": (
            "Cancel processing and close the program?\n"
            "Files already written are kept; running again continues from where it stopped."
        ),
        "gui.finishing": "Finishing…",
        "gui.estimate_title": "Estimate",
        "gui.estimate_text": (
            "Images in library: {files}\n"
            "To process: {remaining}\n"
            "Will be resized: {resize}\n"
            "Copied as is: {copy}\n"
            "Skipped (RAW/video): {skipped}\n"
            "Estimated size: ≈ {size}\n"
            "Discs: {discs}\n"
            "Free in destination: {free}"
        ),
        "gui.estimate_warning": "Warning: the estimated size exceeds the available free space.",
        "gui.estimate_saved": "The list is kept: Start can reuse it without scanning again.",
        "gui.done_title": "Done",
        "gui.done_text": (
            "Processed files: {processed} of {total}\n"
            "Result size: {size}\n"
            "Discs: {discs}\n"
            "Errors: {errors}\n"
            "Time: {time}"
        ),
        "gui.reuse_title": "Scan from estimate",
        "gui.reuse_text": (
            "Use the list produced by the estimate?\n\n"
            "Images: {count}\n"
            "Estimated at: {time}\n\n"
            "Files added or changed after the estimate will not be included.\n"
            "Choose No to scan the library again."
        ),
        "job.scanning": "Scanning library…",
        "job.scan_done": (
            "Scan: {files} images, {skipped} skipped, {errors} errors in {seconds:.0f} s"
        ),
        "job.use_estimate": (
            "Using the scan from the estimate: {count} images, no rescan needed"
        ),
        "job.already_done": "Already processed earlier and skipped: {count}",
        "job.processing": "Processing {total} files with {workers} worker(s)…",
        "job.cancelled_after": "Cancelled after {done} of {total} files",
        "job.done": "Done in {seconds:.0f} s, errors: {errors}",
        "scan.raw": "RAW — not supported",
        "scan.video": "video — skipped",
        "scan.unknown": "unknown format ({ext})",
        "scan.unsupported": "unsupported format ({ext})",
        "scan.empty": "empty file",
        "scan.no_ext": "no extension",
        "scan.read_error": "failed to read the image",
        "disc.title": "Immich DVD Archive",
        "disc.disc": "Disc: {index} of {total}",
        "disc.disc_flat": "Disc: {index} of {total} (no splitting)",
        "disc.files": "Files: {count}",
        "disc.size": "Size: {size}",
        "disc.dates": "Dates taken: {first} … {last}",
        "disc.created": "Created: {time}",
        "disc.source": "Source: {path}",
        "disc.structure": "Layout: <year>/<year-month-day>/<date_time_name>.jpg",
        "disc.resized": "Images resized to fit {width}×{height} (JPEG, quality {quality}).",
        "disc.manifest": "The full file list is in MANIFEST.csv next to this file.",
        "report.title": "Immich DVD Archive — report",
        "report.created": "Created: {time}",
        "report.source": "Source: {path}",
        "report.dest": "Destination: {path}",
        "report.files": "Files in archive: {count}",
        "report.src_size": "Source size: {size}",
        "report.out_size": "Result size: {size}",
        "report.saved": "Saved: {size}",
        "report.discs": "Discs: {count}",
        "report.skipped": "Skipped files: {count} (see skipped.csv)",
        "report.scan_errors": "Scan errors: {count}",
        "report.proc_errors": "Processing errors: {count} (see errors.csv)",
        "report.readonly": "The source library was not modified (read-only access).",
        "time.hours": "{hours} h {minutes:02d} min",
        "time.minutes": "{minutes} min {seconds:02d} s",
        "time.seconds": "{seconds} s",
        "cli.err_no_source": "source folder is not set (use --source)",
        "cli.err_no_dest": "destination folder is not set (use --dest)",
        "cli.err_quality": "--quality must be between 50 and 95",
        "cli.err_disc": "--disc-size must be positive",
        "cli.err_workers": "--workers must be 0 or greater",
        "cli.scanning": "Scanning… {count} images",
        "cli.cancel_wait": "Cancelling, waiting for the current file…",
        "cli.cancelled": "Cancelled. Run again to continue from the last written file.",
        "cli.interrupted": "Interrupted.",
        "cli.error": "Error: {message}",
        "cli.done": (
            "Done: {processed} of {total} files, {size}, {discs} disc(s), "
            "{errors} error(s), {seconds:.0f} s (total {total_seconds:.0f} s)"
        ),
        "cli.progress": (
            "{done}/{total} ({percent:.0f}%) · {size} · {speed:.1f} files/s · disc {disc}"
        ),
        "cli.est_source": "Source: {value}",
        "cli.est_dest": "Destination: {value}",
        "cli.est_files": "Images found: {value}",
        "cli.est_remaining": "To process: {value}",
        "cli.est_resize": "Will be resized: {value}",
        "cli.est_copy": "Copied as is: {value}",
        "cli.est_skipped": "Skipped RAW/video: {value}",
        "cli.est_scan_errors": "Scan errors: {value}",
        "cli.est_size": "Estimated size: ~{value}",
        "cli.est_discs": "Discs: {value}",
        "cli.est_free": "Free space: {value}",
        "cli.no_display": (
            "No graphical display detected.\n"
            "Use --no-gui with --source/--dest, for example:\n"
            "  immich-dvd --no-gui --source /mnt/immich/library --dest /mnt/archive\n"
            "Run with --help for all options."
        ),
        "cli.tk_missing": (
            "Cannot start the GUI: {error}\n"
            "On Linux install Tkinter (e.g. 'sudo apt install python3-tk') "
            "or run with --no-gui."
        ),
    },
}

_BYTE_UNITS = {
    "ru": ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ"),
    "en": ("B", "KiB", "MiB", "GiB", "TiB"),
}


def detect_language() -> str:
    for name in ("IMMICH_DVD_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "").strip().lower()
        if value.startswith("ru"):
            return "ru"
        if value.startswith("en"):
            return "en"
    try:
        locale_name = locale.getlocale()[0] or ""
    except Exception:
        locale_name = ""
    return "ru" if locale_name.lower().startswith("ru") else "en"


def set_language(language: str | None) -> str:
    global _current
    code = (language or "").strip().lower()[:2]
    if code not in SUPPORTED:
        code = "en"
    _current = code
    return _current


def get_language() -> str:
    return _current


def byte_units() -> tuple[str, ...]:
    return _BYTE_UNITS.get(_current, _BYTE_UNITS["en"])


def t(key: str, **kwargs) -> str:
    template = _STRINGS.get(_current, {}).get(key)
    if template is None:
        template = _STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template
