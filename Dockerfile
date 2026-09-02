# Готовый образ с уже установленными браузерами Playwright.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# config.yaml и .env монтируются снаружи (см. README), в образ не кладём.
CMD ["python", "-m", "avito_watcher.main"]
