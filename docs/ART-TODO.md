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

Всего животных 19, готовы 8, одна из них временная.

| Готово | Файл | Порода | Постройка | Уровень | Как выглядит |
|:---:|---|---|---|:---:|---|
| ✅ | `breed-rusbel.png` | Русская белая | Курятник | 1 | Белая приземистая несушка, красный гребень |
| ✅ | `breed-moskchern.png` | Московская чёрная | Курятник | 2 | Чёрная, золотистая грива |
| ✅ | `breed-leggorn.png` | Леггорн | Курятник | 3 | Белая, высокая, крупный гребень набок |
| ✅ | `breed-tula.png` | Тульский бойцовый | Гусятник | 4 | Серый гусь |
| ✅ | `breed-orlov.png` | Орловская ситцевая | Курятник | 4 | Пёстрая ситцевая, борода и баки |
| ~ | `breed-pavlov.png` | Павловская | Курятник | 5 | Стоит временная: генератор не нарисовал ни хохла, ни мохнатых ног, и вышла третья белая птица |
|  | `breed-vietnam.png` | Вьетнамская вислобрюхая | Свинарник | 5 | Чёрная свинья, брюхо до земли |
| ✅ | `breed-kuchin.png` | Кучинская юбилейная | Курятник | 6 | Рыже-бурая, золотая шея |
| ✅ | `breed-holmgus.png` | Холмогорский гусь | Гусятник | 7 | Белый гусь, шишка на клюве |
|  | `breed-kitay.png` | Китайский | Гусятник | 5 | Бурый, лебединая шея, шишка на лбу |
|  | `breed-kuban.png` | Кубанский | Гусятник | 9 | Серо-бурый, тёмная полоса по шее |
|  | `breed-tuluz.png` | Тулузский | Гусятник | 11 | Грузный серый, кошелёк под клювом |
|  | `breed-ital.png` | Итальянский белый | Гусятник | 12 | Белый, лёгкий, без шишки |
|  | `breed-mirgorod.png` | Миргородская | Свинарник | 9 | Рябая: розовая с чёрными пятнами |
|  | `breed-holmkor.png` | Холмогорская | Коровник | 10 | Корова чёрно-пёстрая |
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

Тульский бойцовый
cute cartoon domestic farm goose with soft grey and white feathers, long curved neck, orange beak, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Вьетнамская вислобрюхая
cute cartoon black pot-bellied pig with a sagging belly and short legs, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Холмогорский гусь
cute cartoon white domestic farm goose with a knob above its orange beak, long curved neck, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Китайский
cute cartoon brown domestic farm goose with a swan-like slender neck and a round knob on its forehead, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Кубанский
cute cartoon greyish brown domestic farm goose with a dark stripe down the back of its neck and a knob on its forehead, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Тулузский
cute cartoon heavy grey domestic farm goose with a hanging dewlap pouch under its beak, low bulky body, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Итальянский белый
cute cartoon slim white domestic farm goose with a plain orange beak and no knob, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

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

У гусей палитра бедная — белый, серый, бурый, и всё. Поэтому шесть пород
разведены не мастью, а силуэтом: у китайского лебединая шея, у кубанского
полоса по шее, у тулузского кошелёк под клювом и грузное тело, итальянский
белый без шишки в отличие от холмогорского. Две пары всё равно близки —
если в игре сольются, режем так же, как резали кур.

Курятник закрыт: шесть пород, у каждой своя масть — белая, чёрная, белая
высокая, рыжая с белой головой, серебристая, рыжая в крапинку. Десять сначала
завели зря: разницу между третьей и четвёртой белой курицей в плитке всё равно
не видно, а картинок на них уходит столько же.

Заодно из игры выпала единственная порода за кристаллы (Брама). Когда дойдут
руки до «дорогой» живности — верну такую в гусятник или коровник.

## Если генератор отказал

Он режет торговые марки, даже когда речь про птицу. «Grey goose» — это водка,
и запрос с такой парой слов Leonardo завернул как нарушение правил. Лечится
перестановкой: «domestic farm goose with soft grey and white feathers».
По той же причине из списка убрана Брама — это ещё и марка пива.

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
