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

const todayKey = require("../../public/rules.js").todayKey;

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
    bailoutDay:f.bailout_day || null,
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
  st.contracts = db.prepare("SELECT house, need, silver, xp, gems, created_at FROM contracts WHERE farm_id = ? ORDER BY id")
    .all(farmId).map(c => ({house:c.house, need:c.need, silver:c.silver, xp:c.xp, gems:c.gems, at:c.created_at}));
  return st;
}

/* ------------------------------------------------------------------ запись */
const saveState = db.transaction(function(st){
  const t = now();
  db.prepare(
    "UPDATE farms SET name=?, silver=?, gems=?, xp=?, level=?, energy=?, energy_at=?, dog=?, cat=?, pet_at=?," +
    " quest_index=?, boost_until=?, vympel_until=?, helper_at=?, daily_date=?, daily_streak=?, daily_opened=?," +
    " daily_picked=?, bailout_day=?, updated_at=? WHERE id=?"
  ).run(st.farm, Math.round(st.silver), st.gems, Math.round(st.xp), st.lvl, Math.round(st.energy), st.enAt,
        Math.round(st.dog), Math.round(st.cat), st.petAt, st.quest, st.boostUntil, st.vympUntil, st.helpAt,
        st.daily.date, st.daily.streak, st.daily.opened ? 1 : 0, st.daily.picked,
        st.bailoutDay || null, t, st.id);

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

  /* Заказов всего три, поэтому проще переписать их целиком, чем сверять построчно. */
  db.prepare("DELETE FROM contracts WHERE farm_id = ?").run(st.id);
  const insC = db.prepare(
    "INSERT INTO contracts(farm_id, house, need, silver, xp, gems, created_at) VALUES(?,?,?,?,?,?,?)");
  (st.contracts || []).forEach(c => insC.run(st.id, c.house, c.need, c.silver, c.xp, c.gems | 0, c.at || t));
});

/* ------------------------------------------------------------------ правила */
/* Правила вынесены в public/rules.js — их же использует офлайн-сборка игры. */
const R = require("../../public/rules.js");
const {tick, checkQuests, publicState, todayKey: ruleDay, ACTIONS, fail} = R;

/* Один вход для всех действий: загрузили, проверили, применили, сохранили. */
const perform = db.transaction(function(farmId, action, params){
  const st = loadState(farmId);
  if(!st) throw fail("Хозяйство не найдено.");
  const tickMsg = tick(st);          // подъёмные выдаются в tick, о них надо сказать
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
  return {state:publicState(st), msg:res.msg || tickMsg || null, gift:res.gift || null, quests};
});

function leaderboard(limit){
  return db.prepare("SELECT nick, farm, level, xp, score FROM leaderboard LIMIT ?").all(limit || 100);
}
module.exports = {createFarm, farmOfUser, loadState, perform, publicState, leaderboard, todayKey};
