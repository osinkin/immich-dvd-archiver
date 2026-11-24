from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image

from immich_dvd.models import FileRecord, Settings
from immich_dvd.resizer import fit_size, init_worker, process_file


def _record(path: Path, width: int, height: int, orientation: int = 1) -> FileRecord:
    return FileRecord(
        path=str(path),
        rel=path.name,
        dt=datetime(2020, 1, 2, 3, 4, 5),
        src_size=path.stat().st_size,
        width=width,
        height=height,
        orientation=orientation,
    )


def _jpeg(path: Path, size: tuple[int, int], orientation: int | None = None) -> Path:
    image = Image.new("RGB", size, (10, 120, 200))
    if orientation is None:
        image.save(path, "JPEG", quality=95)
    else:
        exif = Image.Exif()
        exif[274] = orientation
        exif[36867] = "2020:01:02 03:04:05"
        image.save(path, "JPEG", quality=95, exif=exif)
    return path


def test_fit_size_never_upscales() -> None:
    assert fit_size(800, 600, 1920, 1080) == (800, 600)
    assert fit_size(3840, 2160, 1920, 1080) == (1920, 1080)
    assert fit_size(1080, 1920, 1920, 1080) == (608, 1080)
    assert fit_size(0, 100, 1920, 1080) == (0, 100)


def test_small_jpeg_is_copied_byte_for_byte(tmp_path: Path) -> None:
    path = _jpeg(tmp_path / "small.jpg", (800, 600))
    init_worker(Settings(max_width=1920, max_height=1080))

    result = process_file(_record(path, 800, 600))

    assert result.ok
    assert result.copied
    assert result.data == path.read_bytes()
    assert (result.out_width, result.out_height) == (800, 600)


def test_large_jpeg_is_resized(tmp_path: Path) -> None:
    path = _jpeg(tmp_path / "large.jpg", (3840, 2160))
    init_worker(Settings(max_width=1920, max_height=1080))

    result = process_file(_record(path, 3840, 2160))

    assert result.ok
    assert not result.copied
    with Image.open(io.BytesIO(result.data)) as output:
        assert output.size == (1920, 1080)
        assert output.format == "JPEG"


def test_orientation_is_applied(tmp_path: Path) -> None:
    path = _jpeg(tmp_path / "portrait.jpg", (4000, 3000), orientation=6)
    init_worker(Settings(max_width=1920, max_height=1080))

    result = process_file(_record(path, 4000, 3000, orientation=6))

    assert result.ok
    assert (result.out_width, result.out_height) == (810, 1080)
    with Image.open(io.BytesIO(result.data)) as output:
        assert output.size == (810, 1080)


def test_png_with_alpha_becomes_jpeg(tmp_path: Path) -> None:
    path = tmp_path / "graphic.png"
    Image.new("RGBA", (2400, 1600), (255, 0, 0, 128)).save(path)
    init_worker(Settings(max_width=1920, max_height=1080))

    result = process_file(_record(path, 2400, 1600))

    assert result.ok
    assert not result.copied
    assert result.data is not None
    assert result.data[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(result.data)) as output:
        assert output.size == (1620, 1080)
        assert output.mode == "RGB"


def test_minimal_exif_drops_extra_tags(tmp_path: Path) -> None:
    path = tmp_path / "meta.jpg"
    image = Image.new("RGB", (800, 600), (1, 2, 3))
    exif = Image.Exif()
    exif[271] = "TestMake"
    exif[270] = "A description"
    exif[305] = "SomeSoftware"
    exif[36867] = "2020:01:02 03:04:05"
    image.save(path, "JPEG", exif=exif)
    init_worker(Settings(max_width=1920, max_height=1080, minimal_exif=True))

    result = process_file(_record(path, 800, 600))

    assert result.ok
    with Image.open(io.BytesIO(result.data)) as output:
        output_exif = output.getexif()
    assert output_exif.get(271) == "TestMake"
    assert output_exif.get(305) == "SomeSoftware"
    assert 270 not in output_exif
    assert output_exif.get(274) is None
