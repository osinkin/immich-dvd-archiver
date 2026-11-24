from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from immich_dvd import job
from immich_dvd.i18n import set_language
from immich_dvd.job import estimate_job, resolve_paths, run_job
from immich_dvd.models import CancelledError, Settings


class _InlinePool:
    """Runs the worker synchronously so tests do not need spawn processes."""

    def __init__(self, processes=None, initializer=None, initargs=()):
        if initializer is not None:
            initializer(*initargs)

    def imap(self, func, iterable, chunksize=1):
        for item in iterable:
            yield func(item)

    def close(self) -> None:
        pass

    def terminate(self) -> None:
        pass

    def join(self) -> None:
        pass


class _InlineContext:
    def Pool(self, **kwargs) -> _InlinePool:
        return _InlinePool(**kwargs)


@pytest.fixture
def inline_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job.mp, "get_context", lambda method: _InlineContext())
    set_language("en")


def _library(root: Path, count: int = 2) -> Path:
    library = root / "library"
    library.mkdir()
    for index in range(count):
        image = Image.new("RGB", (2400, 1600), (index * 40, 90, 30))
        exif = Image.Exif()
        exif[36867] = f"2018:05:0{index + 1} 12:00:00"
        image.save(library / f"asset-{index}.jpg", "JPEG", exif=exif)
    return library


def _settings(library: Path, dest: Path, **kwargs) -> Settings:
    values = {"source": str(library), "dest": str(dest), "workers": 1, "split_discs": False}
    values.update(kwargs)
    return Settings(**values)


def test_run_job_end_to_end(tmp_path: Path, inline_pool: None) -> None:
    library = _library(tmp_path)
    dest = tmp_path / "dest"
    phases: list[str] = []
    logs: list[str] = []

    summary = run_job(
        _settings(library, dest),
        on_phase=phases.append,
        on_log=logs.append,
    )

    assert summary["total"] == 2
    assert summary["processed"] == 2
    assert summary["errors"] == 0
    assert summary["discs"] == 1
    assert phases == ["scan", "process"]
    assert (dest / "manifest.csv").exists()
    assert (dest / "_REPORT.txt").exists()
    assert len(list(dest.rglob("*.jpg"))) == 2
    assert any("Done in" in line for line in logs)


def test_run_job_reuses_prepared_scan(tmp_path: Path, inline_pool: None) -> None:
    library = _library(tmp_path)
    settings = _settings(library, tmp_path / "dest")

    estimate = estimate_job(settings)
    phases: list[str] = []
    logs: list[str] = []
    summary = run_job(settings, on_phase=phases.append, on_log=logs.append, prepared_scan=estimate["scan"])

    assert summary["processed"] == 2
    assert phases == ["process"]
    assert any("Using the scan from the estimate" in line for line in logs)


def test_run_job_ignores_scan_from_another_source(tmp_path: Path, inline_pool: None) -> None:
    library = _library(tmp_path)
    settings = _settings(library, tmp_path / "dest")
    estimate = estimate_job(settings)
    estimate["scan"].source = "C:/somewhere/else"

    phases: list[str] = []
    run_job(settings, on_phase=phases.append, prepared_scan=estimate["scan"])

    assert phases == ["scan", "process"]


def test_run_job_skips_existing_on_second_run(tmp_path: Path, inline_pool: None) -> None:
    library = _library(tmp_path)
    settings = _settings(library, tmp_path / "dest")
    run_job(settings)

    summary = run_job(settings)

    assert summary["total"] == 0
    assert summary["processed"] == 0


def test_run_job_can_be_cancelled(tmp_path: Path, inline_pool: None) -> None:
    library = _library(tmp_path)
    settings = _settings(library, tmp_path / "dest")

    with pytest.raises(CancelledError):
        run_job(settings, cancelled=lambda: True)


def test_resolve_paths_rejects_dangerous_layouts(tmp_path: Path) -> None:
    library = _library(tmp_path, count=1)

    with pytest.raises(ValueError):
        resolve_paths(Settings(source=str(library), dest=str(library / "out")))
    with pytest.raises(ValueError):
        resolve_paths(Settings(source=str(library), dest=str(library)))
    with pytest.raises(ValueError):
        resolve_paths(Settings(source=str(library / "missing"), dest=str(tmp_path / "out")))
    with pytest.raises(ValueError):
        resolve_paths(Settings(source="", dest=str(tmp_path / "out")))


def test_estimate_reports_counts(tmp_path: Path, inline_pool: None) -> None:
    library = _library(tmp_path)
    result = estimate_job(_settings(library, tmp_path / "dest"))

    assert result["files"] == 2
    assert result["remaining"] == 2
    assert result["resize_count"] == 2
    assert result["discs"] == 1
    assert result["scan"].source == str(library.resolve())
    assert isinstance(result["scanned_at"], datetime)
