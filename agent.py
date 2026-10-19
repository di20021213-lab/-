#!/usr/bin/env python3
"""
Локальный ИИ-помощник, который выполняет команды на вашем компьютере.

Вы пишете обычным языком, что нужно сделать («покажи, сколько места на диске»),
ИИ подбирает команду, показывает её, спрашивает разрешения и выполняет.
Потом смотрит на результат и либо отвечает, либо делает следующий шаг.

Модель работает через Ollama (https://ollama.com) прямо на вашем компьютере:
ничего не уходит в интернет, ничего не нужно оплачивать.

Если Ollama не установлена, помощник предложит скачать и установить её сам (Windows),
а если не запущена — запустит.

Нужно: Python 3.8+ (или готовый AI-Helper.exe). Сторонние пакеты не нужны.

Запуск:   python agent.py
Справка:  python agent.py --help
"""

import argparse
import codecs
import datetime
import getpass
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    import readline  # noqa: F401  (стрелки и история ввода в Linux/macOS)
except ImportError:
    pass

VERSION = "1.1.0"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_HOST = "http://localhost:11434"
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
IS_WINDOWS = os.name == "nt"
FROZEN = getattr(sys, "frozen", False)  # запущены из готового .exe

MAX_STEPS = 15              # максимум действий ИИ на одну просьбу
MAX_OUTPUT_FOR_MODEL = 4000  # сколько символов вывода команды показываем модели
HISTORY_LIMIT = 40          # сколько последних сообщений помнит ИИ

YES = {"", "д", "да", "y", "yes", "+", "ок", "ok"}
NO = {"н", "нет", "n", "no", "-"}
ALWAYS = {"в", "всегда", "a", "always"}


# ---------------------------------------------------------------- оформление

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"


def setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if IS_WINDOWS:
        os.system("")  # включает цветной вывод в консоли Windows 10/11
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(f"ИИ-помощник {VERSION}")
        except Exception:
            pass
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        for name in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "CYAN"):
            setattr(Color, name, "")


def say(text, color=""):
    print(f"{color}{text}{Color.RESET if color else ''}")


def ask_yes(question):
    try:
        return input(question).strip().lower() in YES
    except (EOFError, KeyboardInterrupt):
        print()
        return False


class Spinner:
    """Крутилка «ИИ думает...», пока ждём ответа модели."""

    def __init__(self, text):
        self.text = text
        self.stop_event = threading.Event()
        self.thread = None

    def __enter__(self):
        if sys.stdout.isatty():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        return self

    def _run(self):
        frames = "|/-\\"
        i = 0
        while not self.stop_event.wait(0.12):
            sys.stdout.write(f"\r{Color.DIM}{self.text} {frames[i % 4]}{Color.RESET}")
            sys.stdout.flush()
            i += 1

    def __exit__(self, *exc):
        if self.thread:
            self.stop_event.set()
            self.thread.join()
            sys.stdout.write("\r" + " " * (len(self.text) + 4) + "\r")
            sys.stdout.flush()


# ---------------------------------------------------------------- инструменты

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Выполнить команду в терминале компьютера пользователя и получить её вывод.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Команда для выполнения в оболочке пользователя.",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Коротко по-русски: что делает эта команда.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Создать или перезаписать текстовый файл с указанным содержимым.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу."},
                    "content": {"type": "string", "description": "Полное содержимое файла."},
                },
                "required": ["path", "content"],
            },
        },
    },
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

# Команды, которые всегда требуют явного «да», даже в авто-режиме.
DANGEROUS_PATTERNS = [
    r"\brm\s+(-\w+\s+)*-\w*[rR]",          # rm -r, rm -rf
    r"\bsudo\s+rm\b",
    r"\bmkfs",
    r"\bdd\s+.*\bof=",
    r":\(\)\s*\{",                          # fork-бомба
    r"\b(shutdown|reboot|poweroff|halt)\b",
    r"\b(stop|restart)-computer\b",
    r"\bformat\s+[a-z]:",                   # format C:
    r"\bformat-volume\b",
    r"\bclear-disk\b",
    r"\bdiskpart\b",
    r"\bremove-item\b.*-recurse",
    r"\b(del|erase)\b.*\s/s\b",
    r"\b(rd|rmdir)\b.*\s/s\b",
    r"\breg\s+delete\b",
    r"\bchmod\s+(-\w+\s+)*777\s+/",
    r">\s*/dev/(sd|nvme|disk)",
]


def is_dangerous(command):
    return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_PATTERNS)


CD_RE = re.compile(
    r"^\s*(?:cd|chdir|set-location|sl)(?:\s+(?:/d\s+|-(?:literal)?path\s+)?(?P<path>.+?))?\s*$",
    re.IGNORECASE,
)


def parse_cd(command):
    """Если команда — просто смена папки, вернуть путь (или "~"), иначе None."""
    if re.search(r"[;&|\n]", command):
        return None
    m = CD_RE.match(command)
    if not m:
        return None
    path = (m.group("path") or "~").strip().strip("\"'")
    path = re.sub(r"\$env:(\w+)", lambda x: os.environ.get(x.group(1), x.group(0)), path, flags=re.I)
    path = path.replace("$HOME", "~")
    return os.path.expanduser(os.path.expandvars(path or "~"))


def clean_content(text):
    """Убрать «мысли» reasoning-моделей (<think>...</think>)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.strip()


def extract_text_tool_call(content):
    """Некоторые модели пишут вызов инструмента текстом (JSON), а не через API. Разбираем такое."""
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool")
    args = obj.get("arguments", obj.get("parameters", obj.get("args")))
    if name in TOOL_NAMES and isinstance(args, (dict, str)):
        return {"function": {"name": name, "arguments": args}}
    return None


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def shorten_for_model(text):
    text = ANSI_RE.sub("", text).strip()
    if len(text) <= MAX_OUTPUT_FOR_MODEL:
        return text
    head = MAX_OUTPUT_FOR_MODEL * 2 // 3
    tail = MAX_OUTPUT_FOR_MODEL - head
    skipped = len(text) - head - tail
    return f"{text[:head]}\n... [пропущено {skipped} символов] ...\n{text[-tail:]}"


# ---------------------------------------------------------------- запуск команд

def find_shell():
    if IS_WINDOWS:
        path = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        return "PowerShell", path
    path = shutil.which("bash") or "/bin/sh"
    return os.path.basename(path), path


def make_decoder():
    """Декодер вывода: UTF-8, а если не вышло — кодировка консоли Windows."""
    fallback = "latin-1"
    if IS_WINDOWS:
        fallback = "cp866"
        try:
            import ctypes
            candidate = "cp%d" % ctypes.windll.kernel32.GetOEMCP()
            codecs.lookup(candidate)
            fallback = candidate
        except Exception:
            pass
    decoder = codecs.getincrementaldecoder("utf-8")("strict")

    def decode(data, final=False):
        try:
            return decoder.decode(data, final)
        except UnicodeDecodeError:
            decoder.reset()
            return data.decode(fallback, errors="replace")

    return decode


def _descendants(pid):
    try:
        out = subprocess.run(["pgrep", "-P", str(pid)], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, universal_newlines=True).stdout
    except OSError:
        return []
    result = []
    for line in out.split():
        if line.isdigit():
            child = int(line)
            result.append(child)
            result.extend(_descendants(child))
    return result


def kill_tree(proc):
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        for pid in [proc.pid] + _descendants(proc.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_shell(shell_path, command, timeout):
    """Выполнить команду, показывая вывод вживую. Вернуть (вывод, код, статус)."""
    script_path = None
    if IS_WINDOWS:
        # Команду кладём во временный .ps1: так нет проблем с кавычками и кириллицей.
        script = (
            "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}\n"
            "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
            "$ProgressPreference = 'SilentlyContinue'\n"
            f"{command}\n"
            "$__ok = $?\n"
            "if ($LASTEXITCODE) { exit $LASTEXITCODE }\n"
            "if (-not $__ok) { exit 1 }\n"
        )
        fd, script_path = tempfile.mkstemp(suffix=".ps1", prefix="agent_")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(script)
        argv = [shell_path, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", script_path]
    else:
        argv = [shell_path, "-c", command]

    chunks = []
    decode = make_decoder()
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        if script_path:
            os.remove(script_path)
        return f"Не удалось запустить оболочку: {e}", -1, "error"

    def reader():
        while True:
            data = proc.stdout.read1(4096)
            if not data:
                break
            text = decode(data)
            chunks.append(text)
            sys.stdout.write(text)
            sys.stdout.flush()
        rest = decode(b"", final=True)
        if rest:
            chunks.append(rest)
            sys.stdout.write(rest)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    status = "done"
    started = time.monotonic()
    try:
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started > timeout:
                    status = "timeout"
                    kill_tree(proc)
                    break
    except KeyboardInterrupt:
        status = "interrupted"
        kill_tree(proc)
    thread.join(2)
    if script_path:
        try:
            os.remove(script_path)
        except OSError:
            pass

    output = "".join(chunks)
    if output and not output.endswith("\n"):
        print()
    return output, proc.returncode, status


# ---------------------------------------------------------------- Ollama

class OllamaError(Exception):
    pass


def find_ollama():
    """Найти установленную Ollama. Вернуть (путь к ollama, путь к приложению Ollama) или None."""
    if IS_WINDOWS:
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama")
        cli = shutil.which("ollama") or os.path.join(base, "ollama.exe")
        app = os.path.join(base, "ollama app.exe")
        return (cli if os.path.isfile(cli) else None), (app if os.path.isfile(app) else None)
    cli = shutil.which("ollama")
    if not cli:
        for path in ("/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
                     "/Applications/Ollama.app/Contents/Resources/ollama"):
            if os.path.isfile(path):
                cli = path
                break
    app = "/Applications/Ollama.app"
    return cli, (app if sys.platform == "darwin" and os.path.isdir(app) else None)


def start_ollama(cli, app):
    """Запустить сервер Ollama в фоне (он продолжит работать и после закрытия помощника)."""
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if IS_WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            if cli:
                subprocess.Popen([cli, "serve"], creationflags=flags, **quiet)
            else:
                subprocess.Popen([app], **quiet)
        elif cli:
            subprocess.Popen([cli, "serve"], start_new_session=True, **quiet)
        else:
            subprocess.Popen(["open", "-a", app], **quiet)
        return True
    except OSError as e:
        say(f"Не удалось запустить Ollama: {e}", Color.RED)
        return False


def download_file(url, path, title):
    part = path + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done, shown = 0, 0.0
            while True:
                chunk = resp.read(1 << 20)
                f.write(chunk)
                done += len(chunk)
                if not chunk or time.monotonic() - shown > 0.3:
                    shown = time.monotonic()
                    if total:
                        text = f"{title}: {done * 100 // total}%  ({done / 1e6:.0f} из {total / 1e6:.0f} МБ)"
                    else:
                        text = f"{title}: {done / 1e6:.0f} МБ"
                    sys.stdout.write("\r" + text.ljust(70))
                    sys.stdout.flush()
                if not chunk:
                    break
        print()
        os.replace(part, path)
        return True
    except (OSError, ValueError) as e:
        print()
        say(f"Не удалось скачать {url}: {e}", Color.RED)
    except KeyboardInterrupt:
        print()
        say("Скачивание прервано.", Color.YELLOW)
    try:
        os.remove(part)
    except OSError:
        pass
    return False


def install_ollama_windows():
    setup = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
    say("Скачиваю установщик Ollama (около 1 ГБ, это займёт несколько минут)...", Color.CYAN)
    if not download_file(OLLAMA_SETUP_URL, setup, "Ollama"):
        return False
    say("Устанавливаю Ollama — появится окно установки, просто подождите...", Color.CYAN)
    try:
        code = subprocess.run([setup, "/SP-", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]).returncode
    except OSError as e:
        say(f"Не удалось запустить установщик: {e}", Color.RED)
        return False
    finally:
        try:
            os.remove(setup)
        except OSError:
            pass
    if code != 0:
        say(f"Установка Ollama не завершилась (код {code}).", Color.RED)
        return False
    say("Ollama установлена.", Color.GREEN)
    return True


def normalize_host(host):
    host = host.strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    return host.replace("://0.0.0.0", "://127.0.0.1")


class Agent:
    def __init__(self, args):
        self.host = normalize_host(args.host)
        self.model = args.model
        self.auto = args.auto
        self.timeout = args.timeout
        self.num_ctx = args.ctx
        self.shell_name, self.shell_path = find_shell()
        self.history = []
        # Прокси для localhost не нужен (и часто мешает), поэтому отключаем.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # --- общение с Ollama

    def _open(self, path, payload=None, timeout=600):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.host + path, data=data, headers=headers)
        try:
            return self.http.open(request, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                message = json.loads(body).get("error", body)
            except ValueError:
                message = body
            raise OllamaError(message or f"HTTP {e.code}") from None

    def api(self, path, payload=None, timeout=600):
        with self._open(path, payload, timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def ollama_alive(self):
        try:
            self.api("/api/tags", timeout=3)
            return True
        except (OSError, OllamaError, ValueError):
            return False

    def wait_for_ollama(self, seconds):
        deadline = time.monotonic() + seconds
        with Spinner("Жду, пока Ollama запустится"):
            while time.monotonic() < deadline:
                if self.ollama_alive():
                    return True
                time.sleep(1)
        return False

    def ensure_ollama(self):
        """Убедиться, что Ollama работает: при необходимости запустить или установить её."""
        if self.ollama_alive():
            return True
        if not re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", self.host, re.I):
            say(f"Не получается подключиться к Ollama по адресу {self.host}.", Color.RED)
            return False

        cli, app = find_ollama()
        if not (cli or app):
            say("Для работы нужна бесплатная программа Ollama — она запускает нейросеть "
                "прямо на вашем компьютере.", Color.YELLOW)
            if not IS_WINDOWS:
                if sys.platform == "darwin":
                    say("Скачайте её с https://ollama.com/download, установите и откройте помощника снова.")
                else:
                    say("Установите её командой:  curl -fsSL https://ollama.com/install.sh | sh")
                return False
            if not ask_yes("Скачать и установить Ollama автоматически? [Enter = да / н = нет]: "):
                say("Скачать вручную можно здесь: https://ollama.com/download", Color.DIM)
                return False
            if not install_ollama_windows():
                return False
            if self.wait_for_ollama(10):  # установщик мог запустить её сам
                return True
            cli, app = find_ollama()

        if cli or app:
            say("Запускаю Ollama...", Color.CYAN)
            if start_ollama(cli, app) and self.wait_for_ollama(60):
                return True
        say("Не удалось запустить Ollama. Запустите её вручную (из меню «Пуск» или командой "
            "«ollama serve») и откройте помощника снова.", Color.RED)
        return False

    def ensure_ready(self):
        """Проверить, что Ollama работает и модель скачана (если нет — предложить скачать)."""
        if not self.ensure_ollama():
            return False
        try:
            tags = self.api("/api/tags", timeout=10)
        except (OSError, OllamaError, ValueError) as e:
            say(f"Ошибка связи с Ollama: {e}", Color.RED)
            return False

        names = set()
        for m in tags.get("models", []):
            names.add(m.get("name"))
            names.add(m.get("model"))
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if self.model in names or wanted in names:
            return True

        say(f"Нейросеть «{self.model}» ещё не скачана (это нужно сделать один раз).", Color.YELLOW)
        installed = sorted(n for n in names if n)
        if installed:
            say("Уже скачаны: " + ", ".join(installed), Color.DIM)
        if not ask_yes("Скачать её сейчас? Это несколько гигабайт. [Enter = да / н = нет]: "):
            say(f"Скачать можно командой:  ollama pull {self.model}", Color.DIM)
            return False
        return self.pull_model()

    def pull_model(self):
        say(f"Скачиваю {self.model}... Это может занять несколько минут.", Color.CYAN)
        try:
            with self._open("/api/pull", {"model": self.model, "name": self.model, "stream": True}) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    if "error" in event:
                        print()
                        say(f"Ошибка скачивания: {event['error']}", Color.RED)
                        return False
                    status = event.get("status", "")
                    total, done = event.get("total"), event.get("completed")
                    if total and done is not None:
                        text = f"{status[:25]}  {done * 100 // total}%  ({done / 1e9:.2f} из {total / 1e9:.2f} ГБ)"
                    else:
                        text = status
                    sys.stdout.write("\r" + text[:78].ljust(78))
                    sys.stdout.flush()
        except (OSError, OllamaError) as e:
            print()
            say(f"Ошибка скачивания: {e}", Color.RED)
            return False
        except KeyboardInterrupt:
            print()
            say("Скачивание прервано.", Color.YELLOW)
            return False
        print()
        say("Модель скачана.", Color.GREEN)
        return True

    def system_prompt(self):
        if IS_WINDOWS:
            os_name = f"Windows {platform.release()} (сборка {platform.version()})"
            tips = ("Команды выполняются в Windows PowerShell — пиши команды на PowerShell "
                    "(Get-ChildItem, Get-Content, Get-Process, Get-PSDrive и т.п.). "
                    "Чтобы открыть программу, файл, папку или сайт, используй Start-Process. "
                    "Права администратора недоступны, если помощник запущен не от имени администратора.")
        elif sys.platform == "darwin":
            os_name = f"macOS {platform.mac_ver()[0]}"
            tips = (f"Команды выполняются в {self.shell_name}. Чтобы открыть программу, файл или сайт, "
                    "используй open.")
        else:
            os_name = platform.platform()
            try:
                with open("/etc/os-release", encoding="utf-8") as f:
                    m = re.search(r'^PRETTY_NAME="?([^"\n]+)', f.read(), re.M)
                    if m:
                        os_name = m.group(1)
            except OSError:
                pass
            tips = (f"Команды выполняются в {self.shell_name}. Чтобы открыть файл или сайт, используй "
                    "xdg-open. Программы с окном запускай в фоне: nohup программа >/dev/null 2>&1 &. "
                    "Если нужен sudo — пользователь сам введёт пароль.")

        return f"""Ты — ИИ-помощник, который работает прямо на компьютере пользователя и умеет выполнять на нём команды.
Инструменты: run_command — выполнить команду в терминале; write_file — создать или перезаписать текстовый файл.

Сведения о компьютере:
- ОС: {os_name}
- Оболочка: {self.shell_name}
- Пользователь: {getpass.getuser()}
- Домашняя папка: {os.path.expanduser("~")}
- Текущая папка: {os.getcwd()}
- Сейчас: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}

{tips}

Правила:
1. Если просьбу можно выполнить на компьютере — сразу вызывай инструмент, а не объясняй, как это сделать.
2. Никогда не выдумывай результат. Сначала выполни команду и опирайся только на её реальный вывод.
3. Каждая команда запускается в новом процессе: переменные и прочее состояние не сохраняются. Исключение — отдельная команда «cd ПАПКА»: она меняет текущую папку для следующих команд.
4. Не запускай программы, которые ждут ввода с клавиатуры или работают бесконечно (vim, nano, top, ping без ограничения числа запросов и т.п.). Используй неинтерактивные варианты и флаги.
5. Получив вывод, кратко сообщи пользователю результат. Если команда завершилась с ошибкой — разберись в причине и попробуй исправить.
6. Для необратимых действий (удаление файлов, изменение системных настроек) сначала убедись, что пользователь точно этого хочет.
7. Если для ответа команды не нужны — просто ответь.
8. Отвечай по-русски, коротко и по делу."""

    def call_model(self):
        self.history = trim_history(self.history, HISTORY_LIMIT)
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_prompt()}] + self.history,
            "tools": TOOLS,
            "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": 0.2},
        }
        result = {}

        def worker():
            try:
                result["data"] = self.api("/api/chat", payload, timeout=900)
            except Exception as e:  # передаём ошибку в основной поток
                result["error"] = e

        # Запрос идёт в отдельном потоке, чтобы Ctrl+C срабатывал сразу (особенно в Windows).
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        with Spinner("ИИ думает"):
            while thread.is_alive():
                thread.join(0.1)
        if "error" in result:
            raise result["error"]
        return result["data"].get("message") or {}

    # --- основной цикл одной просьбы

    def handle(self, text):
        self.history.append({"role": "user", "content": text})
        for _ in range(MAX_STEPS):
            try:
                message = self.call_model()
            except OllamaError as e:
                self.report_model_error(str(e))
                return
            except OSError as e:
                say(f"Нет связи с Ollama: {e}. Проверьте, что Ollama запущена.", Color.RED)
                return

            content = clean_content(message.get("content") or "")
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                parsed = extract_text_tool_call(content)
                if parsed:
                    tool_calls, content = [parsed], ""

            entry = {"role": "assistant", "content": content}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            self.history.append(entry)
            if content:
                print()
                say(content, Color.CYAN)
            if not tool_calls:
                return

            stop = False
            for call in tool_calls:
                name = (call.get("function") or {}).get("name", "")
                if stop:
                    result = "Пропущено: пользователь остановил выполнение."
                else:
                    try:
                        result, stop = self.execute_tool(call)
                    except KeyboardInterrupt:
                        print()
                        say("Остановлено.", Color.YELLOW)
                        result, stop = "Пользователь прервал выполнение (Ctrl+C).", True
                self.history.append({"role": "tool", "content": result, "tool_name": name})
            if stop:
                return

        say(f"Сделано {MAX_STEPS} шагов подряд — останавливаюсь. "
            "Напишите «продолжай», если нужно продолжить.", Color.YELLOW)

    def report_model_error(self, error):
        say(f"Ошибка модели: {error}", Color.RED)
        if "does not support tools" in error:
            say(f"Модель «{self.model}» не умеет выполнять команды (не поддерживает tools). "
                "Возьмите другую, например: qwen2.5:7b, qwen3:8b или llama3.1:8b. "
                "Сменить можно командой /модель ИМЯ.", Color.YELLOW)
        elif "not found" in error:
            say(f"Модель не найдена. Скачайте её: ollama pull {self.model}", Color.YELLOW)

    def execute_tool(self, call):
        function = call.get("function") or {}
        name = function.get("name", "")
        args = function.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"command": args}
        if not isinstance(args, dict):
            return "Ошибка: аргументы инструмента должны быть объектом.", False
        if name == "run_command":
            return self.tool_run_command(args)
        if name == "write_file":
            return self.tool_write_file(args)
        return f"Ошибка: неизвестный инструмент «{name}». Доступны: run_command, write_file.", False

    def confirm(self, dangerous, action="Выполнить"):
        """Спросить разрешение. Вернуть ("yes" | "no" | "feedback", комментарий)."""
        if dangerous:
            say("Внимание: это потенциально опасное действие!", Color.RED + Color.BOLD)
            try:
                answer = input("Точно выполнить? Напишите «да» для подтверждения: ").strip().lower()
            except EOFError:
                return "no", ""
            return ("yes", "") if answer in {"да", "yes"} else ("no", "")
        if self.auto:
            return "yes", ""
        while True:
            try:
                answer = input(f"{action}? [Enter = да / н = нет / в = всегда да / или напишите, "
                               f"что сделать иначе]: ").strip()
            except EOFError:
                return "no", ""
            low = answer.lower()
            if low in YES:
                return "yes", ""
            if low in NO:
                return "no", ""
            if low in ALWAYS:
                self.auto = True
                say("Авто-режим включён: дальше выполняю без вопросов (кроме опасных команд). "
                    "Выключить: /авто", Color.DIM)
                return "yes", ""
            if len(answer) <= 1:
                say("Не понял ответ. Нажмите Enter, чтобы выполнить, или «н», чтобы отказаться.", Color.DIM)
                continue
            return "feedback", answer

    def tool_run_command(self, args):
        command = str(args.get("command") or "").strip()
        explanation = str(args.get("explanation") or "").strip()
        if not command:
            return "Ошибка: пустая команда.", False

        print()
        if explanation:
            say(explanation, Color.DIM)
        say(f"$ {command}", Color.YELLOW + Color.BOLD)
        decision, comment = self.confirm(is_dangerous(command))
        if decision == "no":
            say("Отменено.", Color.DIM)
            return "Пользователь отказался выполнять эту команду.", True
        if decision == "feedback":
            return f"Пользователь не стал выполнять команду и написал: {comment}", False

        new_dir = parse_cd(command)
        if new_dir is not None:
            return self.change_dir(new_dir), False

        output, code, status = run_shell(self.shell_path, command, self.timeout)
        if status == "timeout":
            say(f"[остановлено: команда работала дольше {self.timeout} с]", Color.RED)
            head = (f"Команда остановлена: она работала дольше {self.timeout} секунд "
                    "(возможно, ждала ввода или работает бесконечно).")
        elif status == "interrupted":
            say("[остановлено пользователем]", Color.YELLOW)
            return f"Пользователь прервал команду (Ctrl+C).\nВывод:\n{shorten_for_model(output)}", True
        elif status == "error":
            say(output, Color.RED)
            head = output
            output = ""
        else:
            say(f"[код завершения: {code}]", Color.DIM if code == 0 else Color.RED)
            head = f"Код завершения: {code}"
        body = shorten_for_model(output)
        return f"{head}\nВывод:\n{body if body else '(пусто)'}", False

    def tool_write_file(self, args):
        path = str(args.get("path") or "").strip()
        content = args.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, indent=2)
        if not path:
            return "Ошибка: не указан путь к файлу.", False

        target = os.path.abspath(os.path.expanduser(os.path.expandvars(path)))
        print()
        say(f"Записать файл: {target}", Color.YELLOW + Color.BOLD)
        if os.path.exists(target):
            say("Файл уже существует и будет перезаписан!", Color.RED)
        lines = content.splitlines()
        for line in lines[:15]:
            say(f"  | {line}", Color.DIM)
        if len(lines) > 15:
            say(f"  ... и ещё {len(lines) - 15} строк", Color.DIM)

        decision, comment = self.confirm(False, action="Записать")
        if decision == "no":
            say("Отменено.", Color.DIM)
            return "Пользователь отказался записывать файл.", True
        if decision == "feedback":
            return f"Пользователь не стал записывать файл и написал: {comment}", False
        try:
            folder = os.path.dirname(target)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content.replace("\r\n", "\n"))
        except OSError as e:
            say(f"Не удалось записать файл: {e}", Color.RED)
            return f"Ошибка записи файла: {e}", False
        say(f"Файл сохранён: {target}", Color.GREEN)
        return f"Файл сохранён: {target} ({len(content)} символов).", False

    def change_dir(self, path):
        target = os.path.abspath(os.path.join(os.getcwd(), path))
        if not os.path.isdir(target):
            say(f"Папка не найдена: {target}", Color.RED)
            return f"Ошибка: папка не найдена: {target}"
        os.chdir(target)
        say(f"Текущая папка: {target}", Color.GREEN)
        return f"Текущая папка изменена на {target}"

    # --- диалог

    def banner(self):
        mode = "без подтверждения" if self.auto else "с подтверждением каждой команды"
        say(f"Локальный ИИ-помощник {VERSION}  ·  модель: {self.model}  ·  оболочка: {self.shell_name}",
            Color.BOLD)
        say(f"Режим: {mode}. Напишите, что сделать, например: «покажи, сколько свободного места на дисках».",
            Color.DIM)
        say("/помощь — список команд, выход — закрыть.", Color.DIM)

    def help(self):
        print("""
  /помощь  (/help)    — эта справка
  /авто    (/auto)    — включить/выключить выполнение без подтверждения
                        (опасные команды всё равно требуют «да»)
  /сброс   (/reset)   — забыть историю разговора
  /модель ИМЯ         — сменить модель, например: /модель qwen3:8b
  !команда            — выполнить команду сразу, без ИИ, например: !dir
  выход    (/exit)    — закрыть программу
  Ctrl+C              — остановить текущую команду или ответ ИИ
""")

    def builtin(self, text):
        """Обработать служебную команду. Вернуть True, если обработана; "exit" — для выхода."""
        low = text.lower()
        if low in {"выход", "/выход", "exit", "/exit", "quit", "/quit", "q"}:
            return "exit"
        if low in {"/помощь", "/help", "помощь", "/?"}:
            self.help()
            return True
        if low in {"/авто", "/auto"}:
            self.auto = not self.auto
            say("Авто-режим " + ("включён." if self.auto else "выключен: буду спрашивать перед каждой командой."),
                Color.GREEN)
            return True
        if low in {"/сброс", "/reset", "/clear"}:
            self.history = []
            say("История очищена.", Color.GREEN)
            return True
        if low.startswith(("/модель", "/model")):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                say(f"Сейчас используется модель: {self.model}", Color.DIM)
                return True
            old = self.model
            self.model = parts[1].strip()
            if self.ensure_ready():
                say(f"Модель изменена на {self.model}.", Color.GREEN)
            else:
                self.model = old
                say(f"Оставляю модель {old}.", Color.YELLOW)
            return True
        if text.startswith("!"):
            command = text[1:].strip()
            if command:
                new_dir = parse_cd(command)
                if new_dir is not None:
                    self.change_dir(new_dir)
                else:
                    _, code, _ = run_shell(self.shell_path, command, self.timeout)
                    say(f"[код завершения: {code}]", Color.DIM if code == 0 else Color.RED)
            return True
        if low.startswith("/"):
            say("Неизвестная команда. /помощь — список команд.", Color.YELLOW)
            return True
        return False

    def repl(self):
        self.banner()
        home = os.path.expanduser("~")
        while True:
            cwd = os.getcwd()
            if cwd == home or cwd.startswith(home + os.sep):
                cwd = "~" + cwd[len(home):]
            print()
            say(cwd, Color.DIM)
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            handled = self.builtin(text)
            if handled == "exit":
                break
            if handled:
                continue
            try:
                self.handle(text)
            except KeyboardInterrupt:
                print()
                say("Остановлено.", Color.YELLOW)
        say("Пока!", Color.DIM)


def trim_history(history, limit):
    """Оставить последние сообщения так, чтобы история начиналась с сообщения пользователя."""
    if len(history) <= limit:
        return history
    start = len(history) - limit
    for i in range(start, len(history)):
        if history[i]["role"] == "user":
            return history[i:]
    for i in range(start - 1, -1, -1):
        if history[i]["role"] == "user":
            return history[i:]
    return history


def prepare_frozen():
    """Настройки для запуска из готового .exe (собранного PyInstaller)."""
    if IS_WINDOWS:
        try:
            import ctypes
            # чтобы запускаемые команды не подхватывали библиотеки из распакованного .exe
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass
    else:
        original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is not None:
            os.environ["LD_LIBRARY_PATH"] = original
        else:
            os.environ.pop("LD_LIBRARY_PATH", None)
    # При двойном щелчке текущая папка — та, где лежит .exe. Удобнее начать с домашней.
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.normcase(os.getcwd()) == os.path.normcase(exe_dir):
        os.chdir(os.path.expanduser("~"))


def main():
    setup_console()
    if FROZEN:
        prepare_frozen()
    parser = argparse.ArgumentParser(
        description="Локальный ИИ-помощник: выполняет на компьютере то, что вы попросите (через Ollama).")
    parser.add_argument("-m", "--model", default=os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
                        help=f"модель Ollama (по умолчанию {DEFAULT_MODEL})")
    parser.add_argument("--host", default=os.environ.get("AGENT_OLLAMA_URL", DEFAULT_HOST),
                        help=f"адрес Ollama (по умолчанию {DEFAULT_HOST})")
    parser.add_argument("--auto", action="store_true",
                        help="выполнять команды без подтверждения (опасные всё равно спрашиваются)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="сколько секунд может работать одна команда (по умолчанию 300)")
    parser.add_argument("--ctx", type=int, default=8192,
                        help="размер контекста модели в токенах (по умолчанию 8192)")
    parser.add_argument("request", nargs="*",
                        help="просьба, которую выполнить сразу и выйти (необязательно)")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()

    agent = Agent(args)
    if not agent.ensure_ready():
        return 1
    if args.request:
        try:
            agent.handle(" ".join(args.request))
        except KeyboardInterrupt:
            print()
        return 0
    agent.repl()
    return 0


def run():
    try:
        code = main()
    except KeyboardInterrupt:
        print()
        return 130
    except Exception:
        import traceback
        traceback.print_exc()
        say("Произошла непредвиденная ошибка (подробности выше).", Color.RED)
        code = 1
    if code and FROZEN and IS_WINDOWS:
        # Иначе окно .exe закроется сразу, и сообщение об ошибке не успеть прочитать.
        try:
            input("\nНажмите Enter, чтобы закрыть окно...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(run())
