# Immich DVD Archiver

[![CI](https://github.com/osinkin/immich-dvd-archiver/actions/workflows/ci.yml/badge.svg)](https://github.com/osinkin/immich-dvd-archiver/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)](#requirements)

**Русская версия:** [README.ru.md](README.ru.md)

Resizes photos from an [Immich](https://immich.app/) library to fit a 1920×1080 box and
splits the result into DVD-sized folders. The source library is opened **read-only** and
is never modified.

The tool is designed for archiving an Immich library to optical media: it keeps the
original capture date in the folder layout, packs files into discs of a configurable
size, and can resume after an interruption without reprocessing finished files.

## Features

- Fits images into a 1920×1080 box while preserving the aspect ratio; never upscales.
- Organizes output by EXIF capture date: `<year>/<year-month-day>/<date_time_name>.jpg`.
- Splits output into `disc_01`, `disc_02`, … folders with a configurable size limit
  (4.3 GiB by default, the practical capacity of a DVD-R).
- Converts PNG, WebP, TIFF, BMP and HEIC/HEIF to JPEG; flattens transparency on white;
  copies already-small JPEGs byte-for-byte without recompression.
- Keeps EXIF metadata (minus the orientation tag), with an optional minimal mode that
  drops MakerNotes and GPS.
- Skips RAW files and videos, and records them in `skipped.csv`.
- Resumes from `manifest.csv`; atomic writes leave no partially written files.
- Estimates the result size and disc count without writing anything, then offers to
  reuse the scan list when you press Start.
- Runs on Windows and Linux, with both a Tkinter GUI and a headless CLI.
- Russian and English interface.

## Requirements

- Python 3.10 or newer (tested on 3.11 and 3.12).
- Pillow and pillow-heif (installed from `requirements.txt` or as package dependencies).
- Tkinter only for the GUI. It ships with the official Windows Python installer; on
  Linux install it separately (`sudo apt install python3-tk`).

## Installation

```bash
git clone https://github.com/osinkin/immich-dvd-archiver.git
cd immich-dvd-archiver
python -m pip install -r requirements.txt
```

Or install it as a package with the `immich-dvd` command:

```bash
python -m pip install .
immich-dvd --help
```

### Windows

```bat
run.bat
```

or

```bat
python -m immich_dvd
```

### Linux

```bash
./run.sh              # GUI
# or
python3 -m immich_dvd
```

## Usage

### GUI

1. **Immich library** — the `library` folder (for example `\\server\immich\library`) or a
   single user folder inside it. The Immich data root also works: service directories
   such as `thumbs`, `encoded-video`, `upload`, `profile` and `.immich` are skipped
   automatically.
2. **Output folder** — a local disk or another share. It must not be inside the library.
3. **Estimate** — a quick read-only pass: number of files, expected size, disc count and
   free space in the destination.
4. **Start** — processes the library. The progress bar shows percentage, output size,
   speed and ETA. **Cancel** stops after the current file; running again continues from
   the last written file. If you ran an estimate first, the program offers to reuse the
   collected file list instead of scanning the library again.

### CLI

```bash
# Estimate only, write nothing
python3 -m immich_dvd --no-gui \
  --source /mnt/immich/library --dest /mnt/archive --estimate

# Process the library
python3 -m immich_dvd --no-gui \
  --source /mnt/immich/library --dest /mnt/archive --disc-size 4.3
```

All options are listed in `python3 -m immich_dvd --help`:

| Option | Description |
| --- | --- |
| `--source PATH` | Immich library folder (read-only) |
| `--dest PATH` | Output folder |
| `--estimate` | Scan and print an estimate; write nothing |
| `--no-gui` / `--gui` | Force headless or graphical mode |
| `--lang {ru,en}` | Interface language |
| `--max-width PX`, `--max-height PX` | Bounding box (default 1920×1080) |
| `--quality N` | JPEG quality, 50–95 (default 85) |
| `--disc-size GIB` | Disc size limit in GiB (default 4.3) |
| `--split` / `--no-split` | Enable or disable disc folders |
| `--exif` / `--no-exif` | Keep or drop EXIF metadata |
| `--minimal-exif` | Keep only basic EXIF tags (no MakerNotes/GPS) |
| `--skip-existing` / `--no-skip-existing` | Skip files already in `manifest.csv` |
| `--workers N` | Worker processes (0 = auto) |
| `--quiet` | Print only warnings and the final summary |

If no graphical display is available, the program prints a hint and suggests `--no-gui`.
Ctrl+C stops after the current file; the next run continues from where it stopped.

## Output layout

```
dest/
  disc_01/
    2019/
      2019-07-04/
        2019-07-04_121530_IMG_0421.jpg
    MANIFEST.csv
    README.txt
  disc_02/
    ...
  manifest.csv          # global list: source → result, sizes, disc
  skipped.csv           # RAW, video and other skipped files
  errors.csv            # files that could not be read or processed
  _REPORT.txt           # final summary
```

- The date comes from EXIF (`DateTimeOriginal` → `DateTimeDigitized` → `DateTime`),
  otherwise from the file modification time.
- The file name is the capture date/time plus the original name when Immich kept an
  `.xmp` sidecar, otherwise the first 8 characters of the Immich asset ID.
- Images are fitted into the 1920×1080 box with the aspect ratio preserved and **never
  upscaled**. A portrait photo becomes 1080×1920; a 4:3 frame becomes 1440×1080.
- Everything is saved as JPEG (quality 85 by default, configurable). PNG/WebP/TIFF/BMP/HEIC
  are converted, transparency is composited on white, and animated GIF/WebP uses the
  first frame.
- JPEGs that already fit the box are copied byte-for-byte without recompression.
- EXIF is kept (the Orientation tag is removed). The minimal mode keeps only the main
  camera and capture fields and drops MakerNotes and GPS.
- Disc boundaries follow the actual output size; a boundary may fall inside a single day.
  The default 4.3 GiB limit matches the practical capacity of a DVD-R.

## Resume and safety

- `manifest.csv` is the source of truth. On a repeated run, files already written are
  skipped and disc counters are restored.
- Writes go through `*.tmp` files and atomic renames, so no partially written files are
  left behind.
- The source is opened read-only. The program refuses to run if the destination is
  inside the source or the source is inside the destination.
- Immich can keep running: files are only read and nothing is locked. If Immich deletes
  a photo during processing, the file is recorded in `errors.csv`.

## Limitations

- RAW files (`.dng`, `.cr2`, `.arw`, …) and videos are not processed; they are listed in
  `skipped.csv`.
- Immich replaces original file names with UUIDs; the human-readable name can only be
  recovered when an `.xmp` sidecar exists.
- The size estimate is approximate (±20%); the exact JPEG size depends on the image
  content.
- EXIF time zones are ignored: the date stays local, as recorded by the camera.

## Performance

Processing uses several worker processes (by default `min(CPU, 8)`). When working over the
network, reading many small files from a share is the bottleneck; 4–8 workers usually
speed things up significantly. The **Workers** field lets you tune this for a specific
share (0 = auto).

## Interface language

- In the GUI, use the **Language** selector in the **Options** block (Русский / English).
  The choice is stored in `config.json`.
- In the CLI, use `--lang ru` or `--lang en`.
- When no language is set, it is detected from the system locale (`LANG`/`LC_ALL`),
  otherwise English is used.

Settings are saved to `config.json` in the per-user config folder
(`%APPDATA%\immich-dvd` on Windows, `~/.config/immich-dvd` on Linux). A `config.json` next
to the package is still used when it already exists, and `IMMICH_DVD_CONFIG` can point to
a custom file.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

The tests cover scanning, resizing, EXIF handling, disc packing, resume logic, the
estimate/scan reuse path and translation catalogues. Multiprocessing is replaced by an
inline pool in tests so they run on Windows and Linux without spawn side effects.

## Project structure

```
immich_dvd/
  gui.py       # Tkinter window, progress, log
  cli.py       # argparse entry point and headless mode
  job.py       # orchestration, estimate, process pool
  scanner.py   # library walk, EXIF dates, filters
  resizer.py   # resize and conversion (worker)
  writer.py    # discs, manifest, reports, resume
  config.py    # settings persisted in config.json
  i18n.py      # Russian/English strings
  models.py    # shared data structures
tests/         # pytest suite
```

## License

[MIT](LICENSE)
