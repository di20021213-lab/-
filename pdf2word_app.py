"""PDF в Word — окно программы.

Запустили → перетащили PDF (или «Выбрать файл») → «Распознать».
Готовый .docx появляется рядом с исходным файлом. Интернет не нужен.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pdf2word import BUILD, __version__
from pdf2word.engine import Cancelled, Engine, OcrError
from pdf2word.imageops import IMAGE_EXT
from pdf2word.pipeline import Options, convert

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # noqa: BLE001 — без перетаскивания тоже работаем
    TkinterDnD = None
    DND_FILES = None

APP_TITLE = "PDF в Word — распознавание"
SUPPORTED = {".pdf"} | IMAGE_EXT


def log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "PDFtoWord")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "log.txt")


def write_log(text: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


def output_path_for(src: str) -> str:
    base = os.path.splitext(src)[0]
    folder = os.path.dirname(src) or "."
    if not os.access(folder, os.W_OK):
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        folder = docs if os.path.isdir(docs) else os.path.expanduser("~")
        base = os.path.join(folder, os.path.splitext(os.path.basename(src))[0])
    out = base + ".docx"
    n = 1
    while os.path.exists(out):
        n += 1
        out = f"{base} ({n}).docx"
    return out


def open_file(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
    except OSError:
        pass


class App:
    def __init__(self, root: tk.Tk, files: list[str]):
        self.root = root
        self.files: list[str] = []
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.engine: Engine | None = None
        self.busy = False

        # версия и дата сборки в заголовке: по ним видно, новая ли программа
        root.title(f"{APP_TITLE} {__version__}" + (f" (сборка {BUILD})" if BUILD else ""))
        root.geometry("620x430")
        root.minsize(520, 380)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", font=("Segoe UI", 12), padding=(18, 10))
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Hint.TLabel", font=("Segoe UI", 10), foreground="#555555")

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="PDF → Word", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Распознаёт сканы и PDF в редактируемый документ Word "
                              "(текст, таблицы, абзацы). Работает без интернета.",
                  style="Hint.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=(2, 10))

        self.drop = tk.Label(
            outer, text="Перетащите сюда PDF-файл\nили нажмите «Выбрать файл»",
            font=("Segoe UI", 13), bg="#f3f6fb", fg="#3a4a63", relief="groove", bd=2,
            height=6, cursor="hand2")
        self.drop.pack(fill="both", expand=True)
        self.drop.bind("<Button-1>", lambda e: self.choose())
        if TkinterDnD is not None:
            try:
                self.drop.drop_target_register(DND_FILES)
                self.drop.dnd_bind("<<Drop>>", self.on_drop)
                root.drop_target_register(DND_FILES)
                root.dnd_bind("<<Drop>>", self.on_drop)
            except Exception:  # noqa: BLE001
                pass

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 4))
        self.btn_choose = ttk.Button(buttons, text="Выбрать файл…", style="Big.TButton",
                                     command=self.choose)
        self.btn_choose.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.btn_run = ttk.Button(buttons, text="Распознать", style="Big.TButton",
                                  command=self.run_or_cancel, state="disabled")
        self.btn_run.pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.stamps = tk.BooleanVar(value=True)
        ttk.Checkbutton(outer, text="Убирать синие печати и подписи (меньше «мусора» в тексте)",
                        variable=self.stamps).pack(anchor="w", pady=(6, 2))

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=1000)
        self.progress.pack(fill="x", pady=(8, 2))
        self.status = ttk.Label(outer, text="Готов к работе", style="Hint.TLabel")
        self.status.pack(anchor="w")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        if files:
            self.set_files(files)
            root.after(300, self.start)

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno(APP_TITLE, "Распознавание ещё идёт. Прервать и закрыть?"):
                return
            if self.engine:
                self.engine.cancel()        # не оставляем висеть процессы Tesseract
        self.root.destroy()

    # ------------------------------------------------------------- файлы
    def on_drop(self, event):
        if self.busy:
            return
        paths = list(self.root.tk.splitlist(event.data))
        self.set_files(paths)
        if self.files:
            self.start()

    def choose(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(
            title="Выберите PDF или скан",
            filetypes=[("PDF и изображения", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                       ("Все файлы", "*.*")])
        if paths:
            self.set_files(list(paths))

    def set_files(self, paths: list[str]):
        good = [p for p in paths if os.path.splitext(p)[1].lower() in SUPPORTED and os.path.isfile(p)]
        bad = [p for p in paths if p not in good]
        if bad and not good:
            messagebox.showwarning(APP_TITLE, "Нужен PDF или картинка (JPG, PNG, TIFF).")
            return
        self.files = good
        if len(good) == 1:
            name = os.path.basename(good[0])
            self.drop.config(text=f"📄 {name}\n\nНажмите «Распознать»")
        else:
            self.drop.config(text=f"📄 Файлов: {len(good)}\n\nНажмите «Распознать»")
        self.btn_run.config(state="normal")
        self.set_status("Файл выбран")

    # ------------------------------------------------------------- работа
    def run_or_cancel(self):
        if self.busy:
            if self.engine:
                self.engine.cancel()
            self.set_status("Отменяю…")
        else:
            self.start()

    def start(self):
        if self.busy or not self.files:
            return
        self.busy = True
        self.btn_run.config(text="Отмена")
        self.btn_choose.config(state="disabled")
        self.progress["value"] = 0
        self.drop.config(text=self.drop.cget("text").replace("Нажмите «Распознать»",
                                                            "Идёт распознавание…"))
        files = list(self.files)
        opts = Options(remove_stamps=self.stamps.get())
        self.worker = threading.Thread(target=self.work, args=(files, opts), daemon=True)
        self.worker.start()

    def work(self, files: list[str], opts: Options):
        results = []
        try:
            self.engine = Engine(opts.langs)
            for i, path in enumerate(files):
                out = output_path_for(path)
                prefix = f"[{i + 1}/{len(files)}] " if len(files) > 1 else ""

                def progress(frac, msg, i=i):
                    total = (i + frac) / len(files)
                    self.queue.put(("progress", total, prefix + msg))

                t0 = time.time()
                convert(path, out, opts, progress, engine=self.engine)
                write_log(f"OK {path} -> {out} ({time.time() - t0:.1f} s)")
                results.append(out)
            self.queue.put(("done", results))
        except Cancelled:
            self.queue.put(("cancelled", results))
        except (OcrError, ValueError) as exc:
            write_log("ERROR " + traceback.format_exc())
            self.queue.put(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001
            write_log("ERROR " + traceback.format_exc())
            self.queue.put(("error", f"{type(exc).__name__}: {exc}"))

    def poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    self.progress["value"] = int(msg[1] * 1000)
                    self.set_status(msg[2])
                elif kind == "done":
                    self.finish()
                    outs = msg[1]
                    self.progress["value"] = 1000
                    if len(outs) == 1:
                        self.set_status("Готово: " + outs[0])
                        if messagebox.askyesno(APP_TITLE, f"Готово!\n\nФайл сохранён:\n{outs[0]}\n\n"
                                                          "Открыть его сейчас?"):
                            open_file(outs[0])
                    else:
                        self.set_status(f"Готово, файлов: {len(outs)}")
                        if messagebox.askyesno(APP_TITLE, f"Готово! Распознано файлов: {len(outs)}.\n"
                                                          "Открыть папку с результатами?"):
                            open_file(os.path.dirname(outs[0]))
                elif kind == "cancelled":
                    self.finish()
                    self.progress["value"] = 0
                    self.set_status("Отменено")
                elif kind == "error":
                    self.finish()
                    self.set_status("Ошибка")
                    messagebox.showerror(APP_TITLE, "Не получилось распознать файл:\n\n"
                                                    f"{msg[1]}\n\nПодробности: {log_path()}")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def finish(self):
        self.busy = False
        self.engine = None
        self.drop.config(text=self.drop.cget("text").replace("Идёт распознавание…",
                                                            "Можно перетащить следующий файл"))
        self.btn_run.config(text="Распознать", state="normal" if self.files else "disabled")
        self.btn_choose.config(state="normal")

    def set_status(self, text: str):
        self.status.config(text=text)


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--cli" in sys.argv:
        from pdf2word.__main__ import main as cli_main
        sys.exit(cli_main(args))
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    try:
        icon = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
                            "app.ico")
        if os.path.isfile(icon) and os.name == "nt":
            root.iconbitmap(icon)
    except tk.TclError:
        pass
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
