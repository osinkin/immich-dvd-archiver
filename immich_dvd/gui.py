from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import load_settings, save_settings
from .i18n import LANGUAGE_NAMES, SUPPORTED, detect_language, set_language, t
from .job import Progress, estimate_job, resolve_paths, run_job
from .models import CancelledError, Settings
from .writer import human_bytes


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return t("time.hours", hours=hours, minutes=minutes)
    if minutes:
        return t("time.minutes", minutes=minutes, seconds=secs)
    return t("time.seconds", seconds=secs)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self._language_code = set_language(self.settings.language or detect_language())
        self._translatable: list[tuple[object, str, dict]] = []

        self.title(t("app.title"))
        self.geometry("860x680")
        self.minsize(800, 640)

        self.queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.running = False
        self.closing = False
        self._estimate_cache: dict | None = None

        self._build()
        self._apply_settings(self.settings)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._poll)

    # --------------------------------------------------------------- interface
    def _label(self, parent, key: str, **kwargs) -> ttk.Label:
        widget = ttk.Label(parent, text=t(key, **kwargs))
        self._translatable.append((widget, key, kwargs))
        return widget

    def _label_frame(self, parent, key: str, padding: int = 8) -> ttk.LabelFrame:
        widget = ttk.LabelFrame(parent, text=t(key), padding=padding)
        self._translatable.append((widget, key, {}))
        return widget

    def _button(self, parent, key: str, command, **kwargs) -> ttk.Button:
        widget = ttk.Button(parent, text=t(key), command=command, **kwargs)
        self._translatable.append((widget, key, {}))
        return widget

    def _check(self, parent, key: str, variable: tk.BooleanVar) -> ttk.Checkbutton:
        widget = ttk.Checkbutton(parent, text=t(key), variable=variable)
        self._translatable.append((widget, key, {}))
        return widget

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        paths = self._label_frame(outer, "gui.paths")
        paths.pack(fill="x")
        paths.columnconfigure(1, weight=1)

        self.source_var = tk.StringVar()
        self.dest_var = tk.StringVar()

        self._label(paths, "gui.source").grid(row=0, column=0, sticky="w", pady=2)
        self.source_entry = ttk.Entry(paths, textvariable=self.source_var)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self.source_btn = self._button(paths, "gui.browse", self._pick_source, width=10)
        self.source_btn.grid(row=0, column=2, pady=2)

        self._label(paths, "gui.dest").grid(row=1, column=0, sticky="w", pady=2)
        self.dest_entry = ttk.Entry(paths, textvariable=self.dest_var)
        self.dest_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.dest_btn = self._button(paths, "gui.browse", self._pick_dest, width=10)
        self.dest_btn.grid(row=1, column=2, pady=2)

        options = self._label_frame(outer, "gui.options")
        options.pack(fill="x", pady=(8, 0))
        for column in (1, 3, 5):
            options.columnconfigure(column, weight=1)

        self.maxw_var = tk.StringVar(value="1920")
        self.maxh_var = tk.StringVar(value="1080")
        self.quality_var = tk.StringVar(value="85")
        self.disc_var = tk.StringVar(value="4.3")
        self.workers_var = tk.StringVar(value="0")
        self.language_var = tk.StringVar()

        self.split_var = tk.BooleanVar(value=True)
        self.exif_var = tk.BooleanVar(value=True)
        self.minimal_var = tk.BooleanVar(value=False)
        self.skip_var = tk.BooleanVar(value=True)

        self._label(options, "gui.max_width").grid(row=0, column=0, sticky="w")
        self.maxw_entry = ttk.Entry(options, textvariable=self.maxw_var, width=8)
        self.maxw_entry.grid(row=0, column=1, sticky="w", padx=(4, 16))
        self._label(options, "gui.max_height").grid(row=0, column=2, sticky="w")
        self.maxh_entry = ttk.Entry(options, textvariable=self.maxh_var, width=8)
        self.maxh_entry.grid(row=0, column=3, sticky="w", padx=(4, 16))
        self._label(options, "gui.quality").grid(row=0, column=4, sticky="w")
        self.quality_entry = ttk.Entry(options, textvariable=self.quality_var, width=6)
        self.quality_entry.grid(row=0, column=5, sticky="w", padx=4)

        self._label(options, "gui.disc_size").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.disc_entry = ttk.Entry(options, textvariable=self.disc_var, width=8)
        self.disc_entry.grid(row=1, column=1, sticky="w", padx=(4, 16), pady=(6, 0))
        self._label(options, "gui.workers").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.workers_entry = ttk.Entry(options, textvariable=self.workers_var, width=6)
        self.workers_entry.grid(row=1, column=3, sticky="w", padx=4, pady=(6, 0))
        self._label(options, "gui.language").grid(row=1, column=4, sticky="w", pady=(6, 0))
        self.language_combo = ttk.Combobox(
            options,
            textvariable=self.language_var,
            state="readonly",
            width=12,
            values=[LANGUAGE_NAMES[code] for code in SUPPORTED],
        )
        self.language_combo.grid(row=1, column=5, sticky="w", padx=4, pady=(6, 0))
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_change)

        checks = ttk.Frame(options)
        checks.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self.split_check = self._check(checks, "gui.split", self.split_var)
        self.split_check.pack(side="left", padx=(0, 14))
        self.exif_check = self._check(checks, "gui.exif", self.exif_var)
        self.exif_check.pack(side="left", padx=(0, 14))
        self.minimal_check = self._check(checks, "gui.minimal_exif", self.minimal_var)
        self.minimal_check.pack(side="left", padx=(0, 14))
        self.skip_check = self._check(checks, "gui.skip_existing", self.skip_var)
        self.skip_check.pack(side="left")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 0))
        self.estimate_btn = self._button(actions, "gui.estimate_btn", self._estimate)
        self.estimate_btn.pack(side="left")
        self.start_btn = self._button(actions, "gui.start_btn", self._start)
        self.start_btn.pack(side="left", padx=6)
        self.cancel_btn = self._button(actions, "gui.cancel_btn", self._cancel)
        self.cancel_btn.configure(state="disabled")
        self.cancel_btn.pack(side="left")

        progress_frame = self._label_frame(outer, "gui.progress")
        progress_frame.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.stats_var = tk.StringVar(value=t("gui.ready"))
        ttk.Label(progress_frame, textvariable=self.stats_var).pack(anchor="w", pady=(4, 0))
        self.current_var = tk.StringVar(value="")
        ttk.Label(progress_frame, textvariable=self.current_var, foreground="#555555").pack(anchor="w")

        log_frame = self._label_frame(outer, "gui.log", padding=4)
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(log_frame, height=10, wrap="none", state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ---------------------------------------------------------------- settings
    def _apply_settings(self, settings: Settings) -> None:
        self.source_var.set(settings.source)
        self.dest_var.set(settings.dest)
        self.maxw_var.set(str(settings.max_width))
        self.maxh_var.set(str(settings.max_height))
        self.quality_var.set(str(settings.jpeg_quality))
        self.disc_var.set(f"{settings.disc_limit_gib:g}")
        self.workers_var.set(str(settings.workers))
        self.split_var.set(settings.split_discs)
        self.exif_var.set(settings.keep_exif)
        self.minimal_var.set(settings.minimal_exif)
        self.skip_var.set(settings.skip_existing)
        self.language_var.set(LANGUAGE_NAMES.get(self._language_code, LANGUAGE_NAMES["en"]))

    def _collect_settings(self) -> Settings:
        try:
            max_w = int(self.maxw_var.get())
            max_h = int(self.maxh_var.get())
            quality = int(self.quality_var.get())
            disc = float(self.disc_var.get().replace(",", "."))
            workers = int(self.workers_var.get())
        except ValueError as exc:
            raise ValueError(t("gui.numbers_error")) from exc

        if not (64 <= max_w <= 20000 and 64 <= max_h <= 20000):
            raise ValueError(t("gui.max_range"))
        if not (50 <= quality <= 95):
            raise ValueError(t("gui.quality_range"))
        if not (0.1 <= disc <= 100):
            raise ValueError(t("gui.disc_range"))
        if not (0 <= workers <= 32):
            raise ValueError(t("gui.workers_range"))

        settings = Settings(
            source=self.source_var.get().strip(),
            dest=self.dest_var.get().strip(),
            max_width=max_w,
            max_height=max_h,
            jpeg_quality=quality,
            disc_limit_gib=disc,
            split_discs=self.split_var.get(),
            keep_exif=self.exif_var.get(),
            minimal_exif=self.minimal_var.get(),
            skip_existing=self.skip_var.get(),
            workers=workers,
            language=self._language_code,
        )
        if not settings.source or not settings.dest:
            raise ValueError(t("gui.choose_dirs"))
        resolve_paths(settings)
        return settings

    def _on_language_change(self, event=None) -> None:  # noqa: ANN001, ARG002
        name = self.language_var.get()
        code = next((item for item in SUPPORTED if LANGUAGE_NAMES[item] == name), "en")
        set_language(code)
        self._language_code = code
        saved = load_settings()
        saved.language = code
        save_settings(saved)
        self.settings.language = code
        self._retranslate()

    def _retranslate(self) -> None:
        self.title(t("app.title"))
        for widget, key, kwargs in self._translatable:
            try:
                widget.configure(text=t(key, **kwargs))
            except tk.TclError:
                pass
        if not self.running:
            self.stats_var.set(t("gui.ready"))

    # ----------------------------------------------------------------- actions
    def _pick_source(self) -> None:
        path = filedialog.askdirectory(title=t("gui.source_dialog"), parent=self)
        if path:
            self.source_var.set(path)

    def _pick_dest(self) -> None:
        path = filedialog.askdirectory(title=t("gui.dest_dialog"), parent=self)
        if path:
            self.dest_var.set(path)

    def _estimate(self) -> None:
        if self.running:
            return
        try:
            settings = self._collect_settings()
        except ValueError as exc:
            messagebox.showerror(t("gui.settings_title"), str(exc), parent=self)
            return
        save_settings(settings)
        self._begin("gui.phase_estimate")
        self.worker_thread = threading.Thread(
            target=self._estimate_worker, args=(settings,), daemon=True
        )
        self.worker_thread.start()

    def _start(self) -> None:
        if self.running:
            return
        try:
            settings = self._collect_settings()
        except ValueError as exc:
            messagebox.showerror(t("gui.settings_title"), str(exc), parent=self)
            return
        save_settings(settings)

        prepared_scan = None
        cache = self._estimate_cache
        if cache is not None:
            try:
                source, _ = resolve_paths(settings)
            except ValueError:
                source = None
            if source is not None and cache.get("scan") is not None and cache["scan"].source == str(source):
                stamp = cache.get("scanned_at")
                stamp_text = stamp.strftime("%H:%M:%S") if stamp else "—"
                reuse = messagebox.askyesno(
                    t("gui.reuse_title"),
                    t("gui.reuse_text", count=len(cache["scan"].files), time=stamp_text),
                    parent=self,
                )
                if reuse:
                    prepared_scan = cache["scan"]
                else:
                    self._estimate_cache = None
            else:
                self._estimate_cache = None

        self._begin("gui.phase_process")
        self.worker_thread = threading.Thread(
            target=self._run_worker, args=(settings, prepared_scan), daemon=True
        )
        self.worker_thread.start()

    def _cancel(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled")
        self.stats_var.set(t("gui.cancelling"))
        self._log(t("gui.cancel_requested"))

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                t("gui.busy_title"),
                t("gui.busy_close"),
                parent=self,
            ):
                return
            self.closing = True
            self.cancel_event.set()
            self.stats_var.set(t("gui.finishing"))
            return
        self.destroy()

    # ----------------------------------------------------------------- workers
    def _estimate_worker(self, settings: Settings) -> None:
        try:
            result = estimate_job(
                settings,
                on_scan=lambda count: self.queue.put(("scan", count)),
                on_log=lambda message: self.queue.put(("log", message)),
                cancelled=self.cancel_event.is_set,
            )
            self.queue.put(("estimate", result))
        except CancelledError:
            self.queue.put(("cancelled", None))
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self.queue.put(("failed", f"{type(exc).__name__}: {exc}"))

    def _run_worker(self, settings: Settings, prepared_scan=None) -> None:
        try:
            summary = run_job(
                settings,
                on_phase=lambda phase: self.queue.put(("phase", phase)),
                on_scan=lambda count: self.queue.put(("scan", count)),
                on_progress=lambda progress: self.queue.put(("progress", progress)),
                on_log=lambda message: self.queue.put(("log", message)),
                cancelled=self.cancel_event.is_set,
                prepared_scan=prepared_scan,
            )
            self.queue.put(("done", summary))
        except CancelledError:
            self.queue.put(("cancelled", None))
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self.queue.put(("failed", f"{type(exc).__name__}: {exc}"))

    # -------------------------------------------------------------------- queue
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        if self.closing and not self.running:
            self.destroy()
            return
        self.after(120, self._poll)

    def _handle(self, kind: str, payload) -> None:
        if kind == "log":
            self._log(str(payload))
        elif kind == "scan":
            self.stats_var.set(t("gui.scanning", count=payload))
        elif kind == "phase":
            if payload == "process":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=100, value=0)
        elif kind == "progress":
            self._on_progress(payload)
        elif kind == "estimate":
            self._finish()
            self._estimate_cache = payload
            self._show_estimate(payload)
        elif kind == "done":
            self._finish()
            self._estimate_cache = None
            self._show_summary(payload)
        elif kind == "cancelled":
            self._finish()
            self._estimate_cache = None
            self._log(t("gui.cancelled"))
            self.stats_var.set(t("gui.cancelled_state"))
        elif kind == "failed":
            self._finish()
            self._estimate_cache = None
            self._log(t("gui.error_prefix", message=payload))
            messagebox.showerror(t("gui.error_title"), str(payload), parent=self)

    def _on_progress(self, progress: Progress) -> None:
        if str(self.progress.cget("mode")) != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100)
        percent = progress.done / progress.total * 100 if progress.total else 0
        self.progress.configure(value=percent)
        speed = progress.done / progress.elapsed if progress.elapsed > 0 else 0
        disc = t("gui.disc_suffix", disc=progress.disc) if self.split_var.get() else ""
        self.stats_var.set(
            t(
                "gui.stats",
                done=progress.done,
                total=progress.total,
                percent=percent,
                size=human_bytes(progress.out_bytes),
                speed=speed,
                eta=human_time(progress.eta),
                disc=disc,
            )
        )
        self.current_var.set(t("gui.current_file", name=progress.current[-90:]))

    # ------------------------------------------------------------------ helpers
    def _begin(self, phase_key: str) -> None:
        self.running = True
        self.cancel_event.clear()
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.progress.start(12)
        self.stats_var.set(t(phase_key))
        self.current_var.set("")
        self._set_controls(False)
        self._log("—" * 60)
        self._log(t(phase_key))

    def _finish(self) -> None:
        self.running = False
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.current_var.set("")
        self._set_controls(True)

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        widgets = (
            self.source_entry, self.dest_entry, self.source_btn, self.dest_btn,
            self.maxw_entry, self.maxh_entry, self.quality_entry, self.disc_entry, self.workers_entry,
            self.split_check, self.exif_check, self.minimal_check, self.skip_check,
            self.estimate_btn, self.start_btn,
        )
        for widget in widgets:
            widget.configure(state=state)
        self.language_combo.configure(state="readonly" if enabled else "disabled")
        self.cancel_btn.configure(state="disabled" if enabled else "normal")

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _show_estimate(self, result: dict) -> None:
        free = result.get("free_bytes")
        free_text = human_bytes(free) if free is not None else "n/a"
        text = t(
            "gui.estimate_text",
            files=result["files"],
            remaining=result["remaining"],
            resize=result["resize_count"],
            copy=result["copy_count"],
            skipped=result["skipped"],
            size=human_bytes(result["est_bytes"]),
            discs=result["discs"],
            free=free_text,
        )
        if free is not None and result["est_bytes"] > free:
            text += "\n\n" + t("gui.estimate_warning")
        text += "\n\n" + t("gui.estimate_saved")
        self._log(text.replace("\n", " | "))
        messagebox.showinfo(t("gui.estimate_title"), text, parent=self)

    def _show_summary(self, summary: dict) -> None:
        text = t(
            "gui.done_text",
            processed=summary["processed"],
            total=summary["total"],
            size=human_bytes(summary["out_bytes"]),
            discs=summary["discs"],
            errors=summary["errors"],
            time=human_time(summary["elapsed"]),
        )
        self._log(text.replace("\n", " | "))
        self.stats_var.set(t("gui.done_title"))
        messagebox.showinfo(t("gui.done_title"), text, parent=self)


def main() -> None:
    app = App()
    app.mainloop()
