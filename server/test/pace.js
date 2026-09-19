/* Считает, за сколько реального времени игрок доходит до каждого уровня.
   Крутит НАСТОЯЩИЕ правила (public/rules.js) на подменённых часах, поэтому
   числа те же, что в игре, а не прикидка на салфетке. Нужен, когда правится
   темп: сроки созревания в content.js или кривая опыта XP_BASE/XP_POW.
   Переменные окружения MAT_A, MAT_K, XP_A, XP_K позволяют прогнать вариант,
   ничего не меняя в файлах.
   Запуск: node server/test/pace.js */
const nodePath = require('path');
const path = nodePath.join(__dirname, '..', '..', 'public') + nodePath.sep;
const C = require(path + 'content.js');

let T = Date.now();
const realNow = Date.now;
Date.now = () => T;                       // rules.js зовёт Date.now() на каждом шаге

const R = require(path + 'rules.js');

/* Подбор темпа: множитель созревания и кривая опыта задаются переменными
   окружения, чтобы прогнать варианты, не правя файлы. */
if(process.env.MAT_A){
  const a = Number(process.env.MAT_A), k = Number(process.env.MAT_K || 1.24);
  C.BREEDS.forEach(b => { b.mat = Math.round(b.mat * a * Math.pow(k, b.lvl - 1)); });
}
if(process.env.XP_A) C.XP_BASE = Number(process.env.XP_A);
if(process.env.XP_K) C.XP_POW = Number(process.env.XP_K);

let uid = 1;
function fresh(){
  const t = Date.now();
  const s = {
    nick:'Председатель', farm:'Червонэ дышло',
    silver:500, gems:0, xp:0, lvl:1, energy:33, enAt:t,
    dog:60, cat:60, petAt:t, quest:0, boostUntil:0, vympUntil:0, helpAt:0,
    daily:{date:null, streak:0, opened:false, picked:-1},
    feed:{}, res:{}, items:{}, gifts:{}, houses:{}, prods:{},
    decor:[], helpers:[], c:{}, helped:{}, contracts:[]
  };
  C.FEEDS.forEach(f => s.feed[f.id] = 0);
  C.RES.forEach(r => s.res[r.id] = 0);
  C.HKEYS.forEach(k => { s.houses[k] = {lvl:1, slots:[]}; s.prods[k] = {n:0, val:0}; });
  s.feed.low = 3;
  s.houses.kury.slots = [{id:uid++, breed:'rusbel', se:3, fed:true, ready:t - 1000, feedId:'low'}];
  return s;
}

const act = (st, name, p) => { try { R.ACTIONS[name](st, p || {}); return true; } catch(e){ return false; } };

/** Политика «нормального игрока»: сначала корм (без него всё встаёт),
    потом новые породы — но только на свободные деньги, с запасом на корм. */
function play(st){
  R.tick(st);
  C.HKEYS.forEach(k => act(st, 'harvestAll', {house:k}));
  if(C.HKEYS.some(k => st.prods[k].n > 0)) act(st, 'sellAll', {});

  // бедный игрок кормит крапивой, богатый — низким сортом: обе роли важны для темпа
  const lowFeed = C.FEEDS.find(f => f.id === (st.silver > 5000 ? 'low' : 'krapiva'));
  const stock = C.HKEYS.reduce((n, k) => n + st.houses[k].slots.filter(a => !a.fed).length, 0);
  const have = (st.feed.low || 0) + (st.feed.krapiva || 0);
  if(have < stock){
    const can = Math.min(20, Math.floor(st.silver * 0.5 / lowFeed.s));
    if(can >= 1) act(st, 'buy', {kind:'feed', id:lowFeed.id, qty:can});
  }
  const need = stock;
  C.HKEYS.forEach(k => act(st, 'feedAll', {house:k}));

  // Запас на корм: держим деньги на один прокорм всего двора плюс пара порций.
  // Без этого игрок скупает живность и остаётся без корма — двор стоит.
  const busy = C.HKEYS.reduce((n, k) => n + st.houses[k].slots.length, 0);
  const reserve = lowFeed.s * (busy + 2);
  C.HKEYS.forEach(k => {
    let free = R.freeOf(st, k);
    while(free > 0){
      const cands = C.BREEDS
        .filter(b => b.h === k && b.lvl <= st.lvl && !b.c && b.s <= st.silver - reserve)
        .sort((x, y) => y.s - x.s);
      if(!cands.length) break;
      if(!act(st, 'plant', {breed:cands[0].id, qty:1})) break;
      free--;
    }
  });

  (st.contracts || []).forEach((c, i) => {
    if(st.prods[c.house] && st.prods[c.house].n >= c.need) act(st, 'contract', {slot:i});
  });

  C.HKEYS.forEach(k => {
    const h = st.houses[k], cst = C.UPG_COST[k][h.lvl];
    if(!cst) return;
    if(st.silver > cst.s * 2 + reserve && (st.res.doska || 0) >= cst.b &&
       (!cst.p || st.prods[k].n >= cst.p)) act(st, 'upgrade', {house:k});
  });
  const dosk = C.RES.find(r => r.id === 'doska');
  if(st.silver > dosk.s * 40 + reserve && (st.res.doska || 0) < 40) act(st, 'buy', {kind:'res', id:'doska', qty:10});
}

const st = fresh();
const marks = {};
const STEP = 5000;                      // шаг симуляции — 5 секунд
const LIMIT = 1000 * 60 * 60 * 40;      // 40 часов игрового марафона
let last = st.lvl;
for(let el = 0; el <= LIMIT; el += STEP){
  T += STEP;
  play(st);
  while(last < st.lvl){ last++; marks[last] = el / 60000; }
  if(process.env.TRACE && el % (1000 * 60 * 5) === 0){
    console.log('  ' + (el / 60000).toFixed(0) + ' мин: ур.' + st.lvl + ' xp ' + st.xp +
      ' серебро ' + Math.round(st.silver) + ' корм ' + (st.feed.low || 0) +
      ' занято ' + C.HKEYS.map(k => st.houses[k].slots.length).join('/') + ' энергия ' + st.energy);
  }
  if(st.lvl >= 16) break;
}
Date.now = realNow;

console.log('уровень | время с начала | сколько ждать с прошлого');
let prev = 0;
for(let l = 2; l <= 16; l++){
  if(marks[l] == null){ console.log(String(l).padStart(7), '| не достигнут'); break; }
  const m = marks[l];
  console.log(String(l).padStart(7) + ' | ' + fmt(m).padStart(14) + ' | ' + fmt(m - prev));
  prev = m;
}
console.log('\nподъёмные выдавались раз: ' + (st.c.bailout || 0) +
            ', госзаказов сдано: ' + (st.c.contract || 0));
console.log('\nитог: уровень ' + st.lvl + ', серебра ' + Math.round(st.silver) +
            ', кристаллов ' + st.gems + ', порог уровня ' + R.maxXp(st.lvl));

function fmt(min){
  if(min < 60) return min.toFixed(1) + ' мин';
  const h = Math.floor(min / 60);
  return h + ' ч ' + Math.round(min - h * 60) + ' мин';
}
