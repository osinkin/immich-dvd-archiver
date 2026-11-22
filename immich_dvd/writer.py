from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import FileRecord, ResizeResult, ScanResult, Settings

MANIFEST_COLUMNS = [
    "source", "dest", "disc", "taken_at",
    "src_bytes", "out_bytes", "width", "height", "copied",
]

_NAME_BAD = re.compile(r"[^0-9A-Za-z._-]+")


def long_path(path: Path | str) -> str:
    text = os.path.abspath(str(path))
    if os.name == "nt" and len(text) >= 240 and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def human_bytes(value: float) -> str:
    value = float(value)
    for unit in ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ"):
        if value < 1024 or unit == "ТиБ":
            if unit == "Б":
                return f"{int(value)} Б"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} ТиБ"


def _sanitize(name: str, limit: int = 60) -> str:
    if not name:
        return ""
    stem = Path(name).stem
    stem = _NAME_BAD.sub("_", stem)
    stem = re.sub(r"_+", "_", stem).strip("._- ")
    return stem[:limit].strip("._- ")


def _filename(record: FileRecord) -> str:
    stamp = record.dt.strftime("%Y-%m-%d_%H%M%S")
    suffix = _sanitize(record.original_name)
    if not suffix:
        asset = re.sub(r"[^0-9A-Za-z]", "", Path(record.path).stem)
        suffix = asset[:8] or "image"
    return f"{stamp}_{suffix}.jpg"


def _unique(path: Path) -> Path:
    if not os.path.exists(long_path(path)):
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not os.path.exists(long_path(candidate)):
            return candidate
    raise RuntimeError(f"Не удалось подобрать имя для {path}")


@dataclass
class DiscStats:
    count: int = 0
    out_bytes: int = 0
    first_date: datetime | None = None
    last_date: datetime | None = None


class Writer:
    def __init__(self, dest: Path, settings: Settings) -> None:
        self.dest = dest
        self.settings = settings
        self.manifest_path = dest / "manifest.csv"
        self.processed: set[str] = set()
        self.disc_used: dict[int, int] = {}
        self.disc_stats: dict[int, DiscStats] = {}
        self.current_disc = 1
        self._manifest_file = None
        self._manifest_writer = None
        self._finalized = False
        self._prepare()

    # ------------------------------------------------------------------ setup
    def _prepare(self) -> None:
        os.makedirs(long_path(self.dest), exist_ok=True)
        try:
            existed = self.manifest_path.exists() and self.manifest_path.stat().st_size > 0
        except OSError:
            existed = False
        if existed:
            self._load_manifest()
        self._manifest_file = open(long_path(self.manifest_path), "a", newline="", encoding="utf-8")
        self._manifest_writer = csv.writer(self._manifest_file)
        if not existed:
            self._manifest_writer.writerow(MANIFEST_COLUMNS)
            self._manifest_file.flush()
        if self.settings.split_discs:
            self.current_disc = max(self.disc_used) if self.disc_used else 1
        else:
            self.current_disc = 0

    def _load_manifest(self) -> None:
        try:
            with open(long_path(self.manifest_path), newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    source = (row.get("source") or "").strip()
                    if not source:
                        continue
                    self.processed.add(source)
                    try:
                        disc = int(row.get("disc") or 0)
                        out_bytes = int(row.get("out_bytes") or 0)
                    except ValueError:
                        continue
                    self.disc_used[disc] = self.disc_used.get(disc, 0) + out_bytes
                    stats = self.disc_stats.setdefault(disc, DiscStats())
                    stats.count += 1
                    stats.out_bytes += out_bytes
        except OSError:
            pass

    def already_processed(self, record: FileRecord) -> bool:
        return record.path in self.processed

    # ------------------------------------------------------------------- write
    def write(self, record: FileRecord, result: ResizeResult) -> Path:
        data = result.data
        if data is None:
            raise ValueError("нет данных для записи")

        if self.settings.split_discs:
            used = self.disc_used.get(self.current_disc, 0)
            if used > 0 and used + len(data) > self.settings.disc_limit_bytes():
                self.current_disc += 1
                self.disc_used.setdefault(self.current_disc, 0)

        disc = self.current_disc if self.settings.split_discs else 0
        base = self.dest / f"disc_{disc:02d}" if disc else self.dest
        folder = base / record.dt.strftime("%Y") / record.dt.strftime("%Y-%m-%d")
        os.makedirs(long_path(folder), exist_ok=True)

        target = _unique(folder / _filename(record))
        self._write_atomic(target, data)

        self._manifest_writer.writerow([
            record.path,
            str(target),
            disc,
            record.dt.strftime("%Y-%m-%d %H:%M:%S"),
            record.src_size,
            len(data),
            result.out_width,
            result.out_height,
            int(result.copied),
        ])
        self._manifest_file.flush()

        self.processed.add(record.path)
        self.disc_used[disc] = self.disc_used.get(disc, 0) + len(data)
        stats = self.disc_stats.setdefault(disc, DiscStats())
        stats.count += 1
        stats.out_bytes += len(data)
        if stats.first_date is None or record.dt < stats.first_date:
            stats.first_date = record.dt
        if stats.last_date is None or record.dt > stats.last_date:
            stats.last_date = record.dt
        return target

    def _write_atomic(self, target: Path, data: bytes) -> None:
        temp = target.with_name(target.name + ".tmp")
        try:
            with open(long_path(temp), "wb") as handle:
                handle.write(data)
            os.replace(long_path(temp), long_path(target))
        finally:
            try:
                if os.path.exists(long_path(temp)):
                    os.unlink(long_path(temp))
            except OSError:
                pass

    # ------------------------------------------------------------------ finish
    def finalize(
        self,
        scan: ScanResult | None = None,
        runtime_errors: list[tuple[str, str]] | None = None,
    ) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self._manifest_file is not None:
            try:
                self._manifest_file.close()
            except OSError:
                pass
            self._manifest_file = None

        rows = self._read_manifest()
        self._write_disc_reports(rows)

        errors = list(scan.errors) if scan else []
        errors.extend(runtime_errors or [])
        self._write_csv(self.dest / "skipped.csv", ["source", "reason"], scan.skipped if scan else [])
        self._write_csv(self.dest / "errors.csv", ["source", "error"], errors)
        self._write_global_report(rows, scan, errors)

    def _read_manifest(self) -> list[dict]:
        rows: list[dict] = []
        try:
            with open(long_path(self.manifest_path), newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            pass
        return rows

    def _write_disc_reports(self, rows: list[dict]) -> None:
        by_disc: dict[int, list[dict]] = {}
        for row in rows:
            try:
                disc = int(row.get("disc") or 0)
            except ValueError:
                continue
            by_disc.setdefault(disc, []).append(row)

        discs = sorted(by_disc)
        total = len(discs)
        for index, disc in enumerate(discs, start=1):
            disc_rows = by_disc[disc]
            folder = self.dest / f"disc_{disc:02d}" if disc else self.dest
            os.makedirs(long_path(folder), exist_ok=True)

            out_bytes = sum(int(row.get("out_bytes") or 0) for row in disc_rows)
            dates = sorted(row.get("taken_at") or "" for row in disc_rows if row.get("taken_at"))

            if disc:  # global manifest already lives in the destination root
                self._write_csv_at(
                    folder / "MANIFEST.csv",
                    ["source", "dest", "taken_at", "out_bytes", "width", "height", "copied"],
                    [
                        [
                            row.get("source", ""), row.get("dest", ""), row.get("taken_at", ""),
                            row.get("out_bytes", ""), row.get("width", ""), row.get("height", ""),
                            row.get("copied", ""),
                        ]
                        for row in disc_rows
                    ],
                )

            lines = [
                "Immich DVD Archive",
                "=" * 48,
                f"Диск: {index} из {total}" + ("" if disc else " (без разбивки)"),
                f"Файлов: {len(disc_rows)}",
                f"Объём: {human_bytes(out_bytes)}",
            ]
            if dates:
                lines.append(f"Даты съёмки: {dates[0][:10]} … {dates[-1][:10]}")
            lines += [
                f"Создано: {datetime.now():%Y-%m-%d %H:%M:%S}",
                f"Источник: {self.settings.source}",
                "",
                "Структура: <год>/<год-месяц-день>/<дата_время_имя>.jpg",
                f"Изображения уменьшены до рамки {self.settings.max_width}×{self.settings.max_height} "
                f"(JPEG, качество {self.settings.jpeg_quality}).",
                "Полный список файлов — в MANIFEST.csv рядом с этим файлом.",
            ]
            self._write_text(folder / "README.txt", "\n".join(lines) + "\n")

    def _write_global_report(
        self,
        rows: list[dict],
        scan: ScanResult | None,
        errors: list[tuple[str, str]],
    ) -> None:
        total_out = sum(int(row.get("out_bytes") or 0) for row in rows)
        total_src = sum(int(row.get("src_bytes") or 0) for row in rows)
        discs = sorted({int(row.get("disc") or 0) for row in rows})
        lines = [
            "Immich DVD Archive — отчёт",
            "=" * 48,
            f"Создано: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"Источник: {self.settings.source}",
            f"Назначение: {self.settings.dest}",
            "",
            f"Файлов в архиве: {len(rows)}",
            f"Исходный объём: {human_bytes(total_src)}",
            f"Объём результата: {human_bytes(total_out)}",
            f"Экономия: {human_bytes(max(0, total_src - total_out))}",
            f"Дисков: {len(discs)}",
        ]
        if scan is not None:
            lines.append(f"Пропущено файлов: {len(scan.skipped)} (см. skipped.csv)")
            lines.append(f"Ошибок сканирования: {len(scan.errors)}")
        lines.append(f"Ошибок обработки: {len(errors)} (см. errors.csv)")
        lines.append("")
        lines.append("Исходная библиотека не изменялась (доступ только на чтение).")
        self._write_text(self.dest / "_REPORT.txt", "\n".join(lines) + "\n")

    # ------------------------------------------------------------------ helpers
    def _write_csv(self, path: Path, header: list[str], rows) -> None:
        self._write_csv_at(path, header, rows)

    def _write_csv_at(self, path: Path, header: list[str], rows) -> None:
        try:
            with open(long_path(path), "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                for row in rows:
                    writer.writerow(row)
        except OSError:
            pass

    def _write_text(self, path: Path, text: str) -> None:
        try:
            with open(long_path(path), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError:
            pass
