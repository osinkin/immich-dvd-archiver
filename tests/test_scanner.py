from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from immich_dvd.models import CancelledError
from immich_dvd.scanner import scan


def _write_jpeg(path: Path, size: tuple[int, int] = (1200, 800), date: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (40, 80, 120))
    if date is not None:
        exif = Image.Exif()
        exif[36867] = date
        image.save(path, "JPEG", exif=exif)
    else:
        image.save(path, "JPEG")


def test_scan_filters_and_reads_dates(tmp_path: Path) -> None:
    library = tmp_path / "library"
    _write_jpeg(library / "user" / "2020" / "photo.jpg", date="2020:05:04 12:00:00")
    _write_jpeg(library / "user" / "no-exif.jpg")

    (library / "user" / "2020" / "photo.xmp").write_text(
        '<x:xmpmeta><rdf:Description exif:OriginalFileName="IMG_0001.JPG"/></x:xmpmeta>',
        encoding="utf-8",
    )
    (library / "user" / "raw.dng").write_bytes(b"raw")
    (library / "user" / "clip.mp4").write_bytes(b"video")
    (library / "user" / "notes.txt").write_text("ignore me", encoding="utf-8")
    (library / "user" / "mystery.xyz").write_bytes(b"?")
    (library / "user" / "empty.jpg").write_bytes(b"")
    _write_jpeg(library / "thumbs" / "thumb.jpg")

    result = scan(library)

    assert len(result.files) == 2
    assert result.source == str(library)
    assert result.total_bytes > 0

    by_name = {Path(record.path).name: record for record in result.files}
    dated = by_name["photo.jpg"]
    assert dated.dt == datetime(2020, 5, 4, 12, 0, 0)
    assert dated.original_name == "IMG_0001.JPG"
    assert dated.rel.endswith("photo.jpg")
    assert by_name["no-exif.jpg"].dt.date() == datetime.fromtimestamp(
        (library / "user" / "no-exif.jpg").stat().st_mtime
    ).date()

    skipped = {Path(path).name: reason for path, reason in result.skipped}
    assert "raw.dng" in skipped
    assert "clip.mp4" in skipped
    assert "mystery.xyz" in skipped
    assert "empty.jpg" in skipped
    assert "thumb.jpg" not in skipped
    assert "notes.txt" not in skipped
    assert "photo.xmp" not in skipped
    assert not result.errors


def test_scan_progress_is_reported(tmp_path: Path) -> None:
    library = tmp_path / "library"
    _write_jpeg(library / "a.jpg", date="2021:01:01 00:00:00")
    seen: list[int] = []

    scan(library, progress=seen.append)

    assert seen[-1] == 1


def test_scan_cancel(tmp_path: Path) -> None:
    library = tmp_path / "library"
    _write_jpeg(library / "a.jpg")

    with pytest.raises(CancelledError):
        scan(library, cancelled=lambda: True)
