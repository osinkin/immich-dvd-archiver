from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import threading
import time

from . import __version__
from .config import load_settings
from .i18n import SUPPORTED, detect_language, set_language, t
from .job import estimate_job, run_job
from .models import CancelledError, Settings
from .writer import human_bytes


def has_display() -> bool:
    if sys.platform.startswith(("win", "darwin")):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="immich-dvd",
        description="Resize an Immich photo library to 1920x1080 JPEG and split it into DVD-sized folders.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    parser.add_argument("--source", metavar="PATH", help="Immich library folder (read-only)")
    parser.add_argument("--dest", metavar="PATH", help="output folder")
    parser.add_argument("--estimate", action="store_true", help="scan and print an estimate, do not write files")
    parser.add_argument("--no-gui", action="store_true", help="run without the graphical interface")
    parser.add_argument("--gui", action="store_true", help="force the graphical interface")
    parser.add_argument("--lang", choices=SUPPORTED, help="interface language (ru or en)")

    parser.add_argument("--max-width", type=int, metavar="PX", help="maximum width of the output image")
    parser.add_argument("--max-height", type=int, metavar="PX", help="maximum height of the output image")
    parser.add_argument("--quality", type=int, metavar="N", help="JPEG quality (50-95)")
    parser.add_argument("--disc-size", type=float, metavar="GIB", help="disc size limit in GiB")
    parser.add_argument("--split", action=argparse.BooleanOptionalAction, help="split output into disc_NN folders")
    parser.add_argument("--exif", action=argparse.BooleanOptionalAction, help="keep EXIF metadata")
    parser.add_argument("--minimal-exif", action="store_true", help="keep only basic EXIF tags (drops MakerNotes/GPS)")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        help="skip files already listed in manifest.csv",
    )
    parser.add_argument("--workers", type=int, metavar="N", help="worker processes (0 = auto)")
    parser.add_argument("--quiet", action="store_true", help="print only warnings and the final summary")
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    settings = load_settings()
    if args.source is not None:
        settings.source = args.source
    if args.dest is not None:
        settings.dest = args.dest
    if args.max_width is not None:
        settings.max_width = args.max_width
    if args.max_height is not None:
        settings.max_height = args.max_height
    if args.quality is not None:
        settings.jpeg_quality = args.quality
    if args.disc_size is not None:
        settings.disc_limit_gib = args.disc_size
    if args.split is not None:
        settings.split_discs = args.split
    if args.exif is not None:
        settings.keep_exif = args.exif
    if args.minimal_exif:
        settings.minimal_exif = True
    if args.skip_existing is not None:
        settings.skip_existing = args.skip_existing
    if args.workers is not None:
        settings.workers = args.workers
    return settings


def _validate(settings: Settings) -> str | None:
    if not settings.source.strip():
        return "cli.err_no_source"
    if not settings.dest.strip():
        return "cli.err_no_dest"
    if not 50 <= settings.jpeg_quality <= 95:
        return "cli.err_quality"
    if settings.disc_limit_gib <= 0:
        return "cli.err_disc"
    if settings.workers < 0:
        return "cli.err_workers"
    return None


def _install_sigint(cancel_event: threading.Event) -> None:
    def handler(signum, frame):
        print("\n" + t("cli.cancel_wait"), file=sys.stderr)
        cancel_event.set()

    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGINT, handler)


def _print_estimate(result: dict) -> None:
    free = result.get("free_bytes")
    print(t("cli.est_source", value=result["source"]))
    print(t("cli.est_dest", value=result["dest"]))
    print(t("cli.est_files", value=result["files"]))
    print(t("cli.est_remaining", value=result["remaining"]))
    print(t("cli.est_resize", value=result["resize_count"]))
    print(t("cli.est_copy", value=result["copy_count"]))
    print(t("cli.est_skipped", value=result["skipped"]))
    print(t("cli.est_scan_errors", value=result["scan_errors"]))
    print(t("cli.est_size", value=human_bytes(result["est_bytes"])))
    print(t("cli.est_discs", value=result["discs"]))
    print(t("cli.est_free", value=human_bytes(free) if free is not None else "n/a"))


def run_cli(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    problem = _validate(settings)
    if problem is not None:
        print(t("cli.error", message=t(problem)), file=sys.stderr)
        return 2

    cancel_event = threading.Event()
    _install_sigint(cancel_event)

    def log(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    try:
        if args.estimate:
            result = estimate_job(
                settings,
                on_scan=lambda count: None
                if args.quiet
                else print("\r" + t("cli.scanning", count=count), end="", file=sys.stderr),
                on_log=log,
                cancelled=cancel_event.is_set,
            )
            if not args.quiet:
                print("", file=sys.stderr)
            _print_estimate(result)
            return 0

        started = time.monotonic()
        last_print = 0.0

        def on_progress(progress) -> None:
            nonlocal last_print
            now = time.monotonic()
            if args.quiet or (now - last_print < 1.0 and progress.done != progress.total):
                return
            last_print = now
            percent = progress.done / progress.total * 100 if progress.total else 0
            speed = progress.done / progress.elapsed if progress.elapsed > 0 else 0
            print(
                "\r"
                + t(
                    "cli.progress",
                    done=progress.done,
                    total=progress.total,
                    percent=percent,
                    size=human_bytes(progress.out_bytes),
                    speed=speed,
                    disc=progress.disc,
                ),
                end="",
                file=sys.stderr,
                flush=True,
            )

        summary = run_job(
            settings,
            on_scan=lambda count: None
            if args.quiet
            else print("\r" + t("cli.scanning", count=count), end="", file=sys.stderr),
            on_progress=on_progress,
            on_log=log,
            cancelled=cancel_event.is_set,
        )
        if not args.quiet:
            print("", file=sys.stderr)
        print(
            t(
                "cli.done",
                processed=summary["processed"],
                total=summary["total"],
                size=human_bytes(summary["out_bytes"]),
                discs=summary["discs"],
                errors=summary["errors"],
                seconds=summary["elapsed"],
                total_seconds=time.monotonic() - started,
            )
        )
        return 0
    except CancelledError:
        print(t("cli.cancelled"), file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print(t("cli.interrupted"), file=sys.stderr)
        return 130
    except Exception as exc:
        print(t("cli.error", message=f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1


def launch_gui() -> int:
    try:
        import tkinter

        from .gui import main as gui_main
    except ImportError as exc:
        print(t("cli.tk_missing", error=exc), file=sys.stderr)
        return 1
    try:
        gui_main()
    except tkinter.TclError:
        print(t("cli.no_display"), file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_language(args.lang or load_settings().language or detect_language())

    wants_cli = args.no_gui or args.estimate or args.source is not None or args.dest is not None
    if args.gui:
        wants_cli = False

    if not wants_cli:
        if has_display():
            return launch_gui()
        print(t("cli.no_display"), file=sys.stderr)
        return 2

    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
