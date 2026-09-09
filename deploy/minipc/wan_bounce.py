#!/usr/bin/env python3
"""Кладёт WAN роутера Keenetic на несколько минут, чтобы провайдер выдал новый IP.

Зачем не «перезагрузка»: короткий реконнект часто возвращает тот же адрес, а
сессия, закрытая на несколько минут, меняет его заметно чаще. Обесточить роутер
удалённо нельзя — включать будет некому, — но положить WAN можно: роутер
остаётся под питанием, локальная сеть работает, и машина, отдавшая команду,
всё это время видит его по LAN.

СТРАХОВКА. Финалом идёт system reboot, а НЕ «поднять интерфейс». Keenetic не
сохраняет изменения конфигурации, пока не сказать configuration save, поэтому
перезагрузка возвращает WAN в исходное состояние сама.

Почему не bash+telnet: там шаги разделялись паузами, а Keenetic печатает баннер
и приглашение Login: с задержкой. Логин уходил в пустоту, пароль попадал в поле
логина, вход не удавался — и скрипт молча не делал ничего. Здесь мы дожидаемся
самих приглашений.

Использование:
  python3 wan_bounce.py                 — показать интерфейсы и выйти
  python3 wan_bounce.py ISP             — положить WAN на 5 минут
  python3 wan_bounce.py ISP 600         — на 10 минут

Пароль — в переменной окружения KEENETIC_PASSWORD.

Запускать ОТВЯЗАННО от SSH: интернет пропадёт, и сессия оборвётся раньше, чем
скрипт дойдёт до перезагрузки.
  KEENETIC_PASSWORD='...' setsid nohup python3 wan_bounce.py ISP 300 &
"""

from __future__ import annotations

import os
import socket
import sys
import time
import urllib.request
from datetime import datetime
from typing import Optional

ROUTER = os.getenv("ROUTER", "192.168.1.1")
PORT = int(os.getenv("ROUTER_PORT", "23"))
LOGIN = os.getenv("KEENETIC_LOGIN", "admin")
LOG_PATH = os.getenv("LOG", os.path.expanduser("~/wan-bounce.log"))

READ_TIMEOUT = 20
PROMPT = ">"

# Байты протокола telnet: сервер согласовывает опции, и если не ответить,
# часть серверов ждёт. Отвечаем отказом на всё — нам нужен голый текст.
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


def say(text: str) -> None:
    line = f"{datetime.now():%d.%m %H:%M:%S}  {text}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Keenetic:
    """Минимальный telnet-клиент для CLI роутера."""

    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, port), timeout=READ_TIMEOUT)
        self.sock.settimeout(READ_TIMEOUT)
        self.buf = ""

    def _feed(self, data: bytes) -> str:
        """Убирает telnet-команды из потока, отвечая на согласование отказом."""
        out = bytearray()
        i = 0
        while i < len(data):
            if data[i] != IAC:
                out.append(data[i])
                i += 1
                continue
            if i + 1 >= len(data):
                break
            cmd = data[i + 1]
            if cmd in (DO, DONT) and i + 2 < len(data):
                self.sock.sendall(bytes([IAC, WONT, data[i + 2]]))
                i += 3
            elif cmd in (WILL, WONT) and i + 2 < len(data):
                self.sock.sendall(bytes([IAC, DONT, data[i + 2]]))
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i)
                i = len(data) if end == -1 else end + 2
            else:
                i += 2
        return out.decode("utf-8", errors="replace")

    def read_until(self, needle: str, timeout: int = READ_TIMEOUT) -> str:
        """Ждёт подстроку в потоке. Именно этого не хватало bash-версии."""
        deadline = time.time() + timeout
        while needle.lower() not in self.buf.lower():
            if time.time() > deadline:
                raise TimeoutError(f"не дождался {needle!r}, получено: {self.buf[-200:]!r}")
            self.sock.settimeout(max(1, deadline - time.time()))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError(f"соединение закрыто, получено: {self.buf[-200:]!r}")
            self.buf += self._feed(chunk)
        text, self.buf = self.buf, ""
        return text

    def send(self, line: str) -> None:
        self.sock.sendall((line + "\n").encode())

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def run_commands(commands: list[str], password: str) -> str:
    """Логинится и выполняет команды. Возвращает всё, что ответил роутер."""
    k = Keenetic(ROUTER, PORT)
    transcript = ""
    try:
        transcript += k.read_until("login:")
        k.send(LOGIN)
        transcript += k.read_until("password:")
        k.send(password)
        transcript += k.read_until(PROMPT)
        for cmd in commands:
            k.send(cmd)
            try:
                transcript += k.read_until(PROMPT)
            except (TimeoutError, ConnectionError):
                # system reboot закрывает соединение, не ответив приглашением.
                break
        k.send("exit")
    finally:
        k.close()
    return transcript


def external_ip() -> Optional[str]:
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=15) as r:
            return r.read().decode().strip()
    except Exception:  # noqa: BLE001 - интернета может не быть, это ожидаемо
        return None


def main() -> int:
    password = os.getenv("KEENETIC_PASSWORD", "")
    if not password:
        print("Нужен пароль: KEENETIC_PASSWORD='...' python3 wan_bounce.py ...",
              file=sys.stderr)
        return 2

    iface = sys.argv[1] if len(sys.argv) > 1 else ""
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    if not iface:
        print(f"Маршруты роутера {ROUTER} — WAN тот, через который идёт 0.0.0.0/0:\n")
        try:
            print(run_commands(["show ip route"], password))
        except (OSError, TimeoutError) as e:
            print(f"Не смог подключиться к роутеру: {e}", file=sys.stderr)
            return 1
        print(f"\nНашёл имя — запускай: "
              f"KEENETIC_PASSWORD='...' setsid nohup python3 {sys.argv[0]} ИМЯ {seconds} &")
        return 0

    say(f"=== старт: кладу {iface} на {seconds} сек ===")
    say(f"IP до: {external_ip() or '?'}")

    try:
        run_commands([f"interface {iface} down"], password)
    except (OSError, TimeoutError) as e:
        say(f"не смог отправить команду down: {e}")
        return 1
    say(f"команда down отправлена, жду {seconds} сек")
    time.sleep(seconds)

    # Возвращаем связь перезагрузкой: она поднимает WAN из сохранённого конфига.
    # Пробуем несколько раз — остаться без интернета из-за одной неудачной
    # сессии нельзя.
    for attempt in range(1, 6):
        say(f"перезагружаю роутер (попытка {attempt})")
        try:
            run_commands(["system reboot"], password)
        except (OSError, TimeoutError) as e:
            say(f"перезагрузка не отправилась: {e}")
        for _ in range(12):
            time.sleep(15)
            ip = external_ip()
            if ip:
                say(f"IP после: {ip}")
                say("=== готово ===")
                return 0

    say("!!! интернет не вернулся — передёрни роутер питанием")
    return 1


if __name__ == "__main__":
    sys.exit(main())
