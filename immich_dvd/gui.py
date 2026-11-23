from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import load_settings, save_settings
from .job import Progress, estimate_job, resolve_paths, run_job
from .models import CancelledError, Settings
from .writer import human_bytes


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин {secs:02d} с"
    return f"{secs} с"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Immich DVD Archiver")
        self.geometry("840x660")
        self.minsize(780, 620)

        self.queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.running = False
        self.closing = False
        self._estimate_cache: dict | None = None

        self._build()
        self._apply_settings(load_settings())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._poll)

    # --------------------------------------------------------------- interface
    def _build(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        paths = ttk.LabelFrame(outer, text="Папки", padding=8)
        paths.pack(fill="x")
        paths.columnconfigure(1, weight=1)

        self.source_var = tk.StringVar()
        self.dest_var = tk.StringVar()

        ttk.Label(paths, text="Библиотека Immich:").grid(row=0, column=0, sticky="w", pady=2)
        self.source_entry = ttk.Entry(paths, textvariable=self.source_var)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self.source_btn = ttk.Button(paths, text="Обзор…", width=10, command=self._pick_source)
        self.source_btn.grid(row=0, column=2, pady=2)

        ttk.Label(paths, text="Папка результата:").grid(row=1, column=0, sticky="w", pady=2)
        self.dest_entry = ttk.Entry(paths, textvariable=self.dest_var)
        self.dest_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.dest_btn = ttk.Button(paths, text="Обзор…", width=10, command=self._pick_dest)
        self.dest_btn.grid(row=1, column=2, pady=2)

        options = ttk.LabelFrame(outer, text="Параметры", padding=8)
        options.pack(fill="x", pady=(8, 0))
        for column in (1, 3, 5):
            options.columnconfigure(column, weight=1)

        self.maxw_var = tk.StringVar(value="1920")
        self.maxh_var = tk.StringVar(value="1080")
        self.quality_var = tk.StringVar(value="85")
        self.disc_var = tk.StringVar(value="4.3")
        self.workers_var = tk.StringVar(value="0")

        self.split_var = tk.BooleanVar(value=True)
        self.exif_var = tk.BooleanVar(value=True)
        self.minimal_var = tk.BooleanVar(value=False)
        self.skip_var = tk.BooleanVar(value=True)

        ttk.Label(options, text="Макс. ширина:").grid(row=0, column=0, sticky="w")
        self.maxw_entry = ttk.Entry(options, textvariable=self.maxw_var, width=8)
        self.maxw_entry.grid(row=0, column=1, sticky="w", padx=(4, 16))
        ttk.Label(options, text="Макс. высота:").grid(row=0, column=2, sticky="w")
        self.maxh_entry = ttk.Entry(options, textvariable=self.maxh_var, width=8)
        self.maxh_entry.grid(row=0, column=3, sticky="w", padx=(4, 16))
        ttk.Label(options, text="Качество JPEG:").grid(row=0, column=4, sticky="w")
        self.quality_entry = ttk.Entry(options, textvariable=self.quality_var, width=6)
        self.quality_entry.grid(row=0, column=5, sticky="w", padx=4)

        ttk.Label(options, text="Лимит диска, ГиБ:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.disc_entry = ttk.Entry(options, textvariable=self.disc_var, width=8)
        self.disc_entry.grid(row=1, column=1, sticky="w", padx=(4, 16), pady=(6, 0))
        ttk.Label(options, text="Потоков (0 = авто):").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.workers_entry = ttk.Entry(options, textvariable=self.workers_var, width=6)
        self.workers_entry.grid(row=1, column=3, sticky="w", padx=4, pady=(6, 0))

        checks = ttk.Frame(options)
        checks.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self.split_check = ttk.Checkbutton(checks, text="Разбивать на диски", variable=self.split_var)
        self.split_check.pack(side="left", padx=(0, 14))
        self.exif_check = ttk.Checkbutton(checks, text="Сохранять EXIF", variable=self.exif_var)
        self.exif_check.pack(side="left", padx=(0, 14))
        self.minimal_check = ttk.Checkbutton(checks, text="Минимальный EXIF (без MakerNotes/GPS)", variable=self.minimal_var)
        self.minimal_check.pack(side="left", padx=(0, 14))
        self.skip_check = ttk.Checkbutton(checks, text="Пропускать уже готовые", variable=self.skip_var)
        self.skip_check.pack(side="left")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 0))
        self.estimate_btn = ttk.Button(actions, text="Оценить", command=self._estimate)
        self.estimate_btn.pack(side="left")
        self.start_btn = ttk.Button(actions, text="Старт", command=self._start)
        self.start_btn.pack(side="left", padx=6)
        self.cancel_btn = ttk.Button(actions, text="Отмена", state="disabled", command=self._cancel)
        self.cancel_btn.pack(side="left")

        progress_frame = ttk.LabelFrame(outer, text="Прогресс", padding=8)
        progress_frame.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.stats_var = tk.StringVar(value="Готов к работе")
        ttk.Label(progress_frame, textvariable=self.stats_var).pack(anchor="w", pady=(4, 0))
        self.current_var = tk.StringVar(value="")
        ttk.Label(progress_frame, textvariable=self.current_var, foreground="#555555").pack(anchor="w")

        log_frame = ttk.LabelFrame(outer, text="Журнал", padding=4)
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

    def _collect_settings(self) -> Settings:
        try:
            max_w = int(self.maxw_var.get())
            max_h = int(self.maxh_var.get())
            quality = int(self.quality_var.get())
            disc = float(self.disc_var.get().replace(",", "."))
            workers = int(self.workers_var.get())
        except ValueError as exc:
            raise ValueError("Проверьте числовые параметры") from exc

        if not (64 <= max_w <= 20000 and 64 <= max_h <= 20000):
            raise ValueError("Максимальные размеры должны быть в диапазоне 64…20000")
        if not (50 <= quality <= 95):
            raise ValueError("Качество JPEG должно быть от 50 до 95")
        if not (0.1 <= disc <= 100):
            raise ValueError("Лимит диска должен быть от 0.1 до 100 ГиБ")
        if not (0 <= workers <= 32):
            raise ValueError("Потоков: 0 (авто) или от 1 до 32")

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
        )
        if not settings.source or not settings.dest:
            raise ValueError("Выберите папку-источник и папку назначения")
        resolve_paths(settings)
        return settings

    # ----------------------------------------------------------------- actions
    def _pick_source(self) -> None:
        path = filedialog.askdirectory(title="Папка библиотеки Immich", parent=self)
        if path:
            self.source_var.set(path)

    def _pick_dest(self) -> None:
        path = filedialog.askdirectory(title="Папка для результата", parent=self)
        if path:
            self.dest_var.set(path)

    def _estimate(self) -> None:
        if self.running:
            return
        try:
            settings = self._collect_settings()
        except ValueError as exc:
            messagebox.showerror("Проверка настроек", str(exc), parent=self)
            return
        save_settings(settings)
        self._begin("Оценка объёма…")
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
            messagebox.showerror("Проверка настроек", str(exc), parent=self)
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
                    "Список из оценки",
                    f"Использовать список, полученный при оценке?\n\n"
                    f"Изображений: {len(cache['scan'].files)}\n"
                    f"Оценка сделана: {stamp_text}\n\n"
                    "Файлы, добавленные или изменённые после оценки, учтены не будут.\n"
                    "Выберите «Нет», чтобы просканировать библиотеку заново.",
                    parent=self,
                )
                if reuse:
                    prepared_scan = cache["scan"]
                else:
                    self._estimate_cache = None
            else:
                self._estimate_cache = None

        self._begin("Обработка…")
        self.worker_thread = threading.Thread(
            target=self._run_worker, args=(settings, prepared_scan), daemon=True
        )
        self.worker_thread.start()

    def _cancel(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled")
        self.stats_var.set("Отмена…")
        self._log("Запрошена отмена, ожидаем завершения текущего файла…")

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                "Идёт обработка",
                "Прервать обработку и закрыть программу?\n"
                "Уже записанные файлы останутся, повторный запуск продолжит с места остановки.",
                parent=self,
            ):
                return
            self.closing = True
            self.cancel_event.set()
            self.stats_var.set("Завершение…")
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
            self.stats_var.set(f"Сканирование библиотеки: найдено {payload} изображений…")
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
            self._log("Операция отменена.")
            self.stats_var.set("Отменено")
        elif kind == "failed":
            self._finish()
            self._estimate_cache = None
            self._log(f"ОШИБКА: {payload}")
            messagebox.showerror("Ошибка", str(payload), parent=self)

    def _on_progress(self, progress: Progress) -> None:
        if str(self.progress.cget("mode")) != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100)
        percent = progress.done / progress.total * 100 if progress.total else 0
        self.progress.configure(value=percent)
        speed = progress.done / progress.elapsed if progress.elapsed > 0 else 0
        disc = f" · диск {progress.disc}" if self.split_var.get() else ""
        self.stats_var.set(
            f"{progress.done} / {progress.total} ({percent:.0f}%) · "
            f"{human_bytes(progress.out_bytes)} · {speed:.1f} файл/с · "
            f"осталось {human_time(progress.eta)}{disc}"
        )
        self.current_var.set(f"Текущий файл: …{progress.current[-90:]}")

    # ------------------------------------------------------------------ helpers
    def _begin(self, phase: str) -> None:
        self.running = True
        self.cancel_event.clear()
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.progress.start(12)
        self.stats_var.set(phase)
        self.current_var.set("")
        self._set_controls(False)
        self._log("—" * 60)
        self._log(phase)

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
        self.cancel_btn.configure(state="disabled" if enabled else "normal")

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _show_estimate(self, result: dict) -> None:
        free = result.get("free_bytes")
        free_text = human_bytes(free) if free is not None else "н/д"
        text = (
            f"Изображений в библиотеке: {result['files']}\n"
            f"К обработке: {result['remaining']}\n"
            f"Будет уменьшено: {result['resize_count']}\n"
            f"Будет скопировано как есть: {result['copy_count']}\n"
            f"Пропущено (RAW/видео): {result['skipped']}\n"
            f"Ожидаемый объём: ≈ {human_bytes(result['est_bytes'])}\n"
            f"Дисков: {result['discs']}\n"
            f"Свободно в папке назначения: {free_text}"
        )
        if free is not None and result["est_bytes"] > free:
            text += "\n\nВнимание: ожидаемый объём больше свободного места."
        text += "\n\nСписок сохранён: кнопка «Старт» может использовать его без повторного сканирования."
        self._log(text.replace("\n", " | "))
        messagebox.showinfo("Оценка", text, parent=self)

    def _show_summary(self, summary: dict) -> None:
        text = (
            f"Обработано файлов: {summary['processed']} из {summary['total']}\n"
            f"Объём результата: {human_bytes(summary['out_bytes'])}\n"
            f"Дисков: {summary['discs']}\n"
            f"Ошибок: {summary['errors']}\n"
            f"Время: {human_time(summary['elapsed'])}"
        )
        self._log(text.replace("\n", " | "))
        self.stats_var.set("Готово")
        messagebox.showinfo("Готово", text, parent=self)


def main() -> None:
    app = App()
    app.mainloop()
