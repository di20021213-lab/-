# Какие текстуры животных нужны

Порядок — как игрок их встречает: сверху то, что нужно раньше всего.
Сделал → кидай картинку, я прогоняю её через импортёр:

```
python3 tools/import-art.py картинка.png <id>
```

Скрипт сам снимает фон (хоть шашечки, хоть белый), срезает нарисованную под
ногами тень, обрезает по краю, ужимает до 200 пикселей по ширине и подставляет
общую мягкую тень. Исходник кладём в `assets-src/art/<id>.jpg`.

## Чтобы картинка встала без возни

- **Вид сбоку в три четверти, мордой вправо.** Во дворе все смотрят в одну
  сторону. Если картинка смотрит влево — не беда, импортёр отразит по флагу
  `--flip`, но лучше сразу вправо: отражение уводит несимметричные детали.
- Животное целиком, стоит на ногах, ничем не обрезано по краям.
- Фон прозрачный или ровный белый. Шашечки тоже сойдут.
- Своя тень-эллипс под ногами не нужна — я всё равно срезаю и ставлю общую.
  Если хочется оставить: `--keep-shadow`.
- Квадрат 1024×1024 — в самый раз, больше не нужно.
- Без подписей, рамок и бликов по краю картинки.

## Список

| Готово | Файл | Порода | Постройка | Уровень | Как выглядит |
|:---:|---|---|---|:---:|---|
| ✅ | `breed-rusbel.png` | Русская белая | Курятник | 1 | Белая несушка, красный гребень |
| ✅ | `breed-leggorn.png` | Леггорн | Курятник | 3 | Белая, гребень крупный, набок |
| | `breed-tula.png` | Тульский бойцовый | Гусятник | 4 | Серый гусь, характер скверный |
| | `breed-vietnam.png` | Вьетнамская вислобрюхая | Свинарник | 5 | Чёрная свинья, брюхо до земли |
| | `breed-kuchin.png` | Кучинская юбилейная | Курятник | 6 | Рыже-бурая курица, золотая шея |
| | `breed-holmgus.png` | Холмогорский гусь | Гусятник | 7 | Белый гусь, шишка на клюве |
| | `breed-brama.png` | Брама | Курятник | 8 | Крупная, светлая, мохнатые ноги |
| | `breed-mirgorod.png` | Миргородская | Свинарник | 9 | Рябая: розовая с чёрными пятнами |
| | `breed-holmkor.png` | Холмогорская | Коровник | 10 | Корова чёрно-пёстрая |
| | `breed-landras.png` | Ландрас | Свинарник | 11 | Длинная бледно-розовая, уши вперёд |
| | `breed-simment.png` | Симментальская | Коровник | 13 | Корова рыже-пёстрая, белая голова |
| | `breed-krupbel.png` | Крупная белая | Свинарник | 13 | Крупная розовая свинья |
| | `breed-vladimir.png` | Владимирский тяжеловоз | Конюшня | 14 | Гнедой тяжеловоз, щётки на ногах |

## Запросы для генератора

Хвост одинаковый у всех, меняется только первая часть — так весь двор выходит
в одном стиле. Порядок тот же, что в таблице выше.

```text
Леггорн
cute cartoon white leghorn hen with a large floppy red comb, yellow beak, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Тульский бойцовый
cute cartoon grey goose with a long neck and orange beak, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Вьетнамская вислобрюхая
cute cartoon black pot-bellied pig with a sagging belly and short legs, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Кучинская юбилейная
cute cartoon reddish-brown hen with golden neck feathers, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Холмогорский гусь
cute cartoon white goose with a knob above its orange beak, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Брама
cute cartoon large fluffy cream brahma hen with feathered legs, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Миргородская
cute cartoon pink pig with big black spots, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Холмогорская
cute cartoon black and white dairy cow with an udder, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Ландрас
cute cartoon long pale pink pig with big forward-drooping ears, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Симментальская
cute cartoon red and white simmental cow with a white head, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Крупная белая
cute cartoon large pink sow, heavy body, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Владимирский тяжеловоз
cute cartoon bay draft horse with feathered hooves, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background
```

Если генератор всё равно рисует тень или траву под ногами — не страшно,
импортёр их срезает.

Две белые курицы подряд (Русская белая и Леггорн) в плитке магазина похожи:
различаются только статью и гребнем. Если захочется контраста — порода меняется
одной строкой в `public/content.js`, взамен подойдут Московская чёрная (чёрная с
золотой гривой), Орловская ситцевая (пёстрая, с бородой) или Павловская
(хохлатая, мохноногая). Хуже, когда животное смотрит влево: такую картинку
приходится отражать, и надписи с несимметричными деталями уезжают.

## Потом, если захочется

Не животные, но тоже пиксельные и выбиваются:

| Файл | Что это | Где видно |
|---|---|---|
| `prop-farmer.png` | Председатель | подсказка внизу двора |
| `feed-bone.png` | Косточка | корм для собаки |
| `feed-fish.png` | Рыбка | корм для кота |

Пёс и кот пока эмодзи в шапке — если дашь картинки, заведу им спрайты.

## Откуда что взялось

Присланные картинки сделаны нейросетью по заказу владельца проекта; остальная
графика и её лицензии описаны в [CREDITS.md](../CREDITS.md).
