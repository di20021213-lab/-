/* Снимки всех разделов магазина по сборке без сервера. Нужен playwright:
       npm i -D playwright && npx playwright install chromium
   Запуск: node server/test/shop-tour.js  ->  docs/screenshots/magazin-raw/NN-название.png */
const { chromium } = require('playwright');
const fs = require('fs'); const http = require('http'); const path = require('path');
const PORT = 3992;
const OUT = process.env.SHOTS_DIR || path.join(__dirname, '..', '..', 'docs', 'screenshots', 'magazin-raw');
fs.mkdirSync(OUT, { recursive: true });
let n = 0;

(async () => {
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'dist', 'index.html'));
  const srv = http.createServer((q, r) => {
    r.writeHead(200, {'Content-Type':'text/html; charset=utf-8'});
    r.end('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
          '<style>body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style></head><body>' + html + '</body></html>');
  }).listen(PORT);

  const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
  const p = await b.newPage({ viewport: { width: 1000, height: 940 }, deviceScaleFactor: 2 });
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));

  const shot = async (name, wait = 350) => {
    await p.waitForTimeout(wait);
    n++;
    await p.screenshot({ path: path.join(OUT, String(n).padStart(2, '0') + '-' + name + '.png') });
    console.log('  ' + String(n).padStart(2, '0') + '-' + name);
  };
  const nav = async label => {
    await p.locator('.shop-nav button', { hasText: label }).first().click();
    await p.waitForTimeout(300);
  };

  await p.goto('http://127.0.0.1:' + PORT + '/', { waitUntil: 'load' });
  await p.waitForSelector('.bld');
  // уровень и кошелёк повыше: иначе половина витрины серая и не видно, что там есть
  await p.evaluate(() => {
    const k = 'dyshlo-offline-v2', st = JSON.parse(localStorage.getItem(k));
    st.lvl = 14; st.silver = 500000; st.gems = 40;
    st.res = Object.assign({}, st.res, { doska: 40, gvozdi: 30, kirpich: 20 });
    localStorage.setItem(k, JSON.stringify(st));
  });
  await p.reload({ waitUntil: 'load' });
  await p.waitForSelector('.bld');
  await p.waitForTimeout(500);

  await p.locator('#shopBtn').click();
  await shot('novinki', 500);

  await nav('Животные');
  await shot('zhivotnye-1');
  await p.locator('.pager button').last().click();
  await shot('zhivotnye-2', 300);
  // карточка породы — все числа, прибыль и окупаемость
  await p.locator('.good', { hasText: 'Ландрас' }).first().locator('button.pick').click();
  await shot('kartochka-porody', 400);
  await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();
  await p.waitForTimeout(300);

  await nav('Растения');
  await shot('rasteniya-1');
  await p.locator('.pager button').last().click();
  await shot('rasteniya-2', 300);

  await nav('Корма');
  await shot('korma');
  await p.locator('.good').first().locator('button.pick').click();
  await shot('kartochka-korma', 400);
  await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();
  await p.waitForTimeout(300);
  await p.locator('.shop-nav button.sub', { hasText: 'Для собаки' }).first().click();
  await shot('korma-dlya-sobaki', 300);

  await nav('Декор');
  await shot('dekor');

  await nav('Подарки');
  await shot('podarki');

  await nav('Улучшения');
  await shot('uluchsheniya');

  await nav('Помощники');
  await shot('pomoshchniki');

  await nav('Бонусы');
  await shot('bonusy');

  await nav('Ресурсы');
  await shot('resursy');

  // фильтры «по карману» и «по уровню»
  await nav('Животные');
  const labels = await p.locator('.filters label').allInnerTexts();
  console.log('фильтры:', labels.join(' | '));
  await p.locator('.filters input').first().check();
  await shot('filtr-po-karmanu', 400);
  await p.locator('.filters input').first().uncheck();

  // телефон
  await p.setViewportSize({ width: 390, height: 844 });
  await p.waitForTimeout(400);
  await nav('Животные');
  await shot('telefon-magazin', 400);

  console.log('\nошибки:', errs.length ? errs.join('\n') : 'нет');
  await b.close(); srv.close();
})();
