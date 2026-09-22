"use strict";
/* ===================== связь с сервером =====================
   Состояние приходит с сервера и только с сервера: цены, сроки и урожай считает он.
   Клиент рисует и отправляет намерения. */
var S = null;              // состояние хозяйства (снимок с сервера)
var ME = null;             // текущий пользователь
var SKEW = 0;              // поправка на расхождение часов клиента и сервера
var live = [];             // окна, которые перерисовываются каждую секунду (таймеры)
var panels = [];           // окна, которые перерисовываются после действия

function nowMs(){ return Date.now() + SKEW; }

async function api(url, body, method){
  /* В сборке без сервера запросы обслуживает offline.js по тем же правилам. */
  if(window.LOCAL_API) return window.LOCAL_API(url, body, method);
  var res = await fetch(url, {
    method: method || (body ? "POST" : "GET"),
    headers: body ? {"Content-Type":"application/json"} : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin"
  });
  var data = null;
  try{ data = await res.json(); }catch(e){ data = {}; }
  if(!res.ok){
    var err = new Error(data.error || ("Ошибка " + res.status));
    err.code = data.code;
    err.status = res.status;
    throw err;
  }
  return data;
}
function applyResult(r){
  S = r.state;
  SKEW = (r.state.serverTime || Date.now()) - Date.now();
  if(r.msg) toast(r.msg);
  (r.quests || []).forEach(function(q){ showQuestDone(q); });
  after();
}
/** Единственный путь что-то изменить: сервер проверяет и возвращает новое состояние. */
function act(name, params){
  return api("/api/game/" + name, params || {})
    .then(applyResult)
    .catch(function(e){
      if(e.code === "no_session" || e.code === "email_unverified"){ boot(); return; }
      toast(e.message, true);
    });
}
function sync(){
  return api("/api/game").then(applyResult).catch(function(e){
    if(e.code === "no_session" || e.code === "email_unverified") boot();
  });
}

/* ===================== утилиты ===================== */
function $(id){ return document.getElementById(id); }
function el(tag, cls, html){
  var e = document.createElement(tag);
  if(cls) e.className = cls;
  if(html != null) e.innerHTML = html;
  return e;
}
function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[c]; }); }
function fmt(n){ return Math.floor(n).toLocaleString("ru-RU"); }
function fmtC(n){ return (Math.round(n * 100) / 100).toFixed(2); }
function priceC(n){ return (Math.round(n * 10) / 10).toFixed(1); }
function breed(id){ for(var i = 0; i < BREEDS.length; i++) if(BREEDS[i].id === id) return BREEDS[i]; return null; }
function feedById(id){ for(var i = 0; i < FEEDS.length; i++) if(FEEDS[i].id === id) return FEEDS[i]; return null; }
function maxXp(l){ return Math.round(XP_BASE * Math.pow(l, XP_POW)); }
/** Самый дешёвый корм, которым вообще можно кормить: по нему считаем прибыль. */
function cheapestFeed(){
  var best = null;
  FEEDS.forEach(function(f){
    if(f.pet || f.inst || f.gives || !f.s) return;
    if(!best || f.s < best.s) best = f;
  });
  return best || FEEDS[0];
}
function maxEn(){ return 100; }
function gtime(min){
  min = Math.max(0, Math.round(min));
  if(min >= 1440){ var d = Math.floor(min / 1440), h = Math.round((min - d * 1440) / 60); return d + " д. " + h + " ч."; }
  if(min >= 60){ var hh = Math.floor(min / 60), mm = min - hh * 60; return hh + " ч. " + (mm < 10 ? "0" + mm : mm) + " мин."; }
  return min + " мин.";
}
function msLeft(a){ return Math.max(0, a.ready - nowMs()); }
function gminLeft(a){ return msLeft(a) / 1000 * GM_PER_SEC; }
function toast(msg, bad){
  var t = el("div", "toast" + (bad ? " bad" : ""), esc(msg));
  $("toasts").appendChild(t);
  setTimeout(function(){ t.remove(); }, 2600);
}
function yieldPct(){ return S && S.yieldPct != null ? S.yieldPct : 100; }
function cap(k){ return CAP[S.houses[k].lvl - 1]; }
function free(k){ return cap(k) - S.houses[k].slots.length; }
function stateOf(a){ return !a.fed ? "hungry" : (nowMs() >= a.ready ? "ready" : "growing"); }
function counts(k){
  var r = 0, h = 0;
  S.houses[k].slots.forEach(function(a){ var st = stateOf(a); if(st === "ready") r++; if(st === "hungry") h++; });
  return {ready:r, hungry:h};
}
function qprog(q){ return q.k === "lvl" ? S.lvl : (S.c[q.k] || 0); }
function todayKey(){ var d = new Date(); return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); }
var qview = 0;

/* ---------- спрайты ----------
   Графика: наборы Kenney Tiny Farm / Tiny Town / Pixel Platformer Farm Expansion, CC0.
   Часть живности перекрашена из тех же тайлов, постройки склеены из стен и крыш. */
var SPRITES = {
  breed: {grusha:1, holmgus:1, holmkor:1, kartoha:1, krupbel:1, kuchin:1, kukuruza:1, landras:1, leggorn:1, mirgorod:1, ogurcy:1, podsol:1, rusbel:1, simment:1, trufel:1, tula:1, vietnam:1, vladimir:1, yablon:1},
  house: {gusi:1, koni:1, korovy:1, kury:1, ogorod:1, sad:1, svini:1, teplica:1},
  prop: {barrel:1, crate:1, egg:1, fence:1, hay:1, milk:1, sign:1, stone:1, tree:1, vily:1, well:1}
};

var ISO = {
  /* Растения — из набора ODDBLOT, живность нарисована tools/make-animals.py:
     в наборе животных нет, а пиксельные спрайты Kenney давали четырёх
     одинаковых кур и гуся, неотличимого от курицы. */
  breed: {"baklazh":1, "brokkoli":1, "chili":1, "grusha":1, "kapusta":1, "kartoha":1, "kukuruza":1, "luk":1, "morkov":1, "oblepiha":1, "ogurcy":1, "perec":1, "podsol":1, "pomidor":1, "redis":1, "salat":1, "selderey":1, "shpinat":1, "sliva":1, "trufel":1, "vishnya":1, "yablon":1,
          "rusbel":1, "leggorn":1, "kuchin":1, "moskchern":1, "orlov":1, "pavlov":1,
          "tula":1, "holmgus":1, "kitay":1, "kuban":1, "tuluz":1, "ital":1, "vietnam":1, "mirgorod":1, "landras":1, "krupbel":1, "holmkor":1, "simment":1, "vladimir":1},
  feed: {"bone":1, "elite":1, "fish":1, "high":1, "instant":1, "krapiva":1, "low":1, "lowset":1, "mid":1, "navoz":1, "otrubi":1, "torf":1, "univer":1, "vitamin":1, "zhmyh":1},
  house: {"gusi":1, "koni":1, "korovy":1, "kury":1, "ogorod":1, "sad":1, "svini":1, "teplica":1},
  prop: {"bush":1, "doska":1, "fence":1, "fluger":1, "grass":1, "hay":1, "klumba":1, "kolodec":1, "path":1, "pleten":1, "scare":1, "skirda":1, "table":1, "telega":1, "traktor":1, "tree":1},
  /* Ресурсы держим отдельной группой: «доска» в декоре — это доска почёта,
     а в ресурсах — стопка досок. Одинаковые id, разные картинки. */
  res: {"doska":1, "gvozdi":1, "soloma":1}
};

var UI = {"barn":1, "bonus":1, "butterfly":1, "fertilizer":1, "friends":1, "gusi":1, "koni":1, "korovy":1, "kury":1, "ogorod":1, "pets":1, "piggy":1, "quests":1, "sad":1, "shop":1, "silver":1, "store":1, "svini":1, "teplica":1, "top":1, "wheat":1};

/** Иконка раздела (game-icons.net). Нет такой — вернём null, вызывающий подставит своё. */
function uiIc(key, cls){
  return UI[key] ? "<img class='ui-ic " + (cls || "") + "' src='" + url("img/ui/" + key + ".svg") + "' alt=''>" : null;
}

/** Рисованный спрайт из набора ODDBLOT, если он есть для этой сущности. */
function isoSrc(kind, id){
  return ISO[kind] && ISO[kind][id] ? "img/iso/" + kind + "-" + id + ".png" : null;
}
/** В офлайн-сборке картинки зашиты в страницу, поэтому путь идёт через таблицу. */
function url(p){ return (window.IMG && window.IMG[p]) || p; }
function spr(kind, id, cls){
  var iso = isoSrc(kind, id);
  if(iso) return "<img class='sp iso " + (cls || "") + "' src='" + url(iso) + "' alt='' draggable='false'>";
  return SPRITES[kind] && SPRITES[kind][id]
    ? "<img class='sp " + (cls || "") + "' src='" + url("img/" + kind + "-" + id + ".png") + "' alt='' draggable='false'>"
    : null;
}
/** Спрайт, если он есть; иначе эмодзи — чтобы ничего не пропадало. */
function ic(kind, id, em, cls){
  return spr(kind, id, cls) || "<i class='em " + (cls || "") + "'>" + em + "</i>";
}

/* ===================== окна ===================== */
var live = [];
function makeWin(title, cls){
  var scrim = el("div", "scrim");
  var win = el("div", "win" + (cls ? " " + cls : ""));
  var hd = el("div", "win-hd");
  hd.appendChild(el("h2", null, esc(title)));
  var x = el("button", "x", "Закрыть");
  hd.appendChild(x);
  var bd = el("div", "win-bd");
  win.appendChild(hd); win.appendChild(bd); scrim.appendChild(win);
  var w = {scrim:scrim, win:win, body:bd, refresh:null};
  x.title = "Обновить";
  x.onclick = function(){ if(w.refresh) w.refresh(); else closeWin(scrim); };
  scrim.addEventListener("click", function(e){ if(e.target === scrim) closeWin(scrim); });
  $("modals").appendChild(scrim);
  return w;
}
/** Подвал с «Закрыть» — в оригинале окна закрываются снизу, а не крестиком. */
function closeBar(w){
  if(!w.win.querySelector(".win-ft")) footer(w, [{label:"Закрыть", on:function(){ closeWin(w.scrim); }}]);
  return w;
}
function closeWin(scrim){
  scrim.remove();
  live = live.filter(function(l){ return document.body.contains(l.scrim); });
  panels = panels.filter(function(l){ return document.body.contains(l.scrim); });
}
function closeAll(){ $("modals").innerHTML = ""; live = []; panels = []; }
function footer(win, buttons){
  var ft = el("div", "win-ft");
  buttons.forEach(function(b){
    var btn = el("button", "btn" + (b.cls ? " " + b.cls : ""), esc(b.label));
    btn.onclick = b.on;
    if(b.dis) btn.disabled = true;
    ft.appendChild(btn);
  });
  win.win.appendChild(ft);
  return ft;
}

/** Иконка награды: рисованный спрайт, если он для неё есть, иначе эмодзи.
 *  Серебро, опыт и кристаллы спрайтов не имеют — они не предметы. */
function rewardIcon(rw){
  var kind = rw.t === "feed" ? "feed" : rw.t === "res" ? "res" : null;
  return kind ? ic(kind, rw.id, rw.em) : "<i class='em'>" + rw.em + "</i>";
}

/* ---------- модалка «Задание выполнено» ---------- */
function showQuestDone(q){
  var w = makeWin("Задания", "sm");
  var box = el("div", "reward-box");
  box.appendChild(el("div", null, "Задание «" + esc(q.t) + "» выполнено. Ваша награда"));
  var tile = el("div", "im");
  tile.innerHTML = rewardIcon(q.rw);
  box.appendChild(tile);
  /* Количество отдельной строкой под плиткой — как в оригинале игры.
     В названии его больше не повторяем, иначе одно и то же дважды. */
  if(q.rw.n) box.appendChild(el("div", "qty", fmt(q.rw.n)));
  box.appendChild(el("b", null, esc(q.rw.nm)));
  w.body.appendChild(box);
  footer(w, [{label:"Закрыть", on:function(){ closeWin(w.scrim); }}]);
}

/* ---------- интерьер постройки ---------- */
function openHouse(k){
  var H = HOUSES[k];
  var w = makeWin(H.n + " — " + HOUSE_TITLES[S.houses[k].lvl - 1]);
  var body = w.body;
  function draw(){
    body.innerHTML = "";
    var h = S.houses[k], c = counts(k);
    var hd = el("div", "house-hd");
    hd.appendChild(el("div", null,
      "<b>Мест:</b> <span class='num'>" + h.slots.length + " / " + cap(k) + "</span> &nbsp; " +
      "<b>На складе:</b> <span class='num'>" + fmt(S.prods[k].n) + "</span> " + H.prod.em +
      " на " + fmt(S.prods[k].val) + " 🪙" +
      (S.prods[k].n ? " <small>(по " + (S.prods[k].val / S.prods[k].n).toFixed(1) + " за штуку)</small>" : "")));
    var acts = el("div", "slot-acts");
    acts.style.display = "flex"; acts.style.gap = "5px"; acts.style.flexWrap = "wrap";
    var bFeed = el("button", "mini", H.kind === "plant" ? "Полить всё" : "Покормить всех");
    bFeed.onclick = function(){ act("feedAll", {house:k}); };
    var bHarv = el("button", "mini go", "Собрать всё" + (c.ready ? " (" + c.ready + ")" : ""));
    bHarv.onclick = function(){ act("harvestAll", {house:k}); };
    var bSell = el("button", "mini", "Сдать продукцию");
    bSell.onclick = function(){ act("sell", {house:k}); };
    var bShop = el("button", "mini", "🛒 В магазин");
    bShop.onclick = function(){ openShop(H.kind === "plant" ? "plants" : "animals"); };
    acts.appendChild(bFeed); acts.appendChild(bHarv); acts.appendChild(bSell); acts.appendChild(bShop);
    hd.appendChild(acts);
    body.appendChild(hd);

    var inside = el("div", "inside");
    h.slots.forEach(function(a){
      var b = breed(a.breed), st = stateOf(a);
      var row = el("div", "slot");
      row.appendChild(el("div", "big", ic("breed", b.id, b.em)));
      var who = el("div", "who");
      who.innerHTML = "<b>" + esc(b.n) + " <span class='seasons'>🏅 осталось " + a.se + "</span></b>" +
        "<span class='st'>" + (st === "hungry" ? (H.kind === "plant" ? "Нужен полив" : "Нужен корм")
          : st === "growing" ? "Созревание: " + gtime(gminLeft(a))
          : "Готово к сбору · примерно " + Math.round(b.y * (feedById(a.feedId) || FEEDS[0]).ym * yieldPct() / 100) + " " + H.prod.em) + "</span>";
      row.appendChild(who);
      var ac = el("div", "acts");
      if(st === "hungry"){
        FEEDS.filter(function(f){ return (f.for === "Для животных" || f.for === "Универсальный") && !f.gives; }).forEach(function(f){
          if(!S.feed[f.id]) return;
          var btn = el("button", "mini", ic("feed", f.id, f.em, "tiny") + " " + S.feed[f.id]);
          btn.title = f.n;
          btn.onclick = function(){ act("feed", {house:k, slot:a.id, feed:f.id}); };
          ac.appendChild(btn);
        });
        if(!ac.children.length){
          var go = el("button", "mini", H.kind === "plant" ? "Купить полив" : "Купить корм");
          go.onclick = function(){ openShop("feed"); };
          ac.appendChild(go);
        }
      } else if(st === "ready"){
        var hb = el("button", "mini go", "Собрать");
        hb.onclick = function(){ act("harvest", {house:k, slot:a.id}); };
        ac.appendChild(hb);
      } else {
        var sp = el("span", "st num", gtime(gminLeft(a)));
        ac.appendChild(sp);
      }
      row.appendChild(ac);
      inside.appendChild(row);
    });
    for(var i = h.slots.length; i < cap(k); i++){
      var fr = el("div", "slot free", (H.free || "Свободное место") + " — посади кого-нибудь");
      fr.onclick = function(){ openShop(H.kind === "plant" ? "plants" : "animals"); };
      inside.appendChild(fr);
    }
    body.appendChild(inside);

    var up = el("div", "row");
    up.style.marginTop = "8px";
    if(h.lvl < 4){
      var cst = UPG_COST[k][h.lvl];
      var needProd = cst.p
        ? " · " + H.prod.n.toLowerCase() + " ×" + cst.p + " (есть " + fmt(S.prods[k].n) + ")"
        : "";
      up.innerHTML = "<span class='ic'>🔨</span><span class='grow'><b>" + HOUSE_TITLES[h.lvl] + "</b>" +
        "<small>мест станет " + CAP[h.lvl] + " · " + fmt(cst.s) + " 🪙 или " + priceC(cst.c) + " 💎 · доски ×" + cst.b +
        " (есть " + S.res.doska + ")" + needProd + "</small></span>";
      var ub = el("button", "mini", "Улучшить");
      ub.onclick = function(){ act("upgrade", {house:k}); };
      up.appendChild(ub);
    } else {
      up.innerHTML = "<span class='ic'>🏆</span><span class='grow'><b>Элитная ферма</b><small>улучшать больше некуда</small></span>";
    }
    body.appendChild(up);
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  live.push({scrim:w.scrim, fn:draw});
  panels.push({scrim:w.scrim, fn:draw});
}

/* ---------- магазин ---------- */
var shop = {cat:"new", sub:null, page:0, byPrice:false, byLvl:false};
var SHOP_NAV = [
  {id:"new", n:"Новинки"},
  {id:"animals", n:"Животные"},
  {id:"plants", n:"Растения"},
  {id:"feed", n:"Корма", subs:["Для животных","Для собаки","Для кота","Универсальный"]},
  {id:"decor", n:"Декор"},
  {id:"gifts", n:"Подарки", subs:["В здания","Флаги, ленты","Другое"]},
  {id:"upg", n:"Улучшения"},
  {id:"helpers", n:"Помощники"},
  {id:"boosts", n:"Бонусы"},
  {id:"res", n:"Ресурсы"}
];
function shopGoods(){
  var g = [];
  if(shop.cat === "new"){
    g = BREEDS.filter(function(b){ return b.lvl <= S.lvl + 2; }).sort(function(a, b){ return b.lvl - a.lvl; }).slice(0, 6)
      .map(function(b){ return {kind:"breed", it:b}; });
  } else if(shop.cat === "animals"){
    g = BREEDS.filter(function(b){ return HOUSES[b.h].kind === "animal"; }).map(function(b){ return {kind:"breed", it:b}; });
  } else if(shop.cat === "plants"){
    g = BREEDS.filter(function(b){ return HOUSES[b.h].kind === "plant"; }).map(function(b){ return {kind:"breed", it:b}; });
  } else if(shop.cat === "feed"){
    g = FEEDS.filter(function(f){ return !shop.sub || f.for === shop.sub; }).map(function(f){ return {kind:"feed", it:f}; });
  } else if(shop.cat === "decor"){
    g = DECOR.map(function(d){ return {kind:"decor", it:d}; });
  } else if(shop.cat === "gifts"){
    g = GIFTS.filter(function(x){ return !shop.sub || x.sub === shop.sub; }).map(function(x){ return {kind:"gift", it:x}; });
  } else if(shop.cat === "upg"){
    g = HKEYS.map(function(k){ return {kind:"upg", it:{id:k}}; });
  } else if(shop.cat === "helpers"){
    g = HELPERS.map(function(x){ return {kind:"helper", it:x}; });
  } else if(shop.cat === "boosts"){
    g = BOOSTS.map(function(x){ return {kind:"boost", it:x}; });
  } else if(shop.cat === "res"){
    g = RES.map(function(x){ return {kind:"res", it:x}; });
  }
  if(shop.byLvl) g = g.filter(function(x){ return !x.it.lvl || x.it.lvl <= S.lvl; });
  if(shop.byPrice) g = g.filter(function(x){
    if(x.kind === "upg"){ var c = UPG_COST[x.it.id][S.houses[x.it.id].lvl]; return c && (S.silver >= c.s || S.gems >= c.c); }
    return S.silver >= (x.it.s || 0) && S.gems >= (x.it.c || 0);
  });
  return g;
}
function openShop(cat, sub){
  if(cat){ shop.cat = cat; shop.sub = sub || null; shop.page = 0; }
  var w = makeWin("Магазин");
  var wrap = el("div", "shop");
  var nav = el("div", "shop-nav"), main = el("div", "shop-main");
  wrap.appendChild(nav); wrap.appendChild(main);
  w.body.appendChild(wrap);
  footer(w, [
    {label:"Пополнить счет", cls:"flat", on:openExchange},
    {label:"Закрыть", on:function(){ closeWin(w.scrim); }}
  ]);
  function draw(){
    nav.innerHTML = "";
    SHOP_NAV.forEach(function(c){
      var b = el("button", null, esc(c.n));
      b.setAttribute("aria-pressed", shop.cat === c.id && !shop.sub ? "true" : "false");
      b.onclick = function(){ shop.cat = c.id; shop.sub = null; shop.page = 0; draw(); };
      nav.appendChild(b);
      if(c.subs && shop.cat === c.id){
        c.subs.forEach(function(s){
          var sb = el("button", "sub", esc(s));
          sb.setAttribute("aria-pressed", shop.sub === s ? "true" : "false");
          sb.onclick = function(){ shop.sub = shop.sub === s ? null : s; shop.page = 0; draw(); };
          nav.appendChild(sb);
        });
      }
    });
    main.innerHTML = "";
    var f = el("div", "filters");
    var l1 = el("label", null, "<input type='checkbox' id='fPrice'" + (shop.byPrice ? " checked" : "") + "> Подходящие по цене");
    var l2 = el("label", null, "<input type='checkbox' id='fLvl'" + (shop.byLvl ? " checked" : "") + "> Доступные по уровню");
    f.appendChild(l1); f.appendChild(l2);
    main.appendChild(f);
    l1.querySelector("input").onchange = function(e){ shop.byPrice = e.target.checked; shop.page = 0; draw(); };
    l2.querySelector("input").onchange = function(e){ shop.byLvl = e.target.checked; shop.page = 0; draw(); };

    var goods = shopGoods(), per = 6, pages = Math.max(1, Math.ceil(goods.length / per));
    if(shop.page >= pages) shop.page = pages - 1;
    var pg = el("div", "pager");
    var prev = el("button", null, "◀"), next = el("button", null, "▶");
    prev.onclick = function(){ if(shop.page > 0){ shop.page--; draw(); } };
    next.onclick = function(){ if(shop.page < pages - 1){ shop.page++; draw(); } };
    pg.appendChild(prev);
    pg.appendChild(el("span", null, "Страница " + (shop.page + 1) + " из " + pages));
    pg.appendChild(next);
    main.appendChild(pg);

    var grid = el("div", "goods");
    goods.slice(shop.page * per, shop.page * per + per).forEach(function(g){
      grid.appendChild(goodCard(g, draw));
    });
    if(!goods.length) grid.appendChild(el("div", null, "<i>Ничего не подходит под фильтры.</i>"));
    main.appendChild(grid);
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  panels.push({scrim:w.scrim, fn:draw});
}
function goodCard(g, redraw){
  var it = g.it, card = el("div", "good");
  var name = it.n, em = it.em, s = it.s || 0, c = it.c || 0, lvlReq = it.lvl || 0;
  if(g.kind === "upg"){
    var k = it.id, h = S.houses[k];
    var cst = UPG_COST[k][h.lvl];
    name = HOUSES[k].n + ": " + (h.lvl < 4 ? HOUSE_TITLES[h.lvl] : "максимум");
    em = HOUSES[k].em;
    s = cst ? cst.s : 0; c = cst ? cst.c : 0;
  }
  card.appendChild(el("div", "nm", esc(name)));
  card.appendChild(el("div", "im",
    g.kind === "breed" ? ic("breed", it.id, em) :
    g.kind === "upg"   ? ic("house", it.id, em) :
    g.kind === "feed"  ? ic("feed", it.id, em) :
    g.kind === "decor" ? ic("prop", it.id, em) :
    g.kind === "res"   ? ic("res", it.id, em) : em));
  var pr = el("div", "prices");
  pr.appendChild(el("div", "pr" + (s ? "" : " zero"), "<i class='dot s'></i><span class='num'>" + fmt(s) + "</span>"));
  pr.appendChild(el("div", "pr" + (c ? "" : " zero"), "<i class='dot c'></i><span class='num'>" + priceC(c) + "</span>"));
  card.appendChild(pr);
  if(g.kind === "upg" && cst){
    var needs = "доски ×" + cst.b + (cst.p ? ", " + HOUSES[it.id].prod.n.toLowerCase() + " ×" + cst.p : "");
    var enough = (S.res.doska || 0) >= cst.b && (!cst.p || S.prods[it.id].n >= cst.p);
    card.appendChild(el("div", "need" + (enough ? " ok" : ""), esc(needs)));
  }
  if(lvlReq > S.lvl) card.appendChild(el("div", "lvl", lvlReq + " ур."));
  var b = el("button", "pick", g.kind === "upg" ? "Улучшить" : "Подробнее");
  if(lvlReq > S.lvl) b.disabled = true;
  b.onclick = function(){
    if(g.kind === "upg"){ act("upgrade", {house:it.id}); }
    else openDetail(g, redraw);
  };
  card.appendChild(b);
  return card;
}
function openDetail(g, redraw){
  var it = g.it;
  var w = makeWin(it.n, "sm");
  var qty = 1;
  var d = el("div", "detail");
  var left = el("div", "left");
  left.appendChild(el("div", "im",
    g.kind === "breed" ? ic("breed", it.id, it.em) :
    g.kind === "feed"  ? ic("feed", it.id, it.em) :
    g.kind === "decor" ? ic("prop", it.id, it.em) :
    g.kind === "res"   ? ic("res", it.id, it.em) : it.em));
  var spin = el("div", "spin");
  var minus = el("button", null, "−"), plus = el("button", null, "+");
  var inp = document.createElement("input");
  inp.type = "text"; inp.id = "qty-" + it.id; inp.value = "1"; inp.inputMode = "numeric";
  spin.appendChild(minus); spin.appendChild(inp); spin.appendChild(plus);
  var single = (g.kind === "decor" || g.kind === "helper");
  if(!single) left.appendChild(spin);
  d.appendChild(left);

  var dl = el("dl", "specs");
  function line(k, v, cls){
    dl.appendChild(el("dt", null, esc(k) + ":"));
    dl.appendChild(el("dd", cls || null, v));
  }
  line("Цена", "<i class='dot " + (it.c ? "c" : "s") + "'></i> " + (it.c ? priceC(it.c) : fmt(it.s || 0)));
  line("Название", esc(it.n));
  if(g.kind === "breed"){
    line("Созревание", gtime(it.mat));
    line("Урожайность", it.y);
    line("Цена единицы", "<i class='dot s'></i> " + it.u);
    line("Чистая прибыль", "<i class='dot s'></i> " + fmt(it.y * it.u * it.se - it.s));
    line("Кол-во опыта", it.xp);
    line("Сезон", it.se);
    /* Кормить надо каждый цикл, поэтому прибыль считаем за вычетом корма —
       по самому дешёвому, иначе дешёвые культуры выглядят убыточными. */
    var feed = cheapestFeed();
    var perCycle = Math.round(it.y * (feed.ym || 1)) * it.u - feed.s;
    line("Прибыль за цикл", "<i class='dot s'></i> " + fmt(perCycle) +
         " <small>минус " + esc(feed.n.toLowerCase()) + "</small>");
    line("Окупится за", Math.max(1, Math.ceil(it.s / Math.max(1, perCycle))) + " " +
         (Math.ceil(it.s / Math.max(1, perCycle)) === 1 ? "цикл" : "цикла"));
    line("Постройка", HOUSES[it.h].n + " (свободно " + free(it.h) + ")");
  }
  if(g.kind === "feed" && it.sp) line("Созревание", Math.round(it.sp * 100) + "% от срока");
  if(g.kind === "feed" && it.ym) line("Урожайность", "+" + Math.round((it.ym - 1) * 100) + "%");
  if(g.kind === "decor") line("Урожайность", "+" + it.bonus + "%");
  if(it.lvl) line("Уровень", it.lvl + " ур.");
  line("Описание", esc(it.d || ""), "desc");
  d.appendChild(dl);
  w.body.appendChild(d);

  function setQty(n){
    qty = Math.max(1, Math.min(99, n || 1));
    inp.value = String(qty);
  }
  minus.onclick = function(){ setQty(qty - 1); };
  plus.onclick = function(){ setQty(qty + 1); };
  inp.onchange = function(){ setQty(parseInt(inp.value, 10)); };

  footer(w, [
    {label:"Купить", cls:"go", on:function(){
      if(g.kind === "breed") act("plant", {breed:it.id, qty:qty});
      else act("buy", {kind:g.kind, id:it.id, qty:single ? 1 : qty});
      closeWin(w.scrim);
    }},
    {label:"Закрыть", on:function(){ closeWin(w.scrim); }}
  ]);
}

/* ---------- вкладки нижней панели ---------- */
function openTop(){
  var w = makeWin("TOP 100 колхозов");
  var rows = el("div", "rows");
  rows.appendChild(el("div", "row", "<span class='grow'><small>Загружаем таблицу…</small></span>"));
  w.body.appendChild(rows);
  closeBar(w);
  w.refresh = function(){ closeWin(w.scrim); openTop(); };
  api("/api/top").then(function(r){
    rows.innerHTML = "";
    var list = r.top || [];
    if(!list.length) rows.appendChild(el("div", "row", "<span class='grow'><small>Пока пусто.</small></span>"));
    list.forEach(function(x, i){
      var mine = S && x.nick === S.nick && x.farm === S.farm;
      var row = el("div", "row" + (mine ? " me" : ""));
      row.innerHTML = "<span class='rank num'>" + (i + 1) + ".</span><span class='ic'>" +
        (i < 3 ? ["🥇","🥈","🥉"][i] : "🌾") + "</span>" +
        "<span class='grow'><b>" + esc(x.nick) + "</b><small>колхоз «" + esc(x.farm) + "» · ур. " + x.level + "</small></span>" +
        "<span class='num'><b>" + fmt(x.score) + "</b></span>";
      rows.appendChild(row);
    });
  }).catch(function(e){
    rows.innerHTML = "";
    rows.appendChild(el("div", "row", "<span class='grow'><small>" + esc(e.message) + "</small></span>"));
  });
}

function openFriends(){
  var w = makeWin("Друзья");
  var body = w.body;
  function draw(){
    body.innerHTML = "";
    var rows = el("div", "rows");
    FRIENDS.forEach(function(fr, i){
      var key = todayKey() + ":" + i;
      var row = el("div", "row");
      row.innerHTML = "<span class='ic'>🧑‍🌾</span><span class='grow'><b>" + esc(fr.n) + "</b><small>колхоз " + esc(fr.f) + "</small></span>";
      var help = el("button", "mini go", S.helped[key] ? "Сегодня помог" : "Помочь (2⚡)");
      if(S.helped[key]) help.disabled = true;
      help.onclick = function(){
        act("helpFriend", {friend:i});
      };
      row.appendChild(help);
      var giftIds = Object.keys(S.gifts).filter(function(g){ return S.gifts[g] > 0; });
      var gb = el("button", "mini", giftIds.length ? "Подарить" : "Нет подарков");
      gb.disabled = !giftIds.length;
      gb.onclick = function(){
        act("gift", {friend:i, id:giftIds[0]});
      };
      row.appendChild(gb);
      rows.appendChild(row);
    });
    body.appendChild(rows);
    body.appendChild(el("p", null, "<small>Подарки покупаются в магазине, раздел «Подарки».</small>"));
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  panels.push({scrim:w.scrim, fn:draw});
}
function openQuests(){
  var w = makeWin("Задания");
  var rows = el("div", "rows");
  w.refresh = null;
  QUESTS.forEach(function(q, i){
    var done = i < S.quest;
    var row = el("div", "row");
    var p = Math.min(qprog(q), q.n);
    row.innerHTML = "<span class='ic'>" + (done ? "✅" : q.rw.em) + "</span>" +
      "<span class='grow'><b>" + esc(q.t) + "</b><small>" + esc(q.d) + "</small>" +
      "<small>Награда: " + esc(q.rw.nm) + (q.rw.n ? ". Количество: " + q.rw.n : "") + "</small></span>" +
      (done ? "<span class='done'>Сдано</span>" : "<span class='num'>" + fmt(p) + " / " + fmt(q.n) + "</span>");
    rows.appendChild(row);
  });
  w.body.appendChild(rows);
  closeBar(w);
}
function openBonus(){
  var w = makeWin("Бонусы");
  var body = w.body;
  function draw(){
    body.innerHTML = "";

    var head = el("div", "ribbon-wrap");
    head.innerHTML = ic("breed", "podsol", "🌾", "wheat left") +
      "<div class='ribbon'><span>Ежедневный подарок!</span></div>" +
      ic("breed", "podsol", "🌾", "wheat right");
    body.appendChild(head);
    body.appendChild(el("div", "daily-note", "Подарков доступно сегодня: " + (S.daily.opened ? 0 : 1) + "."));

    var days = el("div", "days");
    for(var i = 1; i <= 5; i++){
      if(i > 1) days.appendChild(el("div", "day-arrow", "➜"));
      var on = i <= S.daily.streak;
      days.appendChild(el("div", "day" + (on ? " on" : ""), "<b>" + i + "</b><span>День</span>"));
    }
    body.appendChild(days);

    var row = el("div", "daily-row");
    var scroll = el("div", "scroll",
      "<b>НАГРАДА</b><p>Открывай корзинки и получай призы! Заходи каждый день и испытай удачу — " +
      "можешь найти корма, полезных животных, серебро и опыт. Чем чаще заходишь, тем больше призов.</p>");
    row.appendChild(scroll);

    var board = el("div", "board");
    var bs = el("div", "baskets");
    for(var j = 0; j < 16; j++){
      (function(j){
        var opened = S.daily.opened && S.daily.picked === j;
        var b = el("button", "bsk" + (opened ? " open" : ""),
                   opened ? "<span class='pick'>🎉</span>" : ic("prop", "telega", "🧺"));
        if(S.daily.opened) b.disabled = true;
        b.onclick = function(){ act("daily", {basket:j}); };
        bs.appendChild(b);
      })(j);
    }
    board.appendChild(bs);
    row.appendChild(board);
    body.appendChild(row);

    body.appendChild(el("h3", null, "Мои бонусы"));
    var rows = el("div", "rows"), any = false;
    BOOSTS.forEach(function(b){
      var n = S.items[b.id] || 0;
      if(!n) return;
      any = true;
      var r = el("div", "row");
      r.innerHTML = "<span class='ic'>" + b.em + "</span><span class='grow'><b>" + esc(b.n) + " ×" + n +
                    "</b><small>" + esc(b.d) + "</small></span>";
      var use = el("button", "mini go", "Применить");
      use.onclick = function(){ act("useItem", {id:b.id}); };
      r.appendChild(use);
      rows.appendChild(r);
    });
    if(!any) rows.appendChild(el("div", "row", "<span class='ic'>🤷</span><span class='grow'><small>Бонусов нет. Купи в магазине, раздел «Бонусы».</small></span>"));
    body.appendChild(rows);
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  live.push({scrim:w.scrim, fn:draw});
  panels.push({scrim:w.scrim, fn:draw});
}

/** План сдачи: три заказа, куда уходит продукция. Здесь же виден весь смысл
    цепочки «покормил — собрал — сдал»: за сдачу платят вдвое против рынка. */
function openContracts(){
  var w = makeWin("Госзаказ");
  var body = w.body;
  function draw(){
    body.innerHTML = "";
    body.appendChild(el("p", null,
      "<small>Заготконтора принимает продукцию заметно дороже рынка и даёт опыт. " +
      "Сдал заказ — на его место приходит новый.</small>"));
    var rows = el("div", "rows");
    (S.contracts || []).forEach(function(c, i){
      var H = HOUSES[c.house], have = S.prods[c.house].n, ready = have >= c.need;
      var row = el("div", "row");
      row.innerHTML =
        "<span class='ic'>" + ic("breed", firstBreedOf(c.house), H.prod.em) + "</span>" +
        "<span class='grow'><b>" + esc(H.prod.n) + " — " + fmt(c.need) + " ед.</b>" +
        "<small>на складе <span class='num'" + (ready ? " style='color:#25611a;font-weight:700'" : "") + ">" +
        fmt(have) + "</span> из " + fmt(c.need) + "</small>" +
        "<small class='rw'>Награда: " + fmt(c.silver) + " серебра, " + c.xp + " опыта" +
        (c.gems ? ", кристалл" : "") + "</small></span>";
      var b = el("button", "mini" + (ready ? " go" : ""), ready ? "Сдать" : "Мало");
      b.disabled = !ready;
      b.onclick = function(){ act("contract", {slot:i}); };
      row.appendChild(b);
      rows.appendChild(row);
    });
    if(!(S.contracts || []).length) rows.appendChild(el("div", "row", "<span class='grow'><small>Заказов пока нет.</small></span>"));
    body.appendChild(rows);
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  panels.push({scrim:w.scrim, fn:draw});
}
/** Касса: серебро в кристаллы по твёрдому курсу из справочника. */
function openExchange(){
  var w = makeWin("Касса", "sm");
  var qty = 1;
  function draw(){
    w.body.innerHTML = "";
    var can = Math.floor(S.silver / GEM_PRICE);
    qty = Math.max(1, Math.min(qty, Math.max(1, can)));
    w.body.appendChild(el("p", null,
      "<small>Колхоз меняет серебро на кристаллы: <b>" + fmt(GEM_PRICE) + "</b> серебра за один кристалл. " +
      "Обратно касса не принимает.</small>"));

    var row = el("div", "row");
    row.innerHTML = "<span class='ic'><i class='dot c'></i></span>" +
      "<span class='grow'><b>Кристаллы</b>" +
      "<small>в кассе есть на " + fmt(can) + " шт. (серебра " + fmt(S.silver) + ")</small></span>";
    var spin = el("div", "spin");
    var minus = el("button", null, "−"), plus = el("button", null, "+");
    var inp = el("input");
    inp.value = String(qty);
    inp.inputMode = "numeric";
    minus.onclick = function(){ qty = Math.max(1, qty - 1); draw(); };
    plus.onclick = function(){ qty = Math.min(99, qty + 1); draw(); };
    inp.onchange = function(){ qty = Math.max(1, Math.min(99, parseInt(inp.value, 10) || 1)); draw(); };
    spin.appendChild(minus); spin.appendChild(inp); spin.appendChild(plus);
    row.appendChild(spin);
    w.body.appendChild(row);

    var total = GEM_PRICE * qty;
    var sum = el("div", "row");
    sum.innerHTML = "<span class='grow'><b>К оплате</b><small>" +
      (S.silver >= total ? "хватает" : "не хватает " + fmt(total - S.silver) + " серебра") + "</small></span>" +
      "<span class='num' style='font-weight:700;white-space:nowrap'><i class='dot s'></i> " + fmt(total) + "</span>";
    w.body.appendChild(sum);
  }
  draw();
  footer(w, [
    {label:"Обменять", cls:"go", on:function(){
      act("exchange", {qty:qty}).then(function(){ if(document.body.contains(w.scrim)) draw(); });
    }},
    {label:"Закрыть", on:function(){ closeWin(w.scrim); }}
  ]);
  w.refresh = draw;
  panels.push({scrim:w.scrim, fn:draw});
}

/** Первая порода постройки — нужна только для картинки в списке заказов. */
function firstBreedOf(house){
  for(var i = 0; i < BREEDS.length; i++) if(BREEDS[i].h === house) return BREEDS[i].id;
  return "";
}

function openStore(){
  var w = makeWin("Склад");
  var body = w.body;
  function draw(){
    body.innerHTML = "";
    var rows = el("div", "rows"), total = 0;
    HKEYS.forEach(function(k){
      var p = S.prods[k];
      if(!p.n) return;
      total += p.val;
      var row = el("div", "row");
      row.innerHTML = "<span class='ic'>" + HOUSES[k].prod.em + "</span><span class='grow'><b>" + esc(HOUSES[k].prod.n) +
        " — " + fmt(p.n) + " ед.</b><small>из постройки «" + esc(HOUSES[k].n) + "»</small></span>" +
        "<span class='num'><b>" + fmt(p.val) + "</b> 🪙</span>";
      var b = el("button", "mini go", "Сдать");
      b.onclick = function(){ act("sell", {house:k}); };
      row.appendChild(b);
      rows.appendChild(row);
    });
    if(!total) rows.appendChild(el("div", "row", "<span class='ic'>📭</span><span class='grow'><small>Продукции нет. Собери урожай.</small></span>"));
    body.appendChild(rows);
    if(total){
      var all = el("button", "btn go", "Сдать всё — " + fmt(total) + " 🪙");
      all.style.marginTop = "8px";
      all.onclick = function(){ act("sellAll", {}); };
      body.appendChild(all);
    }
    body.appendChild(el("h3", null, "Запасы"));
    var inv = el("div", "rows");
    FEEDS.forEach(function(f){
      if(!S.feed[f.id]) return;
      inv.appendChild(el("div", "row", "<span class='ic'>" + f.em + "</span><span class='grow'><b>" + esc(f.n) + "</b><small>" + esc(f.for) + "</small></span><span class='num'><b>" + S.feed[f.id] + "</b></span>"));
    });
    RES.forEach(function(r){
      if(!S.res[r.id]) return;
      inv.appendChild(el("div", "row", "<span class='ic'>" + r.em + "</span><span class='grow'><b>" + esc(r.n) + "</b><small>" + esc(r.d) + "</small></span><span class='num'><b>" + S.res[r.id] + "</b></span>"));
    });
    Object.keys(S.gifts).forEach(function(gid){
      if(!S.gifts[gid]) return;
      GIFTS.forEach(function(g){
        if(g.id !== gid) return;
        inv.appendChild(el("div", "row", "<span class='ic'>" + g.em + "</span><span class='grow'><b>" + esc(g.n) + "</b><small>подарок соседям</small></span><span class='num'><b>" + S.gifts[gid] + "</b></span>"));
      });
    });
    if(!inv.children.length) inv.appendChild(el("div", "row", "<span class='ic'>🕸️</span><span class='grow'><small>Пусто. Даже корма нет.</small></span>"));
    body.appendChild(inv);
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  panels.push({scrim:w.scrim, fn:draw});
}
function openPets(){
  var w = makeWin("Пёс и кот", "sm");
  var body = w.body;
  function draw(){
    body.innerHTML = "";
    var rows = el("div", "rows");
    [["dog","🐕","Пёс","Косточка",120,"+3% к урожайности, пока сыт"],
     ["cat","🐈","Кот","Рыбка",140,"+5% к урожайности, пока сыт"]].forEach(function(p){
      var row = el("div", "row");
      row.innerHTML = "<span class='ic'>" + p[1] + "</span><span class='grow'><b>" + p[2] + " — сытость " + Math.round(S[p[0]]) + "%</b><small>" + p[5] + "</small></span>";
      var b = el("button", "mini go", p[3] + " · " + p[4] + " 🪙");
      b.onclick = function(){ act("feedPet", {pet:p[0]}); };
      row.appendChild(b);
      rows.appendChild(row);
    });
    body.appendChild(rows);
    body.appendChild(el("p", null, "<small>Общая урожайность двора сейчас: <b>" + yieldPct() + "%</b></small>"));
  }
  draw();
  w.refresh = draw;
  closeBar(w);
  live.push({scrim:w.scrim, fn:draw});
  panels.push({scrim:w.scrim, fn:draw});
}

/** Окно «Об игре»: лицензии требуют указания авторов, и это честное место для этого. */
function openAbout(){
  var w = makeWin("Об игре", "sm");
  w.body.innerHTML =
    "<p><b>Колхоз «Червонэ дышло»</b> — браузерная ферма по мотивам соцсетевых игр начала 2010-х. " +
    "Механика и устройство интерфейса собраны по скриншотам оригинала, код и графика свои.</p>" +
    "<h3>Графика</h3>" +
    "<p>Двор, постройки и культуры — набор <b>The Great Farm</b> студии <b>ODDBLOT</b>.<br>" +
    "Пиксельная живность и интерьеры — наборы <b>Kenney</b> (kenney.nl), CC0.<br>" +
    "Иконки разделов — <b>Delapouite</b>, <b>Lorc</b> и <b>Skoll</b> с сайта " +
    "<a href='https://game-icons.net' target='_blank' rel='noopener'>game-icons.net</a>, лицензия CC BY 3.0.</p>" +
    "<h3>Шрифты</h3><p>Russo One и PT Sans, Google Fonts.</p>";
  closeBar(w);
}

/* ===================== отрисовка ===================== */
function setBar(id, txtId, val, max, txt){
  var pct = Math.max(0, Math.min(100, val / max * 100));
  $(id).style.width = pct + "%";
  $(txtId).textContent = txt != null ? txt : (Math.floor(val) + "/" + max);
}
function renderHud(){
  $("nick").textContent = S.nick;
  $("lvl").textContent = S.lvl;
  setBar("xpbar", "xptxt", S.xp, maxXp(S.lvl), fmt(S.xp) + "/" + fmt(maxXp(S.lvl)));
  setBar("dogbar", "dogtxt", S.dog, 100, Math.round(S.dog) + "%");
  setBar("catbar", "cattxt", S.cat, 100, Math.round(S.cat) + "%");
  setBar("enbar", "entxt", S.energy, maxEn(), Math.floor(S.energy) + "/" + maxEn());
  $("silver").textContent = fmt(S.silver);
  $("gems").textContent = fmtC(S.gems);
  var q = $("quick");
  q.innerHTML = "";
  HKEYS.forEach(function(k){
    var c = counts(k);
    var b = el("button", null, uiIc(k) || ic("house", k, HOUSES[k].em, "mini-house"));
    b.title = HOUSES[k].n;
    if(c.ready) b.appendChild(el("span", "badge", String(c.ready)));
    b.onclick = function(){ openHouse(k); };
    q.appendChild(b);
  });
  var pets = el("button", null, uiIc("pets") || "🐕");
  pets.title = "Пёс и кот";
  pets.onclick = openPets;
  q.appendChild(pets);
}
/* Раскладка двора: доля ширины и высоты сцены до основания постройки,
   плюс ширина спрайта в долях ширины сцены. Глубина считается от y, поэтому
   дальние постройки не лезут поверх ближних. */
var YARD = {
  /* Чем дальше постройка, тем она мельче: раньше было наоборот и двор выглядел
     вывернутым наизнанку. Задний ряд — 17-20% ширины сцены, передний — до 30%. */
  koni:    {x:27, y:34, w:19},
  korovy:  {x:57, y:36, w:20},
  gusi:    {x:83, y:39, w:15},
  kury:    {x:14, y:61, w:19},
  svini:   {x:45, y:63, w:26},
  teplica: {x:84, y:64, w:21},
  ogorod:  {x:28, y:85, w:28},
  sad:     {x:70, y:86, w:23}
};
/* Выгул: живность стоит перед своей постройкой, поэтому смещения считаются
   от её ширины, а не в процентах сцены — постройки разного размера.
   У растений выгула нет. */
var WALK = {kury:1, gusi:1, svini:1, korovy:1, koni:1};
function walkSpot(pos, i){
  return {
    x: pos.x + pos.w * (i === 0 ? -0.46 : 0.40),
    y: pos.y + (i === 0 ? 3.5 : 6),
    w: Math.max(6, Math.min(10, pos.w * 0.42))
  };
}
var DECOR_SPOT = {
  pleten:  {x:9,  y:57, w:14},
  traktor: {x:6,  y:41, w:6},
  fluger:  {x:94, y:52, w:8},
  skirda:  {x:66, y:50, w:8},
  kolodec: {x:22, y:74, w:8},
  telega:  {x:55, y:79, w:10},
  klumba:  {x:8,  y:88, w:9},
  doska:   {x:95, y:82, w:12}
};
function renderYard(){
  var scene = $("barns");
  scene.innerHTML = "";
  var put = [];

  HKEYS.forEach(function(k){
    var H = HOUSES[k], h = S.houses[k], c = counts(k), pos = YARD[k];
    var b = el("button", "bld");
    b.style.left = pos.x + "%";
    b.style.top = pos.y + "%";
    b.style.width = pos.w + "%";
    b.style.zIndex = String(100 + Math.round(pos.y));
    b.title = H.n;
    b.innerHTML = ic("house", k, H.em) +
      "<span class='chip'><b class='nm'>" + esc(H.n) + "</b> " +
      "<span class='num'>" + h.slots.length + "/" + cap(k) + "</span></span>";
    if(c.ready) b.appendChild(el("span", "tag ready", String(c.ready)));
    else if(c.hungry) b.appendChild(el("span", "tag need", "!"));
    b.onclick = function(){ openHouse(k); };
    put.push(b);
  });

  /* Живность во дворе: у занятой постройки пасётся пара подопечных. Во дворе
     оригинала куры и гуси ходят сами по себе, и без них двор выглядит нежилым. */
  HKEYS.forEach(function(k){
    var slots = S.houses[k].slots, pos = YARD[k];
    if(!slots.length || !WALK[k]) return;
    var ids = [];
    slots.forEach(function(a){ if(ids.indexOf(a.breed) < 0) ids.push(a.breed); });
    ids.slice(0, 2).forEach(function(id, i){
      if(!ISO.breed[id]) return;                 // у растений во дворе делать нечего
      var sp = walkSpot(pos, i);
      var w = el("div", "deco walk");
      w.style.left = sp.x + "%";
      w.style.top = sp.y + "%";
      w.style.width = sp.w + "%";
      w.style.zIndex = String(100 + Math.round(sp.y));
      w.innerHTML = ic("breed", id, "");
      w.title = breed(id) ? breed(id).n : "";
      put.push(w);
    });
  });

  S.decor.forEach(function(id){
    var pos = DECOR_SPOT[id];
    if(!pos) return;
    var d = el("div", "deco");
    d.style.left = pos.x + "%";
    d.style.top = pos.y + "%";
    d.style.width = pos.w + "%";
    d.style.zIndex = String(100 + Math.round(pos.y));
    var em = "";
    DECOR.forEach(function(x){ if(x.id === id) em = x.em; });
    d.innerHTML = ic("prop", id, em);
    put.push(d);
  });

  put.forEach(function(n){ scene.appendChild(n); });
}
function renderQuestStrip(){
  var s = $("qstrip");
  s.innerHTML = "";
  if(qview > QUESTS.length - 1) qview = QUESTS.length - 1;
  if(qview < 0) qview = 0;
  var q = QUESTS[qview], done = qview < S.quest;
  var icon = el("div", "ic");
  icon.innerHTML = done ? "<i class='em'>✅</i>" : rewardIcon(q.rw);
  var body = el("div", "body");
  body.innerHTML = "<b>" + esc(q.t) + "</b><small>" + esc(q.d) + "</small>" +
    "<small class='rw'>Награда: " + esc(q.rw.nm) + (q.rw.n ? ". Количество: " + q.rw.n : "") +
    (done ? " — <span class='done'>выполнено</span>" : " · <span class='num'>" + fmt(Math.min(qprog(q), q.n)) + "/" + fmt(q.n) + "</span>") + "</small>";
  var pg = el("div", "pg");
  var up = el("button", null, "▲"), dn = el("button", null, "▼");
  up.onclick = function(){ qview = Math.max(0, qview - 1); renderQuestStrip(); };
  dn.onclick = function(){ qview = Math.min(QUESTS.length - 1, qview + 1); renderQuestStrip(); };
  pg.appendChild(up); pg.appendChild(dn);
  s.appendChild(icon); s.appendChild(body); s.appendChild(pg);
}
function renderTabs(){
  var t = $("tabs");
  if(t.children.length) return;
  [["TOP 100", openTop, "top"], ["Друзья", openFriends, "friends"], ["Задания", openQuests, "quests"],
   ["Госзаказ", openContracts, "wheat"], ["Бонусы", openBonus, "bonus"], ["Склад", openStore, "store"],
   ["Магазин", function(){ openShop(); }, "shop"]]
  .forEach(function(p){
    var b = el("button", null, (uiIc(p[2], "tab") || "") + "<span>" + p[0] + "</span>");
    b.onclick = function(){ closeAll(); p[1](); };
    t.appendChild(b);
  });
}
function after(){
  if(!S) return;
  renderHud(); renderYard(); renderQuestStrip();
  panels = panels.filter(function(l){ return document.body.contains(l.scrim); });
  panels.forEach(function(l){ l.fn(); });
}

/* ===================== вход и регистрация ===================== */
function authScreen(mode, prefill){
  closeAll();
  var w = makeWin(mode === "register" ? "Регистрация" : mode === "reset" ? "Новый пароль" : "Вход", "sm");
  w.win.querySelector(".x").remove();          // без аккаунта играть не выйдет — закрывать нечего
  var body = w.body;
  var note = el("div", "row");
  note.style.marginBottom = "8px";
  body.appendChild(note);

  function field(id, label, type, value){
    var wrap = el("label", null, "<b style='display:block;font-size:13px'>" + esc(label) + "</b>");
    wrap.style.display = "block";
    wrap.style.marginBottom = "7px";
    var i = document.createElement("input");
    i.id = id; i.type = type; i.value = value || "";
    i.style.cssText = "width:100%;padding:7px;border:2px solid var(--wood-dk);border-radius:6px;background:#fff8e6;font:inherit";
    if(type === "email") i.autocomplete = "email";
    if(type === "password") i.autocomplete = mode === "login" ? "current-password" : "new-password";
    wrap.appendChild(i);
    body.appendChild(wrap);
    return i;
  }
  var email, nick, pass, token;
  if(mode === "reset"){
    note.innerHTML = "<span class='ic'>🔑</span><span class='grow'><small>Придумайте новый пароль — не короче восьми знаков.</small></span>";
    pass = field("f-pass", "Новый пароль", "password");
    token = (prefill && prefill.token) || "";
  } else {
    note.innerHTML = mode === "register"
      ? "<span class='ic'>🌾</span><span class='grow'><small>Заведём колхоз. На почту придёт код — без него в игру не пустят.</small></span>"
      : "<span class='ic'>🚪</span><span class='grow'><small>Входите — хозяйство ждёт там же, где вы его оставили.</small></span>";
    email = field("f-email", "Почта", "email", (prefill && prefill.email) || "");
    if(mode === "register") nick = field("f-nick", "Имя председателя", "text", "");
    pass = field("f-pass", "Пароль", "password");
  }
  var msg = el("div", null, "");
  msg.style.cssText = "font-size:13px;font-weight:700;min-height:18px";
  body.appendChild(msg);
  function say(t, bad){ msg.textContent = t; msg.style.color = bad ? "#bf3b2c" : "#25611a"; }

  var buttons = [];
  if(mode === "login"){
    buttons.push({label:"Войти", cls:"go", on:submit});
    buttons.push({label:"Регистрация", cls:"flat", on:function(){ authScreen("register", {email:email.value}); }});
  } else if(mode === "register"){
    buttons.push({label:"Завести колхоз", cls:"go", on:submit});
    buttons.push({label:"У меня есть аккаунт", cls:"flat", on:function(){ authScreen("login", {email:email.value}); }});
  } else {
    buttons.push({label:"Сохранить пароль", cls:"go", on:submit});
  }
  footer(w, buttons);
  if(mode === "login"){
    var extra = el("p", null, "");
    var forgot = el("button", "btn flat", "Забыли пароль?");
    forgot.style.marginTop = "6px";
    forgot.onclick = function(){
      if(!email.value) return say("Сначала впишите почту.", true);
      api("/api/auth/forgot", {email:email.value})
        .then(function(r){ say(r.message); })
        .catch(function(e){ say(e.message, true); });
    };
    extra.appendChild(forgot);
    body.appendChild(extra);
  }
  function submit(){
    say("Секунду…");
    if(mode === "login"){
      api("/api/auth/login", {email:email.value, password:pass.value})
        .then(function(){ closeAll(); boot(); })
        .catch(function(e){ say(e.message, true); });
    } else if(mode === "register"){
      api("/api/auth/register", {email:email.value, password:pass.value, nick:nick.value})
        .then(function(r){ closeAll(); if(r.verified) boot(); else verifyScreen(email.value, r.message); })
        .catch(function(e){ say(e.message, true); });
    } else {
      api("/api/auth/reset", {token:token, password:pass.value})
        .then(function(r){ closeAll(); authScreen("login", {}); toast(r.message); })
        .catch(function(e){ say(e.message, true); });
    }
  }
  body.querySelectorAll("input").forEach(function(i){
    i.addEventListener("keydown", function(e){ if(e.key === "Enter") submit(); });
  });
}
/* Экран подтверждения: шесть цифр из письма. Ссылка в письме тоже есть и
   работает — она выручает, когда почту открывают на другом устройстве, —
   поэтому кнопка «я перешёл по ссылке» остаётся. */
function verifyScreen(email, message){
  closeAll();
  var w = makeWin("Подтвердите почту", "sm");
  w.win.querySelector(".x").remove();
  var box = el("div", "reward-box");
  box.appendChild(el("div", "im", "✉️"));
  box.appendChild(el("div", null, esc(message || ("Мы отправили код на " + email + "."))));
  w.body.appendChild(box);

  var hint = el("p", null, "Впишите шесть цифр из письма. В письме есть и ссылка — если открыли её, нажмите «Я перешёл по ссылке».");
  hint.style.cssText = "font-size:13px;margin:10px 0 0";
  w.body.appendChild(hint);

  var code = document.createElement("input");
  code.id = "f-code";
  code.type = "text";
  code.inputMode = "numeric";
  code.autocomplete = "one-time-code";
  code.maxLength = 6;
  code.placeholder = "000000";
  code.style.cssText = "display:block;width:100%;margin-top:10px;padding:10px;" +
    "border:2px solid var(--wood-dk);border-radius:6px;" +
    "background:#fff8e6;font:700 26px/1.2 Georgia,serif;letter-spacing:10px;text-align:center";
  w.body.appendChild(code);

  var msg = el("div", null, "");
  msg.style.cssText = "font-size:13px;font-weight:700;min-height:18px;margin-top:6px";
  w.body.appendChild(msg);
  function say(t, bad){ msg.textContent = t; msg.style.color = bad ? "#bf3b2c" : "#25611a"; }

  function submit(){
    var v = String(code.value || "").replace(/\D/g, "");
    if(v.length !== 6) return say("Код состоит из шести цифр.", true);
    say("Секунду…");
    api("/api/auth/verify-code", {email:email, code:v})
      .then(function(r){ closeAll(); toast(r.message); boot(); })
      .catch(function(e){ say(e.message, true); code.select(); });
  }
  /* Код обычно вставляют из письма — чистим от пробелов и дефисов на лету. */
  code.addEventListener("input", function(){
    var v = String(code.value || "").replace(/\D/g, "").slice(0, 6);
    if(v !== code.value) code.value = v;
    if(v.length === 6) submit();
  });
  code.addEventListener("keydown", function(e){ if(e.key === "Enter") submit(); });

  footer(w, [
    {label:"Выслать код заново", cls:"flat", on:function(){
      api("/api/auth/resend", {email:email}).then(function(r){ toast(r.message); }).catch(function(e){ toast(e.message, true); });
    }},
    {label:"Я перешёл по ссылке", cls:"flat", on:function(){ closeAll(); boot(); }},
    {label:"Подтвердить", cls:"go", on:submit}
  ]);
  setTimeout(function(){ code.focus(); }, 50);
}

/* ===================== запуск ===================== */
var started = false;
function startGame(){
  /* Класс снимаем до проверки: boot() вешает его при каждом вызове, а
     обвязку ниже надо ставить один раз. Если выйти раньше — двор так и
     останется спрятанным. Ловится на повторном boot(): например, когда
     игрок жмёт «Я перешёл по ссылке» на уже загруженной игре. */
  document.body.classList.remove("booting");
  if(started) return;
  started = true;
  renderTabs();
  $("shopBtn").onclick = function(){ closeAll(); openShop(); };
  $("questBtn").onclick = function(){ closeAll(); openQuests(); };
  $("aboutBtn").onclick = function(){ closeAll(); openAbout(); };
  $("logoutBtn").onclick = function(){
    api("/api/auth/logout", {}).then(function(){ S = null; started = false; location.reload(); });
  };
  $("renameBtn").onclick = function(){
    var v = prompt("Как назовём колхоз?", S.farm);
    if(v && v.trim()) act("rename", {name:v.trim()});
  };
  var hi = 0;
  setInterval(function(){ hi = (hi + 1) % HINTS.length; $("hint").textContent = HINTS[hi]; }, 12000);
  setInterval(function(){
    if(!S) return;
    renderHud(); renderYard(); renderQuestStrip();
    live = live.filter(function(l){ return document.body.contains(l.scrim); });
    live.forEach(function(l){ l.fn(); });
  }, 1000);
  setInterval(function(){ if(S) sync(); }, 20000);   // энергия, питомцы и работа помощников считаются на сервере
  document.addEventListener("visibilitychange", function(){ if(!document.hidden && S) sync(); });
}
function boot(){
  document.body.classList.add("booting");
  var params = new URLSearchParams(location.search);
  if(params.get("reset")){
    var t = params.get("reset");
    history.replaceState(null, "", location.pathname);
    return authScreen("reset", {token:t});
  }
  if(params.get("verify")){
    toast(params.get("verify") === "ok" ? "Почта подтверждена, с новосельем." : "Ссылка не сработала — запросите новую.", params.get("verify") !== "ok");
    history.replaceState(null, "", location.pathname);
  }
  api("/api/auth/me").then(function(r){
    ME = r.user;
    if(!ME) return authScreen("login", {});
    if(!ME.verified) return verifyScreen(ME.email, null);
    return api("/api/game").then(function(g){
      closeAll();
      startGame();
      applyResult(g);
      $("renameBtn").textContent = S.farm;
    });
  }).catch(function(e){
    if(e.code === "email_unverified" && ME) return verifyScreen(ME.email, null);
    toast(e.message, true);
    authScreen("login", {});
  });
}
boot();
