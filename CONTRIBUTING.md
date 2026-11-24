# Contributing

Thanks for your interest in Immich DVD Archiver. Bug reports, feature ideas and pull
requests are welcome.

## Reporting an issue

Please include:

- operating system and Python version;
- whether you used the GUI or the CLI (and the full command line);
- what you expected to happen and what actually happened;
- relevant lines from the log, `errors.csv` or the terminal output (remove personal paths
  if needed).

Do not attach your photo library. A minimal reproduction with a few generated images is
much more useful.

## Development setup

```bash
git clone https://github.com/osinkin/immich-dvd-archiver.git
cd immich-dvd-archiver
python -m pip install -e ".[dev]"
```

Run the checks before opening a pull request:

```bash
python -m ruff check .
python -m pytest -q
```

## Guidelines

- Keep the source library strictly read-only. Any change that writes into the source must
  be rejected.
- Preserve the resume behaviour: `manifest.csv` is the source of truth and writes must stay
  atomic (`*.tmp` + `os.replace`).
- New user-visible strings belong in `immich_dvd/i18n.py` for both `ru` and `en`.
- Add or update tests in `tests/` for behaviour changes. Tests must not depend on a GUI or
  on real multiprocessing (use the inline pool pattern from `tests/test_job.py`).
- Follow the existing code style; `ruff` is the source of truth for formatting and imports.

## Commit messages

Short, imperative summaries are preferred, for example:

- `feat: add CLI and Linux/headless support`
- `fix: keep EXIF orientation when resizing`
- `docs: translate README to English`
