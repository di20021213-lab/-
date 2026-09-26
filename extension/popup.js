const btn = document.getElementById("collect");
const status = document.getElementById("status");

function show(text) {
  status.textContent = text;
}

btn.addEventListener("click", () => {
  btn.disabled = true;
  show("Сканирую страницу…");
  chrome.runtime.sendMessage({ type: "collect" }, (res) => {
    if (chrome.runtime.lastError || !res) {
      show("Не удалось. Открой страницу с видео и попробуй снова.");
      btn.disabled = false;
      return;
    }
    if (res.error) {
      show(res.error);
      btn.disabled = false;
      return;
    }
    const parts = [];
    if (res.sent) parts.push(`Отправлено сразу: ${res.sent}`);
    if (res.links) {
      parts.push(
        `Открываю в фоне: ${res.links} стр. — следи за счётчиком на значке ` +
          `и за списком в приложении.`
      );
    }
    if (!parts.length) {
      parts.push(
        "На этой странице видео не нашёл. Открой саму запись (плеер) и " +
          "нажми кнопку там — либо просто запусти видео с включённой ловлей."
      );
    }
    show(parts.join("\n"));
    // Кнопку вернём: фоновый сбор идёт в service worker сам по себе.
    btn.disabled = false;
  });
});
