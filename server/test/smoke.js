"use strict";
/* Сквозная проверка: регистрация → письмо → подтверждение → игра.
   Запуск: node server/test/smoke.js  (поднимает сервер на своей базе) */
const {spawn} = require("child_process");
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const PORT = 3999;
const BASE = "http://127.0.0.1:" + PORT;
const DB_PATH = path.join(ROOT, "var", "test.db");
const MAIL_DIR = path.join(ROOT, "var", "mail");

let cookie = "";
async function call(url, body, method){
  const res = await fetch(BASE + url, {
    method: method || (body ? "POST" : "GET"),
    headers: Object.assign({}, body ? {"Content-Type":"application/json"} : {}, cookie ? {cookie} : {}),
    body: body ? JSON.stringify(body) : undefined,
    redirect: "manual"
  });
  const set = res.headers.get("set-cookie");
  if(set) cookie = set.split(";")[0];
  let data = null;
  try{ data = await res.json(); }catch(e){}
  return {status:res.status, data, location:res.headers.get("location")};
}
const ok = (name) => console.log("  ✓ " + name);

(async () => {
  [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"].forEach(f => { try{ fs.unlinkSync(f); }catch(e){} });
  fs.mkdirSync(MAIL_DIR, {recursive:true});
  fs.readdirSync(MAIL_DIR).forEach(f => fs.unlinkSync(path.join(MAIL_DIR, f)));

  const srv = spawn(process.execPath, [path.join(ROOT, "server", "src", "index.js")], {
    env: Object.assign({}, process.env, {PORT:String(PORT), DB_PATH, PUBLIC_URL:BASE}),
    stdio: ["ignore", "pipe", "pipe"]
  });
  srv.stderr.on("data", d => process.stderr.write("[сервер] " + d));
  await new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error("сервер не поднялся")), 10000);
    srv.stdout.on("data", d => { if(String(d).includes("запущен")){ clearTimeout(t); res(); } });
  });

  try{
    const email = "pred" + Date.now() + "@example.org";

    let r = await call("/api/auth/register", {email, password:"kolhoz12345", nick:"Председатель"});
    assert.strictEqual(r.status, 200, "регистрация");
    ok("регистрация принята");

    r = await call("/api/game");
    assert.strictEqual(r.status, 401, "без сессии в игру нельзя");
    ok("без входа игра закрыта");

    r = await call("/api/auth/login", {email, password:"kolhoz12345"});
    assert.strictEqual(r.status, 200, "вход");
    r = await call("/api/game");
    assert.strictEqual(r.status, 403, "неподтверждённая почта");
    assert.strictEqual(r.data.code, "email_unverified");
    ok("до подтверждения почты играть нельзя");

    r = await call("/api/auth/login", {email, password:"неверный"});
    assert.strictEqual(r.status, 401, "неверный пароль");
    ok("неверный пароль отклонён");

    const files = fs.readdirSync(MAIL_DIR).filter(f => f.includes(email));
    assert.ok(files.length, "письмо не отправлено");
    const eml = fs.readFileSync(path.join(MAIL_DIR, files[0]), "utf8")
      .replace(/=\r?\n/g, "")      // мягкие переносы quoted-printable
      .replace(/=3D/g, "=");        // и экранированный знак равенства
    const token = (eml.match(/verify\?token=([A-Za-z0-9_-]+)/) || [])[1];
    assert.ok(token, "в письме нет ссылки");
    ok("письмо со ссылкой отправлено");

    r = await call("/api/auth/verify?token=" + token);
    assert.strictEqual(r.status, 302);
    assert.ok(String(r.location).includes("verify=ok"));
    ok("почта подтверждена, сессия выдана");

    r = await call("/api/auth/verify?token=" + token);
    assert.ok(String(r.location).includes("verify=fail"), "токен одноразовый");
    ok("повторная ссылка не работает");

    r = await call("/api/game");
    assert.strictEqual(r.status, 200);
    let S = r.data.state;
    assert.strictEqual(S.silver, 500);
    assert.strictEqual(S.houses.kury.slots.length, 1);
    ok("хозяйство создано: 500 серебра и курица на насесте");

    const slot = S.houses.kury.slots[0];
    r = await call("/api/game/harvest", {house:"kury", slot:slot.id});
    assert.strictEqual(r.status, 200, r.data && r.data.error);
    S = r.data.state;
    assert.ok(S.prods.kury.n >= 47, "яйца на складе");
    assert.strictEqual(S.houses.kury.slots[0].se, 2, "сезон списан");
    ok("урожай собран: " + S.prods.kury.n + " яиц, сезонов осталось " + S.houses.kury.slots[0].se);

    r = await call("/api/game/sell", {house:"kury"});
    S = r.data.state;
    assert.ok(S.silver > 500, "серебро не начислено");
    assert.strictEqual(S.prods.kury.n, 0);
    ok("продукция сдана, серебра стало " + S.silver);

    r = await call("/api/game/plant", {breed:"rusbel", qty:99});
    S = r.data.state;
    assert.strictEqual(S.houses.kury.slots.length, 3, "в домик влезает только три");
    ok("вместимость постройки соблюдена: куплено под завязку, " + S.houses.kury.slots.length + "/3");

    assert.ok(r.data.quests.length >= 1, "задание не закрылось");
    assert.strictEqual(r.data.quests[0].t, "Купи цыпленка");
    ok("задание «" + r.data.quests[0].t + "» засчитано сервером, награда: " + r.data.quests[0].rw.nm);

    let before = S.silver;
    r = await call("/api/game/buy", {kind:"feed", id:"low", qty:1});
    S = r.data.state;
    assert.strictEqual(S.silver, before - 90, "цена корма берётся с сервера");
    ok("корм куплен по серверной цене");

    before = S.silver;
    r = await call("/api/game/buy", {kind:"feed", id:"low", qty:1, s:0, c:0, price:1, silver:999999});
    S = r.data.state;
    assert.strictEqual(S.silver, before - 90, "цену из запроса сервер игнорирует");
    ok("подставленная в запрос цена проигнорирована");

    r = await call("/api/game/plant", {breed:"simment", qty:1});
    assert.strictEqual(r.status, 400);
    assert.ok(/уровня/.test(r.data.error), r.data.error);
    ok("породу не по уровню сервер не продаёт");

    r = await call("/api/game/plant", {breed:"нет-такой", qty:1});
    assert.strictEqual(r.status, 400);
    ok("несуществующая порода отклонена");

    r = await call("/api/game/plant", {breed:"holmkor", qty:1});
    assert.strictEqual(r.status, 400);
    ok("покупка не по карману отклонена");

    r = await call("/api/game/harvest", {house:"kury", slot:S.houses.kury.slots[2].id});
    assert.strictEqual(r.status, 400);
    ok("несозревшее собрать нельзя");

    r = await call("/api/game/upgrade", {house:"kury"});
    assert.strictEqual(r.status, 400);
    assert.ok(/досок/i.test(r.data.error), r.data.error);
    ok("улучшение без досок отклонено");

    r = await call("/api/top");
    assert.ok(r.data.top.length >= 1, "таблица рекордов пуста");
    ok("таблица рекордов отдаётся: " + r.data.top[0].nick);

    r = await call("/api/auth/logout", {});
    r = await call("/api/game");
    assert.strictEqual(r.status, 401);
    ok("выход из аккаунта гасит сессию");

    /* данные действительно в базе, а не в памяти процесса */
    const Database = require("better-sqlite3");
    const db = new Database(DB_PATH, {readonly:true});
    const u = db.prepare("SELECT * FROM users WHERE email = ?").get(email);
    assert.ok(u && u.email_verified_at, "пользователь не сохранён");
    assert.ok(!u.password_hash.includes("kolhoz12345"), "пароль хранится открытым текстом");
    assert.ok(u.password_hash.startsWith("scrypt$"), "пароль не захеширован");
    const slots = db.prepare(
      "SELECT COUNT(*) n FROM slots s JOIN buildings b ON b.id = s.building_id JOIN farms f ON f.id = b.farm_id WHERE f.user_id = ?"
    ).get(u.id);
    assert.strictEqual(slots.n, 3, "слоты не записались");
    const ev = db.prepare("SELECT COUNT(*) n FROM events").get();
    assert.ok(ev.n > 0, "журнал пуст");
    db.close();
    ok("в базе: пользователь, хеш пароля scrypt, " + slots.n + " слота, " + ev.n + " записей в журнале");

    console.log("\nВсе проверки прошли.");
  } finally {
    srv.kill();
  }
})().catch(e => { console.error("\nПРОВАЛ: " + e.message); process.exit(1); });
