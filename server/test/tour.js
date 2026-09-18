/* Прогон по всей механике со снимками экрана: регистрация, письмо, покупка,
   кормление, созревание, сбор, склад, улучшение, задания, бонусы, соседи.
   Складывает кадры в docs/screenshots-raw. Нужен playwright:
       npm i -D playwright && npx playwright install chromium
   Запуск: node server/test/tour.js */
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs'), path = require('path');

const ROOT = path.join(__dirname, '..', '..'), PORT = Number(process.env.PORT || 3995), BASE = 'http://127.0.0.1:' + PORT;
const DB = path.join(ROOT, 'var', 'tour.db'), MAIL = path.join(ROOT, 'var', 'mail');
const SHOTS = process.env.SHOTS_DIR || path.join(ROOT, 'docs', 'screenshots-raw');
fs.mkdirSync(SHOTS, { recursive: true });
let n = 0;

(async () => {
  [DB, DB+'-wal', DB+'-shm'].forEach(f => { try { fs.unlinkSync(f); } catch(e){} });
  fs.mkdirSync(MAIL, { recursive: true });
  const srv = spawn(process.execPath, [path.join(ROOT, 'server/src/index.js')],
    { env: {...process.env, PORT:String(PORT), DB_PATH:DB, PUBLIC_URL:BASE, ENV_FILE:'/nonexistent'},
      stdio:['ignore','pipe','pipe'] });
  srv.stderr.on('data', d => process.stderr.write('[сервер] ' + d));
  await new Promise((res, rej) => { const t = setTimeout(() => rej(new Error('нет старта')), 10000);
    srv.stdout.on('data', d => { if (String(d).includes('запущен')) { clearTimeout(t); res(); } }); });

  const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
  const p = await b.newPage({ viewport: { width: 980, height: 880 }, deviceScaleFactor: 2 });
  const errs = [];
  p.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));

  const shot = async (name, wait = 350) => {
    await p.waitForTimeout(wait);
    n++;
    const file = path.join(SHOTS, String(n).padStart(2, '0') + '-' + name + '.png');
    await p.screenshot({ path: file });
    console.log('  ' + path.basename(file));
  };
  const closeTop = async () => {   // закрыть верхнюю модалку, если это окно награды
    const x = p.locator('.scrim .win.sm .win-ft .btn').last();
    if (await x.count()) { await x.click().catch(() => {}); await p.waitForTimeout(200); }
  };

  try {
    // ---------- 1. регистрация и почта ----------
    await p.goto(BASE, { waitUntil: 'networkidle' });
    await shot('vhod');
    await p.locator('.btn.flat', { hasText: 'Регистрация' }).click();
    const email = 'tour' + Date.now() + '@example.org';
    await p.fill('#f-email', email);
    await p.fill('#f-nick', 'Председатель Иван');
    await p.fill('#f-pass', 'kolhoz12345');
    await shot('registraciya');
    await p.locator('.btn.go', { hasText: 'Завести колхоз' }).click();
    await p.waitForSelector('text=Подтвердите почту');
    await shot('podtverdite-pochtu');

    const file = fs.readdirSync(MAIL).filter(f => f.includes(email)).pop();
    const eml = fs.readFileSync(path.join(MAIL, file), 'utf8').replace(/=\r?\n/g, '').replace(/=3D/g, '=');
    const link = eml.match(/http:\/\/[^\s"<>]*verify\?token=[A-Za-z0-9_-]+/)[0];
    await p.goto(link, { waitUntil: 'networkidle' });
    await p.waitForSelector('.bld');
    await shot('dvor-start', 700);

    // ---------- сервер-side выдача средств, чтобы показать поздние механики ----------
    const { DatabaseSync } = require('node:sqlite');
    const db = new DatabaseSync(DB);
    const farm = db.prepare('SELECT f.id FROM farms f JOIN users u ON u.id=f.user_id WHERE u.email=?').get(email);
    db.prepare('UPDATE farms SET silver=250000, gems=25, level=10 WHERE id=?').run(farm.id);
    db.prepare("INSERT INTO inventory(farm_id,kind,item_id,qty) VALUES(?,'res','doska',60) " +
               'ON CONFLICT(farm_id,kind,item_id) DO UPDATE SET qty=60').run(farm.id);
    db.close();
    await p.reload({ waitUntil: 'networkidle' });
    await p.waitForSelector('.bld');

    // ---------- 2. магазин ----------
    await p.locator('#shopBtn').click();
    await p.locator('.shop-nav button', { hasText: 'Животные' }).first().click();
    await shot('magazin-zhivotnye');
    await p.locator('.good', { hasText: 'Русская белая' }).locator('button.pick').click();
    await shot('kartochka-porody');
    await p.locator('.spin button').last().click();   // количество 2
    await p.locator('.btn.go', { hasText: 'Купить' }).click();
    await p.waitForTimeout(500);
    await closeTop();                                  // задание «Купи цыпленка»
    await shot('zadanie-vypolneno', 200);

    await p.locator('.shop-nav button', { hasText: 'Корма' }).first().click();
    await shot('magazin-korma');
    await p.locator('.good', { hasText: 'Корм высокого сорта' }).locator('button.pick').click();
    await p.locator('.spin input').fill('4');
    await p.locator('.spin input').press('Enter');
    await p.locator('.btn.go', { hasText: 'Купить' }).click();
    await p.waitForTimeout(400);
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    // ---------- 3. цикл: голодные → кормим → созревание → сбор ----------
    await p.locator('.bld', { hasText: 'Курятник' }).click();
    await shot('kuryatnik-golodnye');
    await p.locator('.mini', { hasText: 'Покормить всех' }).click();
    await p.waitForTimeout(600);
    await closeTop();
    await shot('kuryatnik-sozrevanie');
    await p.waitForTimeout(9000);
    await shot('kuryatnik-taimer-idet');
    await p.waitForTimeout(17000);
    await shot('kuryatnik-gotovo');
    await p.locator('.mini.go', { hasText: 'Собрать всё' }).click();
    await p.waitForTimeout(700);
    await closeTop();
    await shot('kuryatnik-posle-sbora');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    // ---------- 4. склад и сдача продукции ----------
    await p.locator('.tabs button', { hasText: 'Склад' }).click();
    await shot('sklad');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    // госзаказ — куда девать накопленное: платят вдвое против рынка
    await p.locator('.tabs button', { hasText: 'Госзаказ' }).click();
    await shot('goszakaz', 300);
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    await p.locator('.tabs button', { hasText: 'Склад' }).click();
    await p.locator('.btn.go', { hasText: 'Сдать всё' }).click();
    await p.waitForTimeout(700);
    await closeTop();
    await shot('sklad-posle-sdachi');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    // ---------- 5. огород ----------
    await p.locator('#shopBtn').click();
    await p.locator('.shop-nav button', { hasText: 'Растения' }).first().click();
    await p.locator('.good', { hasText: 'Картошка' }).locator('button.pick').click();
    await p.locator('.spin input').fill('3');
    await p.locator('.spin input').press('Enter');
    await p.locator('.btn.go', { hasText: 'Купить' }).click();
    await p.waitForTimeout(500);
    await closeTop();
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();
    await p.locator('.bld', { hasText: 'Огород' }).click();
    await shot('ogorod-posazheno');

    // ---------- 6. улучшение постройки ----------
    await p.locator('.mini', { hasText: 'Улучшить' }).click();
    await p.waitForTimeout(700);
    await closeTop();
    await shot('ogorod-posle-uluchsheniya');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    // ---------- 7. задания, бонусы, соседи, рекорды, питомцы ----------
    await p.locator('.tabs button', { hasText: 'Задания' }).click();
    await shot('spisok-zadaniy');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    await p.locator('.tabs button', { hasText: 'Бонусы' }).click();
    await shot('ezhednevnyy-podarok');
    await p.locator('.bsk').nth(5).click();
    await p.waitForTimeout(700);
    await closeTop();
    await shot('podarok-otkryt');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    await p.locator('.tabs button', { hasText: 'Друзья' }).click();
    await shot('sosedi');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    await p.locator('.tabs button', { hasText: 'TOP 100' }).click();
    await shot('top-100', 800);
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    await p.locator('.quick button').last().click();
    await shot('pes-i-kot');
    await p.locator('.win-ft .btn', { hasText: 'Закрыть' }).last().click();

    await shot('dvor-obzhitoy', 600);

    // ---------- 8. телефон ----------
    await p.setViewportSize({ width: 390, height: 844 });
    await p.waitForTimeout(500);
    await shot('telefon-dvor');
    await p.locator('.bld', { hasText: 'Курятник' }).click();
    await shot('telefon-kuryatnik');

    console.log('\nошибки консоли:', errs.length ? errs.join('\n') : 'нет');
  } finally { await b.close(); srv.kill(); }
})();
