# Исходные архивы графики

Сюда кладутся скачанные архивы наборов, из которых потом собираются спрайты
в `public/img`. Готовая графика лежит в репозитории, а архивы здесь — временно,
только чтобы передать их в работу; после интеграции архив удаляется.

## Как положить архив

Через сайт GitHub, без установки git:

1. Открыть репозиторий, переключиться на ветку `claude/intelligent-euler-5hb0te`.
2. Зайти в папку `assets-src`.
3. **Add file → Upload files**, перетащить архив.
4. Внизу **Commit changes** — коммитить прямо в эту ветку.

Или из командной строки:

```
git checkout claude/intelligent-euler-5hb0te
git pull
copy "%USERPROFILE%\Downloads\Gr8FarmPack_ODDBLOT.zip" assets-src\
git add assets-src/Gr8FarmPack_ODDBLOT.zip
git commit -m "Архив набора ODDBLOT"
git push
```

Ограничение GitHub — 100 МБ на файл, наш архив 4.9 МБ, влезает с запасом.

## Что ожидается сейчас

`Gr8FarmPack_ODDBLOT.zip` — набор [The Great Farm](https://oddblotstudios.itch.io/free-the-great-farm-isometric),
рисованная изометрия, 146 ассетов. Лицензия: коммерческое использование и правки
разрешены, нельзя обучать на нём нейросети и перепродавать как есть.
