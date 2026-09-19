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

Всего животных 19, готовы 5, одна временная.

| Готово | Файл | Порода | Постройка | Уровень | Как выглядит |
|:---:|---|---|---|:---:|---|
| ✅ | `breed-rusbel.png` | Русская белая | Курятник | 1 | Белая приземистая несушка, красный гребень |
| ✅ | `breed-moskchern.png` | Московская чёрная | Курятник | 2 | Чёрная, золотистая грива |
| ✅ | `breed-leggorn.png` | Леггорн | Курятник | 3 | Белая, высокая, крупный гребень набок |
|  | `breed-tula.png` | Тульский бойцовый | Гусятник | 4 | Серый гусь |
| ✅ | `breed-orlov.png` | Орловская ситцевая | Курятник | 4 | Пёстрая ситцевая, борода и баки |
| ~ | `breed-pavlov.png` | Павловская | Курятник | 5 | Стоит временная: генератор не нарисовал ни хохла, ни мохнатых ног, и вышла третья белая птица |
|  | `breed-vietnam.png` | Вьетнамская вислобрюхая | Свинарник | 5 | Чёрная свинья, брюхо до земли |
| ✅ | `breed-kuchin.png` | Кучинская юбилейная | Курятник | 6 | Рыже-бурая, золотая шея |
|  | `breed-holmgus.png` | Холмогорский гусь | Гусятник | 7 | Белый гусь, шишка на клюве |
|  | `breed-yurlov.png` | Юрловская голосистая | Курятник | 7 | Тёмная, рослая, длинные ноги |
|  | `breed-brama.png` | Брама | Курятник | 8 | Крупная палевая, мохнатые ноги |
|  | `breed-mirgorod.png` | Миргородская | Свинарник | 9 | Рябая: розовая с чёрными пятнами |
|  | `breed-poltav.png` | Полтавская глинистая | Курятник | 9 | Глинисто-жёлтая |
|  | `breed-holmkor.png` | Холмогорская | Коровник | 10 | Корова чёрно-пёстрая |
|  | `breed-zagorsk.png` | Загорская лососёвая | Курятник | 11 | Лососёвая, розовато-кремовая |
|  | `breed-landras.png` | Ландрас | Свинарник | 11 | Длинная бледно-розовая, уши вперёд |
|  | `breed-simment.png` | Симментальская | Коровник | 13 | Корова рыже-пёстрая, белая голова |
|  | `breed-krupbel.png` | Крупная белая | Свинарник | 13 | Крупная розовая свинья |
|  | `breed-vladimir.png` | Владимирский тяжеловоз | Конюшня | 14 | Гнедой тяжеловоз, щётки на ногах |

## Запросы для генератора

Хвост одинаковый у всех, меняется только первая часть — так весь двор выходит
в одном стиле. Порядок тот же, что в таблице выше.

```text
Московская чёрная
cute cartoon black hen with golden neck feathers and a red comb, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Орловская ситцевая
cute cartoon mottled orange white and black hen with a beard and thick cheek feathers, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Павловская — переснять: нужен хохол и не белая
cute cartoon golden brown hen with black speckles, a big round fluffy feather crest on top of its head like a pompom, thick feathered legs, tiny comb, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Кучинская юбилейная
cute cartoon reddish-brown hen with golden neck feathers, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Юрловская голосистая
cute cartoon tall dark brown rooster with long legs and an upright red comb, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Брама
cute cartoon large fluffy cream brahma hen with feathered legs, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Полтавская глинистая
cute cartoon clay-yellow buff hen, plump body, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Загорская лососёвая
cute cartoon salmon pink cream hen, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Тульский бойцовый
cute cartoon grey goose with a long neck and orange beak, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Вьетнамская вислобрюхая
cute cartoon black pot-bellied pig with a sagging belly and short legs, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Холмогорский гусь
cute cartoon white goose with a knob above its orange beak, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

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

Куры подобраны так, чтобы масть у каждой своя: белая, чёрная, ситцевая,
серебристо-пёстрая, рыже-бурая, тёмная, палевая, глинистая, лососёвая. Пока
картинки не пришли, в игре стоят отрисованные заглушки — они хотя бы разного
цвета, но видно, что это заглушки. Хуже, когда животное смотрит влево: такую картинку
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
