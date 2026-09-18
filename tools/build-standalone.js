"use strict";
/* Собирает игру в один файл: разметка, стили, справочник, правила, офлайн-движок
   и клиент, плюс все картинки как data-URI. Такой файл открывается двойным кликом
   и не требует ни сервера, ни сети — им же публикуется демка.
   Запуск: node tools/build-standalone.js  ->  dist/index.html */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const PUB = path.join(ROOT, "public");
const OUT = path.join(ROOT, "dist");

const read = p => fs.readFileSync(path.join(PUB, p), "utf8");

// --- картинки в data-URI ---
const images = {};
function collect(dir, prefix){
  fs.readdirSync(path.join(PUB, dir), {withFileTypes:true}).forEach(e => {
    if(e.isDirectory()) return collect(path.join(dir, e.name), prefix + e.name + "/");
    if(!/\.(png|jpe?g|svg)$/i.test(e.name)) return;
    const buf = fs.readFileSync(path.join(PUB, dir, e.name));
    const mime = e.name.endsWith(".svg") ? "image/svg+xml"
               : /\.jpe?g$/i.test(e.name) ? "image/jpeg" : "image/png";
    images[prefix + e.name] = "data:" + mime + ";base64," + buf.toString("base64");
  });
}
collect("img", "img/");

let html = read("index.html");
html = html.replace(/<script src="[^"]+"><\/script>\s*/g, "");
// картинки, прописанные прямо в разметке, тоже заменяем на встроенные —
// иначе в одном файле они просто не находятся
html = html.replace(/src="(img\/[^"]+)"/g, (m, p) => images[p] ? 'src="' + images[p] + '"' : m);

// шрифты из сети оставляем, но помечаем: без интернета подставится системный
/** Две сборки: offline играет сама по себе, online ходит на сервер. */
function bundle(offline){
  const parts = [
    "<script>window.IMG = " + JSON.stringify(images) + ";</script>",
    "<script>\n" + read("content.js") + "\n</script>",
    "<script>\n" + read("rules.js") + "\n</script>"
  ];
  if(offline) parts.push("<script>\n" + read("offline.js") + "\n</script>");
  parts.push("<script>\n" + read("game.js") + "\n</script>");
  return html.trimEnd() + "\n\n" + parts.join("\n") + "\n";
}

fs.mkdirSync(OUT, {recursive:true});
for(const [name, offline] of [["index.html", true], ["client.html", false]]){
  const file = path.join(OUT, name);
  fs.writeFileSync(file, bundle(offline));
  console.log((offline ? "без сервера: " : "для сервера: ") + file +
              " — " + (fs.statSync(file).size / 1048576).toFixed(2) + " МБ");
}
console.log("картинок внутри: " + Object.keys(images).length);
