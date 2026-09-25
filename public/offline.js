"use strict";
/* Офлайн-движок для сборки без сервера (dist/index.html и опубликованная демка).
   Считает по тем же правилам из rules.js, что и сервер, только состояние держит
   в localStorage, а не в базе. Клиент об этом не знает: он всё так же зовёт api(). */
(function(){
  var C = window.CONTENT, R = window.RULES;
  /* Витрина — отдельная сборка для осмотра графики: всё открыто, во всех
     постройках живность всех пород. Хранится в своей ячейке, чтобы не
     затирать обычную игру, если открыть обе в одном браузере. */
  var DEMO = !!window.DEMO_MAX;
  var KEY = DEMO ? "dyshlo-vitrina-v1" : "dyshlo-offline-v2";
  var uid = 1, S = null;

  function fresh(){
    var t = Date.now();
    var s = {
      nick:"Председатель", farm:"Червонэ дышло",
      silver:500, gems:0, xp:0, lvl:1, energy:33, enAt:t,
      dog:60, cat:60, petAt:t, quest:0, boostUntil:0, vympUntil:0, helpAt:0,
      daily:{date:null, streak:0, opened:false, picked:-1},
      feed:{}, res:{}, items:{}, gifts:{}, houses:{}, prods:{},
      decor:[], helpers:[], c:{}, helped:{}
    };
    C.FEEDS.forEach(function(f){ s.feed[f.id] = 0; });
    C.RES.forEach(function(r){ s.res[r.id] = 0; });
    C.HKEYS.forEach(function(k){ s.houses[k] = {lvl:1, slots:[]}; s.prods[k] = {n:0, val:0}; });
    s.feed.low = 3;
    s.houses.kury.slots = [{id:uid++, breed:"rusbel", se:3, fed:true, ready:t - 1000, feedId:"low"}];
    return DEMO ? showcase(s, t) : s;
  }

  /** Заполняет двор по максимуму: предельный уровень построек, все породы
      на местах и все три состояния сразу — готово, зреет, просит корма.
      Иначе на снимке видно только одно из трёх. */
  function showcase(s, t){
    s.lvl = 20; s.xp = 0; s.silver = 9000000; s.gems = 500;
    s.energy = 100; s.quest = 4; s.dog = 100; s.cat = 100;
    C.FEEDS.forEach(function(f){ s.feed[f.id] = 99; });
    C.RES.forEach(function(r){ s.res[r.id] = 99; });
    C.DECOR.forEach(function(d){ s.decor.push(d.id); });
    C.HELPERS.forEach(function(h){ s.helpers.push(h.id); });
    (C.GIFTS || []).forEach(function(g){ s.gifts[g.id] = 3; });
    C.HKEYS.forEach(function(k){
      var breeds = C.BREEDS.filter(function(b){ return b.h === k; });
      var max = C.CAP[C.CAP.length - 1];
      s.houses[k] = {lvl:C.CAP.length, slots:[]};
      for(var i = 0; i < max && breeds.length; i++){
        var b = breeds[i % breeds.length], st = i % 3;
        s.houses[k].slots.push({
          id: uid++, breed: b.id, se: b.se, feedId: "high",
          fed: st !== 2,                                   // каждый третий просит корма
          ready: st === 0 ? t - 1000 : t + 3600000 * (1 + st)
        });
      }
      s.prods[k] = {n:250, val:12000};
    });
    return s;
  }
  function load(){
    try{
      var raw = localStorage.getItem(KEY);
      if(raw){
        var d = JSON.parse(raw);
        if(d && d.houses && d.silver != null){
          S = d;
          C.HKEYS.forEach(function(k){
            if(!S.houses[k]) S.houses[k] = {lvl:1, slots:[]};
            if(!S.prods[k]) S.prods[k] = {n:0, val:0};
            S.houses[k].slots.forEach(function(a){ if(a.id >= uid) uid = a.id + 1; });
          });
          return;
        }
      }
    }catch(e){ /* приватное окно — играем без сохранения */ }
    S = fresh();
  }
  function save(){
    try{ localStorage.setItem(KEY, JSON.stringify(S)); }catch(e){}
  }
  function idify(){   // на сервере номера мест выдаёт база, здесь — счётчик
    C.HKEYS.forEach(function(k){
      S.houses[k].slots.forEach(function(a){ if(!a.id) a.id = uid++; });
    });
  }
  function reply(res, quests, tickMsg){
    return {state:R.publicState(S), msg:(res && res.msg) || tickMsg || null,
            gift:(res && res.gift) || null, quests:quests || []};
  }
  function top(){
    var me = {nick:S.nick, farm:S.farm, level:S.lvl, xp:S.xp, score:S.lvl * 1000 + S.xp};
    var list = C.RIVALS.map(function(r){
      return {nick:r[0], farm:r[1].replace(/[«»]/g, ""), level:Math.max(1, Math.round(r[2] / 1000)), xp:r[2] % 1000, score:r[2]};
    });
    list.push(me);
    list.sort(function(a, b){ return b.score - a.score; });
    return {top:list};
  }

  /** Тот же договор, что у сервера: вернуть состояние или бросить ошибку с текстом. */
  window.LOCAL_API = function(url, body){
    if(!S) load();
    return new Promise(function(resolve, reject){
      try{
        if(url === "/api/auth/me") return resolve({user:{id:0, email:"", nick:S.nick, verified:true}});
        if(url === "/api/auth/logout"){
          try{ localStorage.removeItem(KEY); }catch(e){}
          S = fresh(); save();
          return resolve({ok:true});
        }
        if(url === "/api/top") return resolve(top());
        if(url === "/api/content") return resolve(C);

        var action = url === "/api/game" ? "sync" : url.replace("/api/game/", "");
        var tickMsg = R.tick(S);       // подъёмные выдаются в tick, о них надо сказать
        var res = {msg:null};
        if(action !== "sync"){
          var fn = R.ACTIONS[action];
          if(!fn) throw R.fail("Неизвестное действие.");
          res = fn(S, body || {}) || {};
        }
        var quests = R.checkQuests(S);
        delete S._newHelp;
        idify();
        save();
        resolve(reply(res, quests, tickMsg));
      }catch(e){
        var err = new Error(e && e.message ? e.message : "Что-то пошло не так.");
        err.status = e && e.gameError ? 400 : 500;
        reject(err);
      }
    });
  };
})();
