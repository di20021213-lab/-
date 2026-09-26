// Ловит видео Kinescope и МТС Линк (и любые m3u8/mpd на этих сайтах) и
// передаёт приложению KinescopeDownloader (локальный приёмник 127.0.0.1).

const APP_URL = "http://127.0.0.1:53127/capture";
const TOKEN = "kinescope-local-capture";

const recentlySent = new Map();
const DEDUP_MS = 60000;

function extractKinescopeId(url) {
  // DASH-мастер даёт публичный id — его и берём.
  let m = url.match(/kinescope\.io\/([A-Za-z0-9]{6,})\/master\.mpd/);
  if (m) return m[1];
  m = url.match(/kinescope\.io\/embed\/([A-Za-z0-9]{6,})/);
  if (m) return m[1];
  m = url.match(/^https?:\/\/kinescope\.io\/([A-Za-z0-9]{6,})(?:[/?#]|$)/);
  if (m && m[1] !== "embed") return m[1];
  // HLS-мастер (kinescope.io/{uuid}/master.m3u8) НЕ шлём отдельно —
  // это тот же ролик под внутренним uuid, иначе будет дубль.
  return null;
}

function isManifest(url) {
  const u = url.split("?")[0].toLowerCase();
  if (u.endsWith(".m3u8") || u.endsWith(".mpd")) return true;
  // Некоторые CDN добавляют хвост после расширения (…/master.m3u8/seg…).
  return /\.(m3u8|mpd)(?:[/;]|$)/.test(u);
}

// Одно видео обычно отдаёт несколько манифестов (мастер + дорожки/качества).
// Схлопываем их к общей базе, чтобы не слать одно и то же по нескольку раз.
function dedupKey(url) {
  const clean = url.split("?")[0];
  // МТС Линк/вебинары: .../xxx.mp4/v1/index.m3u8 → до ".mp4/".
  const i = clean.indexOf(".mp4/");
  if (i !== -1) return clean.slice(0, i);
  // Kinescope (в т.ч. на своём домене): .../{id}/master.mpd | master.m3u8 |
  // {качество}/index.m3u8 → ключ до "/{id}".
  const m = clean.match(
    /^(https?:\/\/[^?#]+?\/[A-Za-z0-9_-]{6,})\/(?:master\.(?:mpd|m3u8)|[^/]+\/(?:index|playlist|chunklist|media)[^/]*\.m3u8)$/i
  );
  if (m) return m[1];
  return clean;
}

function flash(ok) {
  try {
    chrome.action.setBadgeBackgroundColor({ color: ok ? "#2E7D2E" : "#B00020" });
    chrome.action.setBadgeText({ text: ok ? "✓" : "!" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
  } catch (e) { /* нет chrome.action */ }
}

async function cookiesFor(url) {
  try {
    const list = await chrome.cookies.getAll({ url });
    return list.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    return "";
  }
}

// Заголовок вкладки, из которой пришёл запрос, — это как раз название
// вебинара/видео, показанное вверху страницы. Отдаём его приложению, чтобы
// оно подписало файл по-человечески, а не по id.
async function titleForTab(tabId) {
  if (tabId === undefined || tabId === null || tabId < 0) return "";
  try {
    const tab = await chrome.tabs.get(tabId);
    return (tab && tab.title) ? tab.title : "";
  } catch (e) {
    return "";
  }
}

async function post(payload) {
  const key = dedupKey(payload.url);
  const now = Date.now();
  if (now - (recentlySent.get(key) || 0) < DEDUP_MS) return;
  recentlySent.set(key, now);
  console.log("[KinescopeHelper] отправляю:", payload.url);
  try {
    const r = await fetch(APP_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Kinescope-Token": TOKEN },
      body: JSON.stringify(payload)
    });
    flash(r.ok);
  } catch (e) {
    console.log("[KinescopeHelper] приложение недоступно:", e.message);
    flash(false);
  }
}

chrome.webRequest.onBeforeRequest.addListener(
  async (details) => {
    const id = extractKinescopeId(details.url);
    if (id) {
      const title = await titleForTab(details.tabId);
      post({ url: "https://kinescope.io/" + id, title });
      return;
    }
    // Для Kinescope шлём только id (из master); под-плейлисты вроде
    // media.m3u8 не отправляем — иначе приложение качает дубль.
    if (/:\/\/[^/]*kinescope\.io\//.test(details.url)) return;
    if (isManifest(details.url)) {
      const cookies = await cookiesFor(details.url);
      const title = await titleForTab(details.tabId);
      post({
        url: details.url,
        referer: details.documentUrl || details.initiator || "",
        cookies,
        title
      });
    }
  },
  // Слушаем все сайты: видео бывают не только на Kinescope/МТС Линк, но и на
  // их собственных доменах. Ниже отправляем только манифесты m3u8/mpd и id
  // Kinescope, так что лишнего не шлём. Явные домены в host_permissions
  // гарантируют, что привычные площадки ловятся даже без доступа «на всех
  // сайтах» (Яндекс.Браузер по умолчанию ставит широкий доступ «по клику»).
  { urls: ["*://*/*"] }
);

// ------------------------------------------------------------------------- //
// Кнопка «Собрать со страницы»: разово вытащить все видео с открытой вкладки.
// ------------------------------------------------------------------------- //

// Выполняется в контексте страницы (в каждом фрейме). Возвращает всё, что
// похоже на видео: id Kinescope, прямые манифесты и ссылки на страницы записей.
function pageScan() {
  const out = { kinescope: [], manifests: [], links: [], href: "" };
  const push = (arr, v) => { if (v && arr.indexOf(v) === -1) arr.push(v); };
  try {
    out.href = location.href;
    const idInUrl = (u) => {
      const km = String(u || "").match(/kinescope\.io\/(?:embed\/)?([A-Za-z0-9]{6,})/);
      return km ? km[1] : null;
    };
    // Сам фрейм может быть плеером Kinescope.
    push(out.kinescope, idInUrl(location.href));

    // Явные iframe/ссылки/источники.
    document.querySelectorAll("iframe[src],a[href],source[src],video[src]").forEach((el) => {
      const u = el.getAttribute("src") || el.getAttribute("href") || "";
      push(out.kinescope, idInUrl(u));
      if (/\.(m3u8|mpd)(\?|$)/i.test(u)) {
        try { push(out.manifests, new URL(u, location.href).href); } catch (e) {}
      }
    });

    // Сырой HTML — id и манифесты, зашитые в разметку/скрипты.
    const html = document.documentElement ? document.documentElement.innerHTML : "";
    let m;
    const idRe = /kinescope\.io\/(?:embed\/)?([A-Za-z0-9]{6,})/g;
    while ((m = idRe.exec(html))) push(out.kinescope, m[1]);
    const manRe = /https?:\/\/[^\s"'<>\\]+?\.(?:m3u8|mpd)[^\s"'<>\\]*/g;
    while ((m = manRe.exec(html))) push(out.manifests, m[0]);

    // Ссылки-карточки: открываем их в фоне, чтобы поймать плеер.
    const origin = location.origin;
    const here = location.href.split("#")[0];
    const junk = /(login|logout|signin|signup|register|auth|profile|account|settings|help|support|about|contacts?|policy|terms|cart|checkout|search|tariff|pricing|payment|faq|blog\/?$)/i;
    document.querySelectorAll("a[href]").forEach((a) => {
      const href = a.href || "";
      if (!href) return;
      const clean = href.split("#")[0];
      if (clean === here) return;
      // Известные видеоплощадки — берём даже с другого домена.
      const knownHost = /(?:mts-link|webinar)\.ru|kinescope\.io/.test(href);
      // Свой домен — берём карточки: есть картинка-превью или «контентный» путь.
      const sameOrigin = href.indexOf(origin) === 0;
      const looksContent = /(lesson|video|record|watch|event|program|course|material|topic|episode|module|\/p\/|\/id\/|\/v\/|\/e\/|\/j\/|\/w\/)/i.test(clean);
      const hasThumb = !!a.querySelector("img");
      if (/\.(css|js|png|jpe?g|gif|svg|woff2?|ico)(\?|$)/i.test(clean)) return;
      if (junk.test(clean)) return;
      if (knownHost || (sameOrigin && (looksContent || hasThumb))) {
        push(out.links, clean);
      }
    });
  } catch (e) {
    out.error = String((e && e.message) || e);
  }
  return out;
}

// В открытой в фоне вкладке пробуем запустить плеер (без звука — так браузер
// разрешает автозапуск из скрипта), чтобы пошёл запрос манифеста.
function pagePlay() {
  document.querySelectorAll("video").forEach((v) => {
    try { v.muted = true; const p = v.play(); if (p && p.catch) p.catch(() => {}); } catch (e) {}
  });
  const sel =
    '[class*="play" i],[aria-label*="play" i],[aria-label*="воспро" i],button.vjs-big-play-button';
  const b = document.querySelector(sel);
  if (b) { try { b.click(); } catch (e) {} }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function triggerCapture(url) {
  let tab;
  try {
    tab = await chrome.tabs.create({ url, active: false });
  } catch (e) {
    return;
  }
  await sleep(3500); // даём странице прогрузиться
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: pagePlay });
  } catch (e) { /* нет доступа к этой вкладке — пропускаем */ }
  await sleep(5000); // ждём, пока манифест загрузится и попадёт в перехватчик
  try {
    await chrome.tabs.remove(tab.id);
  } catch (e) {}
}

async function collectFromActiveTab() {
  let tab;
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch (e) {
    return { error: "Не вижу активную вкладку: " + ((e && e.message) || e) };
  }
  if (!tab || tab.id === undefined) return { error: "Нет активной вкладки." };

  // Сканируем все фреймы (плеер часто в iframe). Если allFrames не сработал —
  // пробуем хотя бы главный фрейм.
  let results = null;
  try {
    results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: pageScan,
    });
  } catch (e) {
    try {
      results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: pageScan,
      });
    } catch (e2) {
      return { error: "Нет доступа к этой странице: " + ((e2 && e2.message) || e2) };
    }
  }

  const kinescope = new Set();
  const manifests = new Set();
  const links = new Set();
  let href = tab.url || "";
  for (const r of results || []) {
    const v = r && r.result;
    if (!v) continue;
    (v.kinescope || []).forEach((x) => kinescope.add(x));
    (v.manifests || []).forEach((x) => manifests.add(x));
    (v.links || []).forEach((x) => links.add(x));
    if (v.href && r.frameId === 0) href = v.href;
  }

  let sent = 0;
  for (const id of kinescope) {
    await post({ url: "https://kinescope.io/" + id, title: tab.title });
    sent++;
  }
  for (const url of manifests) {
    const cookies = await cookiesFor(url);
    await post({ url, referer: href, cookies, title: tab.title });
    sent++;
  }

  // Ссылки-карточки открываем по очереди в фоне (не больше 12 за раз).
  const linkList = [...links].slice(0, 12);
  const result = { sent, links: linkList.length, found: sent + linkList.length };
  if (linkList.length) {
    (async () => {
      let done = 0;
      for (const url of linkList) {
        done++;
        try {
          chrome.action.setBadgeBackgroundColor({ color: "#0A5AA0" });
          chrome.action.setBadgeText({ text: `${done}/${linkList.length}` });
        } catch (e) {}
        await triggerCapture(url);
      }
      try {
        chrome.action.setBadgeText({ text: "" });
      } catch (e) {}
    })();
  }
  return result;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "collect") {
    // Всегда отвечаем — даже при исключении, иначе попап покажет «Не удалось».
    collectFromActiveTab()
      .then(sendResponse)
      .catch((e) => sendResponse({ error: "Сбой: " + ((e && e.message) || e) }));
    return true; // ответ придёт асинхронно
  }
});

console.log("[KinescopeHelper] активно: слежу за Kinescope и МТС Линк.");
