"use strict";
/* Серверная экономика. Все цены, сроки и пределы берутся из общего справочника
   public/content.js — клиент не может назначить себе цену или урожай. */
const {db, now, logEvent} = require("./db");
const C = require("../../public/content.js");
const {GM_PER_SEC, HOUSES, HKEYS, CAP, HOUSE_TITLES, BREEDS, FEEDS, DECOR, GIFTS,
       HELPERS, BOOSTS, RES, UPG_COST, QUESTS, WHEEL, FRIENDS} = C;

const byId = (list, id) => list.find(x => x.id === id) || null;
const breedOf = id => byId(BREEDS, id);
const feedOf = id => byId(FEEDS, id);
const maxXp = l => 100 + (l - 1) * 140;
const MAX_ENERGY = 100;
const ENERGY_STEP = 15000;   // секунда на единицу энергии: 15 с
const PET_STEP = 60000;

function todayKey(d){ d = d || new Date(); return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); }

/* ------------------------------------------------------------------ создание */
const createFarm = db.transaction(function(userId, nick){
  const t = now();
  const r = db.prepare(
    "INSERT INTO farms(user_id, energy_at, pet_at, created_at, updated_at) VALUES(?,?,?,?,?)"
  ).run(userId, t, t, t, t);
  const farmId = r.lastInsertRowid;
  const ins = db.prepare("INSERT INTO buildings(farm_id, kind, level) VALUES(?,?,1)");
  HKEYS.forEach(k => ins.run(farmId, k));
  db.prepare("INSERT INTO products(farm_id, house, units, value) SELECT ?, ?, 0, 0").run(farmId, "kury");
  db.prepare("INSERT INTO inventory(farm_id, kind, item_id, qty) VALUES(?,'feed','low',3)").run(farmId);
  const coop = db.prepare("SELECT id FROM buildings WHERE farm_id = ? AND kind = 'kury'").get(farmId);
  db.prepare("INSERT INTO slots(building_id, breed, seasons_left, fed, ready_at, feed_id, created_at) VALUES(?,?,?,?,?,?,?)")
    .run(coop.id, "rusbel", 3, 1, t - 1000, "low", t);
  logEvent(farmId, "farm_created", {nick});
  return farmId;
});
function farmOfUser(userId){
  return db.prepare("SELECT * FROM farms WHERE user_id = ?").get(userId) || null;
}

/* ------------------------------------------------------------------ чтение */
function loadState(farmId){
  const f = db.prepare("SELECT f.*, u.nick FROM farms f JOIN users u ON u.id = f.user_id WHERE f.id = ?").get(farmId);
  if(!f) return null;
  const st = {
    id:f.id, nick:f.nick, farm:f.name,
    silver:f.silver, gems:f.gems, xp:f.xp, lvl:f.level,
    energy:f.energy, enAt:f.energy_at, dog:f.dog, cat:f.cat, petAt:f.pet_at,
    quest:f.quest_index, boostUntil:f.boost_until, vympUntil:f.vympel_until, helpAt:f.helper_at,
    daily:{date:f.daily_date, streak:f.daily_streak, opened:!!f.daily_opened, picked:f.daily_picked},
    feed:{}, res:{}, items:{}, gifts:{}, houses:{}, prods:{}, decor:[], helpers:[], c:{}, helped:{}
  };
  FEEDS.forEach(x => { st.feed[x.id] = 0; });
  RES.forEach(x => { st.res[x.id] = 0; });
  HKEYS.forEach(k => { st.houses[k] = {lvl:1, slots:[], _bid:null}; st.prods[k] = {n:0, val:0}; });

  db.prepare("SELECT * FROM buildings WHERE farm_id = ?").all(farmId).forEach(b => {
    if(!st.houses[b.kind]) return;
    st.houses[b.kind].lvl = b.level;
    st.houses[b.kind]._bid = b.id;
  });
  const slots = db.prepare(
    "SELECT s.*, b.kind FROM slots s JOIN buildings b ON b.id = s.building_id WHERE b.farm_id = ? ORDER BY s.id"
  ).all(farmId);
  slots.forEach(s => {
    if(!st.houses[s.kind]) return;
    st.houses[s.kind].slots.push({id:s.id, breed:s.breed, se:s.seasons_left, fed:!!s.fed, ready:s.ready_at, feedId:s.feed_id});
  });
  db.prepare("SELECT * FROM inventory WHERE farm_id = ?").all(farmId).forEach(i => {
    const box = i.kind === "feed" ? st.feed : i.kind === "res" ? st.res : i.kind === "gift" ? st.gifts : st.items;
    box[i.item_id] = i.qty;
  });
  db.prepare("SELECT * FROM products WHERE farm_id = ?").all(farmId).forEach(p => {
    if(st.prods[p.house]) st.prods[p.house] = {n:p.units, val:p.value};
  });
  db.prepare("SELECT decor_id FROM decor WHERE farm_id = ?").all(farmId).forEach(d => st.decor.push(d.decor_id));
  db.prepare("SELECT helper_id FROM helpers WHERE farm_id = ?").all(farmId).forEach(h => st.helpers.push(h.helper_id));
  db.prepare("SELECT key, value FROM counters WHERE farm_id = ?").all(farmId).forEach(c => { st.c[c.key] = c.value; });
  db.prepare("SELECT friend_idx, day FROM friend_help WHERE farm_id = ? AND day = ?").all(farmId, todayKey())
    .forEach(h => { st.helped[h.day + ":" + h.friend_idx] = 1; });
  return st;
}

/* ------------------------------------------------------------------ запись */
const saveState = db.transaction(function(st){
  const t = now();
  db.prepare(
    "UPDATE farms SET name=?, silver=?, gems=?, xp=?, level=?, energy=?, energy_at=?, dog=?, cat=?, pet_at=?," +
    " quest_index=?, boost_until=?, vympel_until=?, helper_at=?, daily_date=?, daily_streak=?, daily_opened=?," +
    " daily_picked=?, updated_at=? WHERE id=?"
  ).run(st.farm, Math.round(st.silver), st.gems, Math.round(st.xp), st.lvl, Math.round(st.energy), st.enAt,
        Math.round(st.dog), Math.round(st.cat), st.petAt, st.quest, st.boostUntil, st.vympUntil, st.helpAt,
        st.daily.date, st.daily.streak, st.daily.opened ? 1 : 0, st.daily.picked, t, st.id);

  const upB = db.prepare("UPDATE buildings SET level = ? WHERE id = ?");
  const insS = db.prepare("INSERT INTO slots(building_id, breed, seasons_left, fed, ready_at, feed_id, created_at) VALUES(?,?,?,?,?,?,?)");
  const upS = db.prepare("UPDATE slots SET breed=?, seasons_left=?, fed=?, ready_at=?, feed_id=? WHERE id=?");
  const delS = db.prepare("DELETE FROM slots WHERE id = ?");
  HKEYS.forEach(k => {
    const h = st.houses[k];
    upB.run(h.lvl, h._bid);
    const have = db.prepare("SELECT id FROM slots WHERE building_id = ?").all(h._bid).map(r => r.id);
    const keep = [];
    h.slots.forEach(s => {
      if(s.id){ upS.run(s.breed, s.se, s.fed ? 1 : 0, Math.round(s.ready), s.feedId, s.id); keep.push(s.id); }
      else { s.id = insS.run(h._bid, s.breed, s.se, s.fed ? 1 : 0, Math.round(s.ready), s.feedId, t).lastInsertRowid; keep.push(s.id); }
    });
    have.filter(id => keep.indexOf(id) < 0).forEach(id => delS.run(id));
  });

  const upInv = db.prepare(
    "INSERT INTO inventory(farm_id, kind, item_id, qty) VALUES(?,?,?,?) " +
    "ON CONFLICT(farm_id, kind, item_id) DO UPDATE SET qty = excluded.qty");
  Object.keys(st.feed).forEach(id => upInv.run(st.id, "feed", id, Math.max(0, st.feed[id] | 0)));
  Object.keys(st.res).forEach(id => upInv.run(st.id, "res", id, Math.max(0, st.res[id] | 0)));
  Object.keys(st.gifts).forEach(id => upInv.run(st.id, "gift", id, Math.max(0, st.gifts[id] | 0)));
  Object.keys(st.items).forEach(id => upInv.run(st.id, "item", id, Math.max(0, st.items[id] | 0)));

  const upP = db.prepare(
    "INSERT INTO products(farm_id, house, units, value) VALUES(?,?,?,?) " +
    "ON CONFLICT(farm_id, house) DO UPDATE SET units = excluded.units, value = excluded.value");
  HKEYS.forEach(k => upP.run(st.id, k, st.prods[k].n, st.prods[k].val));

  const upD = db.prepare("INSERT OR IGNORE INTO decor(farm_id, decor_id, bought_at) VALUES(?,?,?)");
  st.decor.forEach(d => upD.run(st.id, d, t));
  const upH = db.prepare("INSERT OR IGNORE INTO helpers(farm_id, helper_id, hired_at) VALUES(?,?,?)");
  st.helpers.forEach(h => upH.run(st.id, h, t));
  const upC = db.prepare(
    "INSERT INTO counters(farm_id, key, value) VALUES(?,?,?) " +
    "ON CONFLICT(farm_id, key) DO UPDATE SET value = excluded.value");
  Object.keys(st.c).forEach(k => upC.run(st.id, k, st.c[k] | 0));
});

/* ------------------------------------------------------------------ правила */
function tickEnergy(st){
  const g = Math.floor((now() - st.enAt) / ENERGY_STEP);
  if(g > 0){ st.energy = Math.min(MAX_ENERGY, st.energy + g); st.enAt += g * ENERGY_STEP; }
  if(st.energy >= MAX_ENERGY) st.enAt = now();
}
function tickPets(st){
  const g = Math.floor((now() - st.petAt) / PET_STEP);
  if(g > 0){ st.dog = Math.max(0, st.dog - g * 2); st.cat = Math.max(0, st.cat - g * 2); st.petAt += g * PET_STEP; }
}
function yieldPct(st){
  let p = 100;
  if(st.dog > 0) p += 3;
  if(st.cat > 0) p += 5;
  st.decor.forEach(id => { const d = byId(DECOR, id); if(d) p += d.bonus; });
  if(now() < st.vympUntil) p += 25;
  return p;
}
const capOf = (st, k) => CAP[st.houses[k].lvl - 1];
const freeOf = (st, k) => capOf(st, k) - st.houses[k].slots.length;
const slotState = a => !a.fed ? "hungry" : (now() >= a.ready ? "ready" : "growing");
function addXp(st, n){
  st.xp += n;
  const up = [];
  while(st.xp >= maxXp(st.lvl)){
    st.xp -= maxXp(st.lvl); st.lvl++; st.gems += 1; st.energy = MAX_ENERGY; up.push(st.lvl);
  }
  return up;
}
function bump(st, k, by){ st.c[k] = (st.c[k] || 0) + (by == null ? 1 : by); }
function matureMs(st, b, f){
  if(f.inst) return 0;
  const boost = now() < st.boostUntil ? 0.5 : 1;
  return b.mat / GM_PER_SEC * 1000 * f.sp * boost;
}
function fail(msg){ const e = new Error(msg); e.gameError = true; return e; }
function needEnergy(st, n){ tickEnergy(st); if(st.energy < n) throw fail("Энергия кончилась. Передохни или выпей квасу."); st.energy -= n; }
function charge(st, s, c){
  if(s && st.silver < s) throw fail("Не хватает серебра.");
  if(c && st.gems < c) throw fail("Не хватает кристаллов.");
  st.silver -= s || 0; st.gems -= c || 0;
}
function grant(st, rw){
  if(rw.t === "silver") st.silver += rw.n;
  else if(rw.t === "gems") st.gems += rw.n;
  else if(rw.t === "xp") addXp(st, rw.n);
  else if(rw.t === "feed") st.feed[rw.id] = (st.feed[rw.id] || 0) + rw.n;
  else if(rw.t === "res") st.res[rw.id] = (st.res[rw.id] || 0) + rw.n;
  else if(rw.t === "item") st.items[rw.id] = (st.items[rw.id] || 0) + rw.n;
  else if(rw.t === "breed"){
    const b = breedOf(rw.id);
    if(b && freeOf(st, b.h) > 0) st.houses[b.h].slots.push({id:null, breed:b.id, se:b.se, fed:false, ready:0, feedId:"low"});
    else st.silver += 300;
  }
}
function checkQuests(st){
  const done = [];
  while(st.quest < QUESTS.length){
    const q = QUESTS[st.quest];
    const prog = q.k === "lvl" ? st.lvl : (st.c[q.k] || 0);
    if(prog < q.n) break;
    grant(st, q.rw);
    done.push({index:st.quest, t:q.t, rw:q.rw});
    st.quest++;
  }
  return done;
}

/* ------------------------------------------------------------------ действия */
const ACTIONS = {
  plant(st, p){
    const b = breedOf(String(p.breed || ""));
    if(!b) throw fail("Такой породы в магазине нет.");
    if(st.lvl < b.lvl) throw fail("Доступно с " + b.lvl + " уровня.");
    const qty = Math.max(1, Math.min(99, parseInt(p.qty, 10) || 1));
    const n = Math.min(qty, freeOf(st, b.h));
    if(n < 1) throw fail(HOUSES[b.h].n + ": свободных мест нет, нужно улучшение.");
    charge(st, b.s * n, b.c * n);
    for(let i = 0; i < n; i++) st.houses[b.h].slots.push({id:null, breed:b.id, se:b.se, fed:false, ready:0, feedId:"low"});
    bump(st, "buy_" + b.h, n);
    addXp(st, Math.round(b.xp / 10) * n);
    return {msg:b.n + " ×" + n + " — на месте."};
  },
  feed(st, p){
    const k = String(p.house || ""); if(!HOUSES[k]) throw fail("Нет такой постройки.");
    const a = st.houses[k].slots.find(x => x.id === Number(p.slot));
    if(!a) throw fail("Место пустое.");
    if(a.fed) throw fail("Уже покормлено.");
    const f = feedOf(String(p.feed || "")); if(!f || f.pet || f.gives) throw fail("Таким кормить нельзя.");
    if(!st.feed[f.id]) throw fail(f.n + " кончился.");
    needEnergy(st, 1);
    st.feed[f.id]--;
    a.fed = true; a.feedId = f.id;
    a.ready = now() + matureMs(st, breedOf(a.breed), f);
    bump(st, "fed"); addXp(st, 2);
    return {msg:"Покормлено."};
  },
  feedAll(st, p){
    const k = String(p.house || ""); if(!HOUSES[k]) throw fail("Нет такой постройки.");
    const order = ["elite", "high", "mid", "univer", "low"];
    let n = 0;
    st.houses[k].slots.forEach(a => {
      if(a.fed) return;
      tickEnergy(st);
      if(st.energy < 1) return;
      const fid = order.find(id => st.feed[id] > 0);
      if(!fid) return;
      const f = feedOf(fid);
      st.energy--; st.feed[fid]--;
      a.fed = true; a.feedId = fid;
      a.ready = now() + matureMs(st, breedOf(a.breed), f);
      bump(st, "fed"); addXp(st, 2); n++;
    });
    if(!n) throw fail("Кормить некого или корма нет.");
    return {msg:"Покормлено: " + n};
  },
  harvest(st, p){
    const k = String(p.house || ""); if(!HOUSES[k]) throw fail("Нет такой постройки.");
    const a = st.houses[k].slots.find(x => x.id === Number(p.slot));
    if(!a) throw fail("Место пустое.");
    if(slotState(a) !== "ready") throw fail("Ещё не созрело.");
    needEnergy(st, 1);
    const got = reap(st, k, a);
    return {msg:"+" + got + " " + HOUSES[k].prod.n.toLowerCase()};
  },
  harvestAll(st, p){
    const k = String(p.house || ""); if(!HOUSES[k]) throw fail("Нет такой постройки.");
    let total = 0;
    st.houses[k].slots.slice().forEach(a => {
      if(slotState(a) !== "ready") return;
      tickEnergy(st);
      if(st.energy < 1) return;
      st.energy--;
      total += reap(st, k, a);
    });
    if(!total) throw fail("Собирать нечего.");
    return {msg:"Собрано: " + total};
  },
  sell(st, p){
    const k = String(p.house || ""); if(!HOUSES[k]) throw fail("Нет такой постройки.");
    const pr = st.prods[k];
    if(!pr.n) throw fail("По этой позиции склад пуст.");
    st.silver += pr.val; bump(st, "sold_silver", pr.val); addXp(st, Math.floor(pr.val / 60));
    const msg = "Сдано " + pr.n + " ед. на " + pr.val + " серебра.";
    pr.n = 0; pr.val = 0;
    return {msg};
  },
  sellAll(st){
    let n = 0, v = 0;
    HKEYS.forEach(k => { n += st.prods[k].n; v += st.prods[k].val; st.prods[k].n = 0; st.prods[k].val = 0; });
    if(!n) throw fail("Склад пуст.");
    st.silver += v; bump(st, "sold_silver", v); addXp(st, Math.floor(v / 60));
    return {msg:"Сдано " + n + " ед. на " + v + " серебра."};
  },
  upgrade(st, p){
    const k = String(p.house || ""); if(!HOUSES[k]) throw fail("Нет такой постройки.");
    const h = st.houses[k];
    if(h.lvl >= 4) throw fail("Дальше некуда, это уже элитная ферма.");
    const c = UPG_COST[k][h.lvl];
    if((st.res.doska || 0) < c.b) throw fail("Не хватает досок: нужно " + c.b + ".");
    const bySilver = st.silver >= c.s;
    if(!bySilver && st.gems < c.c) throw fail("Нужно " + c.s + " серебра или " + c.c + " кристаллов.");
    if(bySilver) st.silver -= c.s; else st.gems -= c.c;
    st.res.doska -= c.b;
    h.lvl++;
    bump(st, "upg"); addXp(st, 120);
    return {msg:HOUSES[k].n + " → " + HOUSE_TITLES[h.lvl - 1] + ". Мест: " + capOf(st, k)};
  },
  buy(st, p){
    const kind = String(p.kind || ""), id = String(p.id || "");
    const qty = Math.max(1, Math.min(99, parseInt(p.qty, 10) || 1));
    if(kind === "feed"){
      const f = feedOf(id); if(!f) throw fail("Нет такого корма.");
      charge(st, f.s * qty, f.c * qty);
      if(f.gives) Object.keys(f.gives).forEach(g => { st.feed[g] = (st.feed[g] || 0) + f.gives[g] * qty; });
      else st.feed[f.id] = (st.feed[f.id] || 0) + qty;
      return {msg:f.n + " ×" + qty};
    }
    if(kind === "res"){
      const r = byId(RES, id); if(!r) throw fail("Нет такого ресурса.");
      charge(st, r.s * qty, r.c * qty);
      st.res[r.id] = (st.res[r.id] || 0) + qty;
      return {msg:r.n + " ×" + qty};
    }
    if(kind === "decor"){
      const d = byId(DECOR, id); if(!d) throw fail("Нет такого декора.");
      if(st.decor.indexOf(d.id) >= 0) throw fail("Уже стоит во дворе.");
      charge(st, d.s, d.c);
      st.decor.push(d.id); addXp(st, 20);
      return {msg:d.n + " — во двор."};
    }
    if(kind === "gift"){
      const g = byId(GIFTS, id); if(!g) throw fail("Нет такого подарка.");
      charge(st, g.s * qty, g.c * qty);
      st.gifts[g.id] = (st.gifts[g.id] || 0) + qty; addXp(st, 10);
      return {msg:g.n + " ×" + qty};
    }
    if(kind === "helper"){
      const h = byId(HELPERS, id); if(!h) throw fail("Нет такого помощника.");
      if(st.helpers.indexOf(h.id) >= 0) throw fail("Уже нанят.");
      charge(st, h.s, h.c);
      st.helpers.push(h.id);
      return {msg:h.n + " нанят."};
    }
    if(kind === "boost"){
      const b = byId(BOOSTS, id); if(!b) throw fail("Нет такого бонуса.");
      charge(st, b.s * qty, b.c * qty);
      st.items[b.id] = (st.items[b.id] || 0) + qty;
      return {msg:b.n + " ×" + qty};
    }
    throw fail("Неизвестный товар.");
  },
  useItem(st, p){
    const id = String(p.id || "");
    if(!byId(BOOSTS, id)) throw fail("Такого бонуса нет.");
    if(!st.items[id]) throw fail("Бонус кончился.");
    st.items[id]--;
    if(id === "udar") st.boostUntil = now() + 180000;
    if(id === "kvas"){ st.energy = MAX_ENERGY; st.enAt = now(); }
    if(id === "vymp") st.vympUntil = now() + 300000;
    return {msg:"Применено."};
  },
  feedPet(st, p){
    const which = p.pet === "cat" ? "cat" : "dog";
    const f = feedOf(which === "dog" ? "bone" : "fish");
    charge(st, f.s, f.c);
    st[which] = 100; st.petAt = now();
    bump(st, "fed_" + which); addXp(st, 5);
    return {msg:(which === "dog" ? "Пёс" : "Кот") + " накормлен."};
  },
  daily(st, p){
    rollDaily(st);
    if(st.daily.opened) throw fail("Сегодня подарок уже открыт.");
    const idx = Math.max(0, Math.min(15, parseInt(p.basket, 10) || 0));
    const pick = WHEEL[Math.floor(Math.random() * WHEEL.length)];
    const rw = Object.assign({}, pick);
    if(rw.t === "silver") rw.n = rw.n * Math.max(1, st.daily.streak);
    st.daily.opened = true; st.daily.picked = idx;
    grant(st, {t:rw.t, id:rw.id, n:rw.n});
    return {msg:"В корзинке: " + rw.nm, gift:rw};
  },
  helpFriend(st, p){
    const i = parseInt(p.friend, 10);
    if(!(i >= 0 && i < FRIENDS.length)) throw fail("Нет такого соседа.");
    const key = todayKey() + ":" + i;
    if(st.helped[key]) throw fail("Сегодня ты уже помогал.");
    needEnergy(st, 2);
    st.helped[key] = 1;
    st._newHelp = i;
    const sv = 120 + Math.floor(Math.random() * 200);
    st.silver += sv; addXp(st, 15);
    return {msg:"Помог соседу: +" + sv + " серебра."};
  },
  gift(st, p){
    const i = parseInt(p.friend, 10);
    const id = String(p.id || "");
    if(!(i >= 0 && i < FRIENDS.length)) throw fail("Нет такого соседа.");
    if(!st.gifts[id]) throw fail("Такого подарка нет в сумке.");
    st.gifts[id]--;
    addXp(st, 20);
    return {msg:FRIENDS[i].n + " получает подарок."};
  },
  rename(st, p){
    const v = String(p.name || "").trim().slice(0, 24);
    if(v.length < 2) throw fail("Слишком короткое название.");
    st.farm = v;
    return {msg:"Колхоз теперь «" + v + "»."};
  }
};

function reap(st, k, a){
  const b = breedOf(a.breed), f = feedOf(a.feedId) || FEEDS[0];
  const units = Math.round(b.y * (f.ym || 1) * yieldPct(st) / 100);
  st.prods[k].n += units;
  st.prods[k].val += units * b.u;
  a.se--; a.fed = false; a.ready = 0;
  bump(st, "harvest_" + k); bump(st, "harvest_" + b.id); bump(st, "harvest_total", units);
  addXp(st, b.xp);
  if(a.se <= 0){
    const i = st.houses[k].slots.indexOf(a);
    if(i >= 0) st.houses[k].slots.splice(i, 1);
  }
  return units;
}
function rollDaily(st){
  const t = todayKey();
  if(st.daily.date !== t){
    const y = todayKey(new Date(Date.now() - 86400000));
    st.daily.streak = st.daily.date === y ? Math.min(5, st.daily.streak + 1) : 1;
    st.daily.date = t; st.daily.opened = false; st.daily.picked = -1;
  }
}
function runHelpers(st){
  if(st.helpers.indexOf("batrak") >= 0 && now() - st.helpAt > 60000){
    st.helpAt = now();
    HKEYS.forEach(k => st.houses[k].slots.slice().forEach(a => {
      if(slotState(a) === "ready" && st.energy > 5){ st.energy--; reap(st, k, a); }
    }));
  }
  if(st.helpers.indexOf("pastushok") >= 0){
    HKEYS.forEach(k => st.houses[k].slots.forEach(a => {
      if(!a.fed && st.feed.low > 0 && st.energy > 10){
        st.feed.low--; st.energy--;
        a.fed = true; a.feedId = "low";
        a.ready = now() + matureMs(st, breedOf(a.breed), feedOf("low"));
        bump(st, "fed");
      }
    }));
  }
}

/* Один вход для всех действий: загрузили, проверили, применили, сохранили. */
const perform = db.transaction(function(farmId, action, params){
  const st = loadState(farmId);
  if(!st) throw fail("Хозяйство не найдено.");
  tickEnergy(st); tickPets(st); rollDaily(st); runHelpers(st);
  let res = {msg:null};
  if(action !== "sync"){
    const fn = ACTIONS[action];
    if(!fn) throw fail("Неизвестное действие.");
    res = fn(st, params || {}) || {};
  }
  const quests = checkQuests(st);
  saveState(st);
  if(st._newHelp != null){
    db.prepare("INSERT OR IGNORE INTO friend_help(farm_id, friend_idx, day) VALUES(?,?,?)")
      .run(farmId, st._newHelp, todayKey());
    delete st._newHelp;
  }
  if(action !== "sync") logEvent(farmId, action, params);
  return {state:publicState(st), msg:res.msg || null, gift:res.gift || null, quests};
});

function publicState(st){
  return {
    nick:st.nick, farm:st.farm, silver:st.silver, gems:st.gems, xp:st.xp, lvl:st.lvl,
    energy:st.energy, dog:st.dog, cat:st.cat,
    feed:st.feed, res:st.res, items:st.items, gifts:st.gifts,
    houses:HKEYS.reduce((o, k) => {
      o[k] = {lvl:st.houses[k].lvl, slots:st.houses[k].slots.map(s => ({id:s.id, breed:s.breed, se:s.se, fed:s.fed, ready:s.ready, feedId:s.feedId}))};
      return o;
    }, {}),
    prods:st.prods, decor:st.decor, helpers:st.helpers, c:st.c, quest:st.quest,
    daily:st.daily, helped:st.helped, boostUntil:st.boostUntil, vympUntil:st.vympUntil,
    yieldPct:yieldPct(st), serverTime:now()
  };
}
function leaderboard(limit){
  return db.prepare("SELECT nick, farm, level, xp, score FROM leaderboard LIMIT ?").all(limit || 100);
}
module.exports = {createFarm, farmOfUser, loadState, perform, publicState, leaderboard, todayKey};
