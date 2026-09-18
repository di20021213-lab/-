"use strict";
/* Читает .env из корня проекта. Своя пара строк вместо зависимости:
   уже заданные переменные окружения имеют приоритет, их не перетираем. */
const fs = require("fs");
const path = require("path");

/* Рядом с собранным exe исходников нет, поэтому .env ищем возле него самого. */
const BASE = process.env.KOLHOZ_HOME ||
  (global.__SEA ? path.dirname(process.execPath) : path.join(__dirname, "..", ".."));
const FILE = process.env.ENV_FILE || path.join(BASE, ".env");
try{
  const text = fs.readFileSync(FILE, "utf8");
  text.split(/\r?\n/).forEach(line => {
    const s = line.trim();
    if(!s || s.startsWith("#")) return;
    const i = s.indexOf("=");
    if(i < 1) return;
    const key = s.slice(0, i).trim();
    let val = s.slice(i + 1).trim();
    if((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) val = val.slice(1, -1);
    if(process.env[key] === undefined) process.env[key] = val;
  });
  console.log("Настройки прочитаны из " + FILE);
}catch(e){
  if(e.code !== "ENOENT") console.error("Не смог прочитать .env: " + e.message);
}
