"use strict";
/* Правила игры: как считается энергия, созревание, урожай и что делает каждое действие.
   Один и тот же файл использует сервер (server/src/game.js) и офлайн-сборка игры,
   чтобы правила нельзя было случайно развести по двум местам. */
/* Всё внутри замыкания: в офлайн-сборке этот файл лежит на одной странице
   с клиентом, а у них есть одноимённые функции (yieldPct, maxXp, todayKey).
   Без изоляции клиентские версии затирали правила и урожай считался неверно. */
(function(){
var C = (typeof require !== "undefined" && typeof module !== "undefined")
  ? require("./content.js")
  : window.CONTENT;
var GM_PER_SEC = C.GM_PER_SEC, HOUSES = C.HOUSES, HKEYS = C.HKEYS, CAP = C.CAP,
    HOUSE_TITLES = C.HOUSE_TITLES, BREEDS = C.BREEDS, FEEDS = C.FEEDS, DECOR = C.DECOR,
    GIFTS = C.GIFTS, HELPERS = C.HELPERS, BOOSTS = C.BOOSTS, RES = C.RES,
    UPG_COST = C.UPG_COST, QUESTS = C.QUESTS, WHEEL = C.WHEEL, FRIENDS = C.FRIENDS;

var byId = function(list, id){ for(var i = 0; i < list.length; i++) if(list[i].id === id) return list[i]; return null; };
var breedOf = function(id){ return byId(BREEDS, id); };
var feedOf = function(id){ return byId(FEEDS, id); };
var maxXp = function(l){ return 100 + (l - 1) * 140; };
var MAX_ENERGY = 100;
var ENERGY_STEP = 15000;   // секунда на единицу энергии: 15 с
var PET_STEP = 60000;
function now(){ return Date.now(); }
function todayKey(d){ d = d || new Date(); return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); }

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

/** Прогон времени перед действием: энергия, питомцы, сутки подарка, помощники. */
function tick(st){
  tickEnergy(st); tickPets(st); rollDaily(st); runHelpers(st);
}
function publicState(st){
  return {
    nick:st.nick, farm:st.farm, silver:st.silver, gems:st.gems, xp:st.xp, lvl:st.lvl,
    energy:st.energy, dog:st.dog, cat:st.cat,
    feed:st.feed, res:st.res, items:st.items, gifts:st.gifts,
    houses:HKEYS.reduce(function(o, k){
      o[k] = {lvl:st.houses[k].lvl, slots:st.houses[k].slots.map(function(s){
        return {id:s.id, breed:s.breed, se:s.se, fed:s.fed, ready:s.ready, feedId:s.feedId};
      })};
      return o;
    }, {}),
    prods:st.prods, decor:st.decor, helpers:st.helpers, c:st.c, quest:st.quest,
    daily:st.daily, helped:st.helped, boostUntil:st.boostUntil, vympUntil:st.vympUntil,
    yieldPct:yieldPct(st), serverTime:now()
  };
}

var RULES = {
  MAX_ENERGY:MAX_ENERGY, ENERGY_STEP:ENERGY_STEP, PET_STEP:PET_STEP,
  byId:byId, breedOf:breedOf, feedOf:feedOf, maxXp:maxXp, todayKey:todayKey,
  tickEnergy:tickEnergy, tickPets:tickPets, tick:tick, yieldPct:yieldPct,
  capOf:capOf, freeOf:freeOf, slotState:slotState, addXp:addXp, bump:bump,
  matureMs:matureMs, fail:fail, needEnergy:needEnergy, charge:charge, grant:grant,
  checkQuests:checkQuests, reap:reap, rollDaily:rollDaily, runHelpers:runHelpers,
  ACTIONS:ACTIONS, publicState:publicState
};
if(typeof module !== "undefined" && module.exports) module.exports = RULES;
else window.RULES = RULES;
})();
