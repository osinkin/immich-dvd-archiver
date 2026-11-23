from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from . import __version__
from .config import load_settings
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
        return "source folder is not set (use --source)"
    if not settings.dest.strip():
        return "destination folder is not set (use --dest)"
    if not 50 <= settings.jpeg_quality <= 95:
        return "--quality must be between 50 and 95"
    if settings.disc_limit_gib <= 0:
        return "--disc-size must be positive"
    if settings.workers < 0:
        return "--workers must be 0 or greater"
    return None


def _install_sigint(cancel_event: threading.Event) -> None:
    def handler(signum, frame):  # noqa: ANN001, ARG001
        print("\nCancelling, waiting for the current file…", file=sys.stderr)
        cancel_event.set()

    try:
        signal.signal(signal.SIGINT, handler)
    except (ValueError, OSError):
        pass


def _print_estimate(result: dict) -> None:
    free = result.get("free_bytes")
    print(f"Source:            {result['source']}")
    print(f"Destination:       {result['dest']}")
    print(f"Images found:      {result['files']}")
    print(f"To process:        {result['remaining']}")
    print(f"Will be resized:   {result['resize_count']}")
    print(f"Copied as is:      {result['copy_count']}")
    print(f"Skipped RAW/video: {result['skipped']}")
    print(f"Scan errors:       {result['scan_errors']}")
    print(f"Estimated size:    ~{human_bytes(result['est_bytes'])}")
    print(f"Discs:             {result['discs']}")
    print(f"Free space:        {human_bytes(free) if free is not None else 'n/a'}")


def run_cli(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    problem = _validate(settings)
    if problem is not None:
        print(f"Error: {problem}", file=sys.stderr)
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
                on_scan=lambda count: None if args.quiet else print(f"\rScanning… {count} images", end="", file=sys.stderr),
                on_log=log,
                cancelled=cancel_event.is_set,
            )
            if not args.quiet:
                print("", file=sys.stderr)
            _print_estimate(result)
            return 0

        started = time.monotonic()
        last_print = 0.0

        def on_progress(progress) -> None:  # noqa: ANN001
            nonlocal last_print
            now = time.monotonic()
            if args.quiet or (now - last_print < 1.0 and progress.done != progress.total):
                return
            last_print = now
            percent = progress.done / progress.total * 100 if progress.total else 0
            speed = progress.done / progress.elapsed if progress.elapsed > 0 else 0
            print(
                f"\r{progress.done}/{progress.total} ({percent:.0f}%) · "
                f"{human_bytes(progress.out_bytes)} · {speed:.1f} files/s · "
                f"disc {progress.disc}",
                end="",
                file=sys.stderr,
                flush=True,
            )

        summary = run_job(
            settings,
            on_scan=lambda count: None if args.quiet else print(f"\rScanning… {count} images", end="", file=sys.stderr),
            on_progress=on_progress,
            on_log=log,
            cancelled=cancel_event.is_set,
        )
        if not args.quiet:
            print("", file=sys.stderr)
        print(
            f"Done: {summary['processed']} of {summary['total']} files, "
            f"{human_bytes(summary['out_bytes'])}, {summary['discs']} disc(s), "
            f"{summary['errors']} error(s), {summary['elapsed']:.0f} s "
            f"(total {time.monotonic() - started:.0f} s)"
        )
        return 0
    except CancelledError:
        print("Cancelled. Run again to continue from the last written file.", file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def launch_gui() -> int:
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print(
            f"Cannot start the GUI: {exc}\n"
            "On Linux install Tkinter (e.g. 'sudo apt install python3-tk') "
            "or run with --no-gui.",
            file=sys.stderr,
        )
        return 1
    gui_main()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    wants_cli = args.no_gui or args.estimate or args.source is not None or args.dest is not None
    if args.gui:
        wants_cli = False

    if not wants_cli:
        if has_display():
            return launch_gui()
        print(
            "No graphical display detected.\n"
            "Use --no-gui with --source/--dest, for example:\n"
            "  immich-dvd --no-gui --source /mnt/immich/library --dest /mnt/archive\n"
            "Run with --help for all options.",
            file=sys.stderr,
        )
        return 2

    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
