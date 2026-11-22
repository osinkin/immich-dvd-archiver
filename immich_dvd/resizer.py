from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from .models import FileRecord, ResizeResult, Settings

try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow < 9.1
    LANCZOS = Image.LANCZOS

_JPEG_EXTS = (".jpg", ".jpeg", ".jpe", ".jfif")

_MINIMAL_EXIF_TAGS = {
    271,  # Make
    272,  # Model
    305,  # Software
    306,  # DateTime
    315,  # Artist
    33434,  # ExposureTime
    33437,  # FNumber
    34850,  # ExposureProgram
    34855,  # ISOSpeedRatings
    36864,  # ExifVersion
    36867,  # DateTimeOriginal
    36868,  # DateTimeDigitized
    37377,  # ShutterSpeedValue
    37380,  # ExposureBiasValue
    37382,  # SubjectDistance
    37383,  # MeteringMode
    37385,  # Flash
    37386,  # FocalLength
    41986,  # ExposureMode
    41987,  # WhiteBalance
    42035,  # LensMake
    42036,  # LensModel
}

_WORKER: Settings | None = None


def init_worker(settings: Settings) -> None:
    global _WORKER
    _WORKER = settings
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:
        pass
    Image.MAX_IMAGE_PIXELS = 500_000_000


def fit_size(width: int, height: int, box_w: int, box_h: int) -> tuple[int, int]:
    if width <= 0 or height <= 0 or box_w <= 0 or box_h <= 0:
        return width, height
    scale = min(box_w / width, box_h / height, 1.0)
    if scale >= 1.0:
        return width, height
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def process_file(record: FileRecord) -> ResizeResult:
    settings = _WORKER
    if settings is None:
        return ResizeResult(record=record, ok=False, error="worker не инициализирован")
    try:
        return _process(record, settings)
    except Exception as exc:
        return ResizeResult(record=record, ok=False, error=f"{type(exc).__name__}: {exc}")


def _process(record: FileRecord, settings: Settings) -> ResizeResult:
    path = Path(record.path)
    eff_w, eff_h = record.effective_size
    target_w, target_h = fit_size(eff_w, eff_h, settings.max_width, settings.max_height)
    needs_resize = (target_w, target_h) != (eff_w, eff_h)
    is_jpeg = path.suffix.lower() in _JPEG_EXTS

    # Already small JPEG: copy bytes untouched, no recompression.
    if is_jpeg and not needs_resize and settings.keep_exif and not settings.minimal_exif:
        data = path.read_bytes()
        return ResizeResult(
            record=record,
            ok=True,
            data=data,
            out_width=target_w,
            out_height=target_h,
            copied=True,
        )

    with Image.open(path) as src:
        icc_profile = src.info.get("icc_profile")
        exif_bytes = _exif_bytes(src, settings) if settings.keep_exif else None
        if is_jpeg and needs_resize:
            try:
                src.draft("RGB", (target_w, target_h))
            except Exception:
                pass
        img = ImageOps.exif_transpose(src)
        img = _to_rgb(img)

        actual_w, actual_h = fit_size(img.width, img.height, settings.max_width, settings.max_height)
        if (actual_w, actual_h) != img.size:
            img = img.resize((actual_w, actual_h), LANCZOS)

        buffer = io.BytesIO()
        params = {
            "format": "JPEG",
            "quality": settings.jpeg_quality,
            "optimize": True,
            "progressive": True,
        }
        if exif_bytes:
            params["exif"] = exif_bytes
        if icc_profile:
            params["icc_profile"] = icc_profile
        img.save(buffer, **params)

    return ResizeResult(
        record=record,
        ok=True,
        data=buffer.getvalue(),
        out_width=actual_w,
        out_height=actual_h,
    )


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if img.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):
        gray = img.convert("I")
        low, high = gray.getextrema()
        if high > low:
            gray = gray.point(lambda value: (value - low) * 255.0 / (high - low))
        return gray.convert("L").convert("RGB")
    if img.mode == "F":
        return img.convert("L").convert("RGB")
    return img.convert("RGB")


def _exif_bytes(src: Image.Image, settings: Settings) -> bytes | None:
    try:
        source_exif = src.getexif()
        if not source_exif:
            return None
        # getexif() returns the image's own object: copy it before editing,
        # otherwise exif_transpose() would lose the Orientation tag.
        exif = Image.Exif()
        exif.load(source_exif.tobytes())
        exif.pop(274, None)  # orientation is already applied to pixels
        if settings.minimal_exif:
            minimal = Image.Exif()
            for tag in _MINIMAL_EXIF_TAGS:
                if tag in exif:
                    minimal[tag] = exif[tag]
            exif = minimal
        return exif.tobytes() if exif else None
    except Exception:
        return None
