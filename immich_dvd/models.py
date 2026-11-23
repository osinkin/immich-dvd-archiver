from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime


class CancelledError(Exception):
    """Операция отменена пользователем."""


@dataclass
class Settings:
    source: str = ""
    dest: str = ""
    max_width: int = 1920
    max_height: int = 1080
    jpeg_quality: int = 85
    disc_limit_gib: float = 4.3
    split_discs: bool = True
    keep_exif: bool = True
    minimal_exif: bool = False
    skip_existing: bool = True
    workers: int = 0
    language: str = ""

    def disc_limit_bytes(self) -> int:
        return max(1, int(self.disc_limit_gib * 1024 ** 3))

    def worker_count(self) -> int:
        if self.workers > 0:
            return self.workers
        return max(1, min(os.cpu_count() or 4, 8))


@dataclass(slots=True)
class FileRecord:
    path: str
    rel: str
    dt: datetime
    src_size: int
    width: int
    height: int
    orientation: int = 1
    original_name: str = ""

    @property
    def effective_size(self) -> tuple[int, int]:
        if self.orientation in (5, 6, 7, 8):
            return self.height, self.width
        return self.width, self.height


@dataclass(slots=True)
class ResizeResult:
    record: FileRecord
    ok: bool
    data: bytes | None = None
    out_width: int = 0
    out_height: int = 0
    copied: bool = False
    error: str = ""


@dataclass
class ScanResult:
    files: list[FileRecord] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    total_bytes: int = 0
    source: str = ""
