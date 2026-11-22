from __future__ import annotations

import csv
import multiprocessing as mp
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import CancelledError, Settings
from .resizer import fit_size, init_worker, process_file
from .scanner import scan
from .writer import Writer

_JPEG_EXTS = (".jpg", ".jpeg", ".jpe", ".jfif")


@dataclass
class Progress:
    done: int
    total: int
    out_bytes: int
    current: str
    elapsed: float
    eta: float
    disc: int


def resolve_paths(settings: Settings) -> tuple[Path, Path]:
    if not settings.source.strip():
        raise ValueError("Не выбрана папка-источник")
    if not settings.dest.strip():
        raise ValueError("Не выбрана папка назначения")
    source = Path(settings.source).expanduser().resolve()
    dest = Path(settings.dest).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Папка-источник не найдена: {source}")
    if source == dest:
        raise ValueError("Папка назначения совпадает с источником")
    if source in dest.parents:
        raise ValueError("Папка назначения находится внутри источника — запись в библиотеку запрещена")
    if dest in source.parents:
        raise ValueError("Источник находится внутри папки назначения — выберите другую папку")
    return source, dest


def run_job(
    settings: Settings,
    *,
    on_phase: Callable[[str], None] | None = None,
    on_scan: Callable[[int], None] | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)

    source, dest = resolve_paths(settings)

    if on_phase is not None:
        on_phase("scan")
    log("Сканирование библиотеки…")
    scan_started = time.time()
    scan_result = scan(source, progress=on_scan, cancelled=cancelled)
    log(
        f"Сканирование: изображений {len(scan_result.files)}, "
        f"пропущено {len(scan_result.skipped)}, ошибок {len(scan_result.errors)} "
        f"за {time.time() - scan_started:.0f} с"
    )

    writer = Writer(dest, settings)
    if settings.skip_existing:
        todo = [record for record in scan_result.files if not writer.already_processed(record)]
    else:
        todo = list(scan_result.files)
    skipped_existing = len(scan_result.files) - len(todo)
    if skipped_existing:
        log(f"Уже обработано ранее и пропущено: {skipped_existing}")

    total = len(todo)
    if total == 0:
        writer.finalize(scan_result, [])
        return {
            "total": 0,
            "processed": 0,
            "out_bytes": 0,
            "errors": 0,
            "elapsed": 0.0,
            "discs": len(writer.disc_used),
            "skipped": len(scan_result.skipped),
        }

    if on_phase is not None:
        on_phase("process")
    workers = settings.worker_count()
    log(f"Обработка {total} файлов в {workers} поток(ах)…")

    context = mp.get_context("spawn")
    pool = context.Pool(processes=workers, initializer=init_worker, initargs=(settings,))
    started = time.time()
    done = 0
    out_bytes = 0
    runtime_errors: list[tuple[str, str]] = []
    was_cancelled = False
    completed = False

    try:
        for result in pool.imap(process_file, todo, chunksize=1):
            if cancelled is not None and cancelled():
                was_cancelled = True
                break

            done += 1
            if result.ok:
                writer.write(result.record, result)
                out_bytes += len(result.data or b"")
            else:
                runtime_errors.append((result.record.path, result.error))

            if on_progress is not None:
                elapsed = time.time() - started
                speed = done / elapsed if elapsed > 0 else 0.0
                eta = (total - done) / speed if speed > 0 else 0.0
                on_progress(
                    Progress(
                        done=done,
                        total=total,
                        out_bytes=out_bytes,
                        current=result.record.rel,
                        elapsed=elapsed,
                        eta=eta,
                        disc=writer.current_disc,
                    )
                )
        completed = True
    finally:
        if completed:
            pool.close()
        else:
            pool.terminate()
        pool.join()
        writer.finalize(scan_result, runtime_errors)

    elapsed = time.time() - started
    if was_cancelled:
        log(f"Отменено после {done} из {total} файлов")
        raise CancelledError()

    log(f"Готово за {elapsed:.0f} с, ошибок: {len(runtime_errors)}")
    return {
        "total": total,
        "processed": done,
        "out_bytes": out_bytes,
        "errors": len(runtime_errors),
        "elapsed": elapsed,
        "discs": len(writer.disc_used),
        "skipped": len(scan_result.skipped),
    }


def _load_processed(path: Path) -> set[str]:
    processed: set[str] = set()
    if not path.exists():
        return processed
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                source = (row.get("source") or "").strip()
                if source:
                    processed.add(source)
    except OSError:
        pass
    return processed


def estimate_job(
    settings: Settings,
    *,
    on_scan: Callable[[int], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)

    source, dest = resolve_paths(settings)
    log("Сканирование библиотеки…")
    scan_result = scan(source, progress=on_scan, cancelled=cancelled)
    log(f"Найдено изображений: {len(scan_result.files)}")

    processed = _load_processed(dest / "manifest.csv") if settings.skip_existing else set()
    todo = [record for record in scan_result.files if record.path not in processed]

    limit = settings.disc_limit_bytes()
    est_bytes = 0
    current_disc_bytes = 0
    discs = 1 if todo else 0
    resize_count = 0
    copy_count = 0

    for record in todo:
        width, height = record.effective_size
        target_w, target_h = fit_size(width, height, settings.max_width, settings.max_height)
        is_jpeg = Path(record.path).suffix.lower() in _JPEG_EXTS
        copyable = (
            is_jpeg
            and (target_w, target_h) == (width, height)
            and settings.keep_exif
            and not settings.minimal_exif
        )
        if copyable:
            size = record.src_size
            copy_count += 1
        else:
            size = max(2048, int(target_w * target_h * 0.25))
            resize_count += 1

        if settings.split_discs and current_disc_bytes > 0 and current_disc_bytes + size > limit:
            discs += 1
            current_disc_bytes = 0
        current_disc_bytes += size
        est_bytes += size

    probe = dest
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free_bytes = shutil.disk_usage(probe).free
    except OSError:
        free_bytes = None

    return {
        "files": len(scan_result.files),
        "remaining": len(todo),
        "skipped": len(scan_result.skipped),
        "scan_errors": len(scan_result.errors),
        "est_bytes": est_bytes,
        "resize_count": resize_count,
        "copy_count": copy_count,
        "discs": discs,
        "free_bytes": free_bytes,
        "source": str(source),
        "dest": str(dest),
    }
