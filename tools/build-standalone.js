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

// шрифты из сети оставляем, но помечаем: без интернета подставится системный
const bundle = [
  "<script>window.IMG = " + JSON.stringify(images) + ";</script>",
  "<script>\n" + read("content.js") + "\n</script>",
  "<script>\n" + read("rules.js") + "\n</script>",
  "<script>\n" + read("offline.js") + "\n</script>",
  "<script>\n" + read("game.js") + "\n</script>"
].join("\n");

fs.mkdirSync(OUT, {recursive:true});
const file = path.join(OUT, "index.html");
fs.writeFileSync(file, html.trimEnd() + "\n\n" + bundle + "\n");
const size = fs.statSync(file).size;
console.log("собрано: " + file);
console.log("картинок: " + Object.keys(images).length + ", размер файла: " + (size / 1048576).toFixed(2) + " МБ");
