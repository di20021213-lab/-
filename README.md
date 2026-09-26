# Kinescope Downloader

Восстановлено из рабочего .exe (PyInstaller, Python 3.11) + истории разработки.

## Состав
- `kinescope_gui.py` — приложение (Tkinter, окно в стиле Windows XP).
- `kinescope_dl.py` — движок скачивания DASH/HLS (+ водяной знак, JSON/HAR).
- `capture_server.py` — локальный приёмник ссылок из браузерного расширения.
- `extension/` — расширение для браузера (v2.1).
- `assets/watermark.png`, `assets/font.ttf` — ресурсы (вытащены из exe).
- `requirements.txt`, `.github/workflows/build-exe.yml` — зависимости и сборка.

## Сборка .exe
Запушить в ветку `claude/kinescope-video-downloader-g569dw` — GitHub Actions
соберёт `KinescopeDownloader.exe` (вкладка Actions → Artifacts). ffmpeg
скачивается на этапе сборки и вшивается внутрь.

## Локальный запуск (Windows)
    pip install -r requirements.txt
    python kinescope_gui.py
