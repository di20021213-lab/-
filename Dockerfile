# Готовый образ с уже установленными браузерами Playwright.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
# Ставим браузер ПОСЛЕ установки playwright, чтобы сборка Chromium гарантированно
# совпала с установленной версией пакета (иначе "Executable doesn't exist").
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY . .

# config.yaml и .env монтируются снаружи (см. README), в образ не кладём.
CMD ["python", "-m", "avito_watcher.main"]
