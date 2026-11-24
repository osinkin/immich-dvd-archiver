from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PIL import Image

from .i18n import t
from .models import CancelledError, FileRecord, ScanResult

try:  # HEIC/HEIF support is optional but expected
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - depends on installed packages
    pass

Image.MAX_IMAGE_PIXELS = 500_000_000

# Extensions Pillow can actually open in this environment (HEIC only with pillow-heif).
_SUPPORTED_EXTS = {ext.lower() for ext in Image.registered_extensions()}

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif",
    ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    ".heic", ".heif", ".avif",
}
RAW_EXTS = {
    ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".raf", ".orf", ".rw2", ".raw", ".pef", ".srw", ".x3f", ".3fr", ".erf",
    ".mef", ".mos", ".mrw", ".rwl", ".k25", ".kdc", ".dcr", ".iiq", ".cap",
}
VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".3gp", ".3g2", ".mts", ".m2ts", ".mpg", ".mpeg", ".ogv", ".insv",
}
IGNORED_EXTS = {".xmp", ".json", ".txt", ".aae", ".xml", ".db", ".log", ".ini", ".thm"}
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".directory"}
SERVICE_DIRS = {
    "thumbs", "encoded-video", "upload", "profile", ".immich",
    "@eadir", "#recycle", ".trash", ".recycle", "lost+found",
}

_DATE_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")

_XMP_PATTERNS = (
    re.compile(rb"exif:OriginalFileName\s*=\s*[\"']([^\"']{1,160})[\"']"),
    re.compile(rb"<exif:OriginalFileName>([^<]{1,160})</exif:OriginalFileName>"),
    re.compile(rb"<tiff:DocumentName>([^<]{1,160})</tiff:DocumentName>"),
)


def iter_files(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    name = entry.name.lower()
                    if name in SERVICE_DIRS or name.startswith("."):
                        continue
                    stack.append(Path(entry.path))
                elif entry.is_file():
                    yield Path(entry.path)
            except OSError:
                continue


def _parse_exif_date(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    text = str(value).strip().strip("\x00").strip()
    if not text or text.startswith("0000"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def read_meta(path: Path) -> tuple[datetime | None, int, int, int]:
    """Return (date_taken, width, height, orientation) using header-only access."""
    try:
        with Image.open(path) as img:
            width, height = img.size
            try:
                exif = img.getexif()
            except Exception:
                exif = None
    except Exception:
        return None, 0, 0, 1

    taken = None
    orientation = 1
    if exif:
        for tag in (36867, 36868, 306):
            taken = _parse_exif_date(exif.get(tag))
            if taken is not None:
                break
        raw_orientation = exif.get(274)
        try:
            orientation = int(raw_orientation) if raw_orientation is not None else 1
        except (TypeError, ValueError):
            orientation = 1
        if orientation not in range(1, 9):
            orientation = 1
    return taken, width, height, orientation


def read_original_name(path: Path) -> str:
    sidecar = path.with_suffix(".xmp")
    if not sidecar.exists():
        return ""
    try:
        with open(sidecar, "rb") as handle:
            head = handle.read(256 * 1024)
    except OSError:
        return ""
    for pattern in _XMP_PATTERNS:
        match = pattern.search(head)
        if match:
            return match.group(1).decode("utf-8", "ignore").strip()
    return ""


def scan(
    source: Path,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ScanResult:
    result = ScanResult()
    result.source = str(source)
    found = 0

    for path in iter_files(source):
        if cancelled is not None and cancelled():
            raise CancelledError()

        ext = path.suffix.lower()
        if ext in RAW_EXTS:
            result.skipped.append((str(path), t("scan.raw")))
            continue
        if ext in VIDEO_EXTS:
            result.skipped.append((str(path), t("scan.video")))
            continue
        if ext not in IMAGE_EXTS:
            if ext in IGNORED_EXTS or path.name.lower() in IGNORED_NAMES:
                continue
            result.skipped.append((str(path), t("scan.unknown", ext=ext or t("scan.no_ext"))))
            continue

        if ext not in _SUPPORTED_EXTS:
            result.skipped.append((str(path), t("scan.unsupported", ext=ext)))
            continue

        try:
            stat = path.stat()
        except OSError as exc:
            result.errors.append((str(path), str(exc)))
            continue
        if stat.st_size == 0:
            result.skipped.append((str(path), t("scan.empty")))
            continue

        taken, width, height, orientation = read_meta(path)
        if not width or not height:
            result.errors.append((str(path), t("scan.read_error")))
            continue
        if taken is None:
            taken = datetime.fromtimestamp(stat.st_mtime)

        try:
            rel = str(path.relative_to(source))
        except ValueError:
            rel = path.name

        result.files.append(
            FileRecord(
                path=str(path),
                rel=rel,
                dt=taken,
                src_size=stat.st_size,
                width=width,
                height=height,
                orientation=orientation,
                original_name=read_original_name(path),
            )
        )
        result.total_bytes += stat.st_size
        found += 1
        if progress is not None and found % 50 == 0:
            progress(found)

    result.files.sort(key=lambda record: (record.dt, record.rel.lower()))
    if progress is not None:
        progress(len(result.files))
    return result
