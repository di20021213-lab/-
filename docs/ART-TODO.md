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
- Пропорции обычные. Долговязую птицу импортёр ужимает и добавляет воздух по
  бокам, чтобы во дворе она не перерастала постройку, но тушка при этом мельчает.
- Фон любой ровный: белый, кремовый, прозрачный, шашечки. Цвет угла берётся
  за образец.
- Без подписей, рамок и бликов по краю картинки.
- Если порода смотрит влево — впиши её в `assets-src/art/flip.txt`, и импортёр
  будет разворачивать её всегда. Держать этот список в голове нельзя: при
  переимпорте всех пород разом я его переврал, и четверо во дворе встали
  спиной к остальным.

## Список

Все девятнадцать заменены присланными картинками, временных не осталось.

| Готово | Файл | Порода | Постройка | Уровень | Как выглядит |
|:---:|---|---|---|:---:|---|
| ✅ | `breed-rusbel.png` | Русская белая | Курятник | 1 | Белая приземистая несушка, красный гребень |
| ✅ | `breed-moskchern.png` | Московская чёрная | Курятник | 2 | Чёрная, золотистая грива |
| ✅ | `breed-leggorn.png` | Леггорн | Курятник | 3 | Белая, высокая, крупный гребень набок |
| ✅ | `breed-tula.png` | Тульский бойцовый | Гусятник | 4 | Серый гусь |
| ✅ | `breed-orlov.png` | Орловская ситцевая | Курятник | 4 | Пёстрая ситцевая, борода и баки |
| ✅ | `breed-pavlov.png` | Павловская | Курятник | 5 | Кремовый хохол-помпон, тёмное тело в крапинку |
| ✅ | `breed-vietnam.png` | Вьетнамская вислобрюхая | Свинарник | 5 | Чёрная свинья, брюхо до земли |
| ✅ | `breed-kuchin.png` | Кучинская юбилейная | Курятник | 6 | Рыже-бурая, золотая шея |
| ✅ | `breed-holmgus.png` | Холмогорский гусь | Гусятник | 7 | Белый гусь, шишка на клюве |
| ✅ | `breed-kitay.png` | Китайский | Гусятник | 5 | Бурый, лебединая шея, шишка на лбу |
| ✅ | `breed-kuban.png` | Кубанский | Гусятник | 9 | Серо-бурый, тёмная полоса по шее |
| ✅ | `breed-tuluz.png` | Тулузский | Гусятник | 11 | Грузный серый, кошелёк под клювом |
| ✅ | `breed-ital.png` | Итальянский белый | Гусятник | 12 | Белый, лёгкий, без шишки |
| ✅ | `breed-mirgorod.png` | Миргородская | Свинарник | 9 | Рябая: розовая с чёрными пятнами |
| ✅ | `breed-holmkor.png` | Холмогорская | Коровник | 10 | Чёрно-пёстрая, розовое вымя |
| ✅ | `breed-landras.png` | Ландрас | Свинарник | 11 | Ровно-розовая без пятен, уши торчком |
| ✅ | `breed-simment.png` | Симментальская | Коровник | 13 | Рыже-пёстрая, белая голова |
| ✅ | `breed-krupbel.png` | Крупная белая | Свинарник | 13 | Круглая розовая, уши висят на глаза |
| ✅ | `breed-vladimir.png` | Владимирский тяжеловоз | Конюшня | 14 | Гнедой; масть доведена перекраской |

## Запросы для генератора

Хвост одинаковый у всех, меняется только первая часть — так весь двор выходит
в одном стиле. Порядок тот же, что в таблице выше.

```text
Московская чёрная
cute cartoon black hen with golden neck feathers and a red comb, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Орловская ситцевая
cute cartoon mottled orange white and black hen with a beard and thick cheek feathers, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Павловская
cute cartoon hen with a huge round fluffy feather crest covering the top of its head like a pompom, speckled black and gold plumage, thick feathers down its legs, tiny comb, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

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

Крупная белая — просить уши вниз, иначе сольётся с ландрасом
cute cartoon farm pig with a big round heavy body and large floppy ears hanging down over its eyes, pale pink skin, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background

Владимирский тяжеловоз — на draft фильтр ругается, заменять на farm horse
cute cartoon farm horse with a brown coat, a black mane and tail, and thick shaggy hair over its hooves, heavy sturdy build, 3/4 view facing right, full body standing, hand-painted 2D casual game art, plain flat background
```

Если генератор всё равно рисует тень или траву под ногами — не страшно,
импортёр их срезает.

У гусей палитра бедная — белый, серый, бурый, и всё. Поэтому шесть пород
разведены не мастью, а силуэтом: у китайского лебединая шея, у кубанского
полоса по шее, у тулузского кошелёк под клювом и грузное тело, итальянский
белый без шишки в отличие от холмогорского. Две пары всё равно близки —
если в игре сольются, режем так же, как резали кур.

Свинарник закрыт: четыре породы, и все четыре различаются в плитке —
чёрная вислобрюхая, розовая в чёрных пятнах, длинная с ушами торчком,
круглая с висящими на глаза ушами. Две последние обе розовые, спасает
только силуэт: если бы уши у ландраса вышли висячими, как просили
сначала, пришлось бы одну резать.

Коровник закрыт: чёрно-пёстрая и рыже-пёстрая — в плитке не спутать.
С первого раза симментальская вышла клубничной: слово `red` фильтр
пропускает, но и рисует буквально красным. Пересняли на `warm chestnut` —
тот же обход, что выручил с бурым гусем.

Курятник закрыт: шесть пород, у каждой своя масть — белая, чёрная, белая
высокая, рыжая с белой головой, тёмная с кремовым хохлом, рыжая. Десять сначала
завели зря: разницу между третьей и четвёртой белой курицей в плитке всё равно
не видно, а картинок на них уходит столько же.

Заодно из игры выпала единственная порода за кристаллы (Брама). Когда дойдут
руки до «дорогой» живности — верну такую в гусятник или коровник.

## Если генератор отказал

Leonardo иногда отвечает «did not meet content safety guidelines» на совершенно
безобидный запрос про птицу. Почему — неизвестно, но по пяти прогонам видна
закономерность в том, куда поставлен цвет:

| Не прошло | Прошло |
|---|---|
| `grey goose with a long neck` | `domestic farm goose with soft grey and white feathers` |
| `brown domestic farm goose with a swan-like neck` | `white domestic farm goose with a knob above its beak` |
| `brown farm goose with a long graceful neck` | `heavy domestic farm goose with grey and white feathers` |
| `huge fat pink sow with … her … sagging belly` | `farm pig with a big round heavy body and large floppy ears` |
| `bay draft horse with feathered hooves` | — |
| `farm horse with a brown coat …` | — |
| `workhorse with a chestnut coat …` | — |
| `pony with a warm brown coat …` | `farm horse standing in profile, big friendly eyes` |

Падали те, где цвет стоит прямо перед словом goose; проходили те, где цвет
описан после существительного: «goose **with** … feathers». Слово brown не
прошло ни разу. Это наблюдение, а не правило фильтра — сначала просто повтори
тот же запрос, классификатор шумит и со второго раза часто пропускает.

## Корма

Все пятнадцать кормов нарисованы и все пятнадцать различаются: заглушек из
набора реквизита не осталось. Последними ушли три — набор моментальных
подкормок и отруби были одинаковыми белыми бидонами, жмых пустым ящиком.

Исходники иконок лежат отдельно, в `assets-src/art/items/`: массовый
переимпорт пород идёт по `assets-src/art/*.jpg` и иначе принял бы иконку
за животное. Импортируются тем же скриптом с флагом `--item` — он не
равняет их по общей ширине и вписывает в квадрат 150, как лежат иконки
из набора:

```
for f in assets-src/art/items/*.jpg; do
  python3 tools/import-art.py "$f" "$(basename "$f" .jpg)" --item
done
```

Новую иконку надо не только положить в `public/img/iso/`, но и вписать в
`ISO.feed` в `public/game.js` — иначе клиент продолжит рисовать эмодзи.

### Сорта корма

В оригинале сорт — бумажный пакет с картинкой животного на этикетке, а сорта
разведены цветом; у нас это уже заложено эмодзи 🟥 🟩 🟦 🟪 в `content.js`,
но нарисованы сеновал и три ящика с овощами из набора.

Сделано так: нарисован один красный пакет (`assets-src/art/items/low.jpg`),
остальные три получаются сменой тона, а набор корма — стопкой из трёх пачек.
Всё это пересобирает `python3 tools/make-feed-grades.py`, поэтому исходник
один, а иконок пять.

Перекрашивается только мешок: окно по тону оставляет картинку на этикетке
в покое, иначе вышла бы синяя корова на синей траве. Тон у пакета лежит
около нуля и заворачивается через 255, у коровы начинается с 16, трава на
64, небо на 128 — окна в ±12 хватает, чтобы их разделить.

Стопку складываем из пачек без теней и ставим общую тень уже на неё:
иначе под каждым пакетом остаётся своя клякса.

```text
Косточка
cute cartoon dog bone, 3/4 view, hand-painted 2D casual game item icon, plain flat background

Рыбка
cute cartoon small fresh fish, 3/4 view, hand-painted 2D casual game item icon, plain flat background

Витаминная добавка
cute cartoon glass jar of vitamin pills with two pills lying beside it, 3/4 view, hand-painted 2D casual game item icon, plain flat background

Перепревший навоз
cute cartoon heap of dark compost with a wooden pitchfork stuck in it, 3/4 view, hand-painted 2D casual game item icon, plain flat background

Торфяной субстрат
cute cartoon open burlap sack filled with dark crumbly soil, 3/4 view, hand-painted 2D casual game item icon, plain flat background

Комбикорм универсальный
cute cartoon open paper sack filled with golden grain pellets, 3/4 view, hand-painted 2D casual game item icon, plain flat background
```

## Потом, если захочется

Председатель заменён: был пиксельный бюст 96×96 из набора Kenney, и это
был ковбой в шляпе. Теперь рисованный портрет в кепке, `--prop` кладёт
такие в `public/img/iso/prop-<id>.png` и не ставит им тень — под парящей
головой она выглядит пятном. Показывается он в самом низу двора, так что
при прокрутке вверх его не видно: это не поломка, просто он ниже сгиба.

Пёс и кот тоже заменены: сидят в шапке рядом со своими полосками сытости,
`prop-dog.png` и `prop-cat.png`. Сидящая фигура там читается лучше стоящей —
места в строке мало.

Рисованного в игре больше не осталось ничего пиксельного и ничего
подставленного не по смыслу.

## Откуда что взялось

Присланные картинки сделаны нейросетью по заказу владельца проекта; остальная
графика и её лицензии описаны в [CREDITS.md](../CREDITS.md).
