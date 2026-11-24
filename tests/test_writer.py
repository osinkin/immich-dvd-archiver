from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from immich_dvd.models import FileRecord, ResizeResult, Settings
from immich_dvd.writer import MANIFEST_COLUMNS, Writer


def _record(index: int, original_name: str = "IMG_0001") -> FileRecord:
    return FileRecord(
        path=f"/library/asset-{index}.jpg",
        rel=f"asset-{index}.jpg",
        dt=datetime(2019, 7, 4, 12, 15, 30) + timedelta(minutes=index),
        src_size=5000,
        width=4000,
        height=3000,
        original_name=original_name,
    )


def _result(record: FileRecord, size: int = 2000) -> ResizeResult:
    return ResizeResult(record=record, ok=True, data=b"x" * size, out_width=1920, out_height=1080)


def _settings(dest: Path, **kwargs) -> Settings:
    values = {"source": str(dest.parent / "library"), "dest": str(dest)}
    values.update(kwargs)
    return Settings(**values)


def test_split_into_discs_and_manifest(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    writer = Writer(dest, _settings(dest, disc_limit_gib=0.000001, split_discs=True))

    for index in range(3):
        record = _record(index)
        writer.write(record, _result(record))
    writer.finalize()

    assert (dest / "disc_01").is_dir()
    assert (dest / "disc_02").is_dir()
    assert (dest / "disc_03").is_dir()
    assert (dest / "_REPORT.txt").exists()
    assert (dest / "disc_01" / "README.txt").exists()
    assert (dest / "disc_01" / "MANIFEST.csv").exists()

    with open(dest / "manifest.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == MANIFEST_COLUMNS
    assert len(rows) == 3
    assert [row["disc"] for row in rows] == ["1", "2", "3"]


def test_no_split_writes_into_dest_root(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    writer = Writer(dest, _settings(dest, split_discs=False))
    record = _record(0)

    target = writer.write(record, _result(record))
    writer.finalize()

    assert target.parent == dest / "2019" / "2019-07-04"
    assert target.name == "2019-07-04_121530_IMG_0001.jpg"
    assert not (dest / "disc_00").exists()


def test_duplicate_names_get_suffix(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    writer = Writer(dest, _settings(dest, split_discs=False))
    first = _record(0)
    second = _record(0)

    target_a = writer.write(first, _result(first))
    target_b = writer.write(second, _result(second))
    writer.finalize()

    assert target_a != target_b
    assert target_b.name.endswith("_1.jpg")


def test_resume_reads_manifest(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    record = _record(0)

    writer = Writer(dest, _settings(dest, disc_limit_gib=0.000001))
    writer.write(record, _result(record))
    writer.finalize()

    resumed = Writer(dest, _settings(dest, disc_limit_gib=0.000001))
    assert resumed.already_processed(record)
    assert resumed.current_disc == 1
    resumed.finalize()
