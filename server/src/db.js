"use strict";
const fs = require("fs");
const path = require("path");
const {DatabaseSync} = require("node:sqlite");

const ROOT = path.join(__dirname, "..", "..");
/* В собранном exe рядом с файлом нет исходников, поэтому база ложится
   возле самого исполняемого файла, а схема зашита в сборку. */
const BASE = process.env.KOLHOZ_HOME || (global.__SEA ? path.dirname(process.execPath) : ROOT);
const DB_PATH = process.env.DB_PATH || path.join(BASE, "var", "kolhoz.db");
const SCHEMA_PATH = path.join(ROOT, "server", "db", "schema.sql");

fs.mkdirSync(path.dirname(DB_PATH), {recursive:true});

/* Встроенный в Node SQLite вместо нативного модуля: так проект собирается
   в один исполняемый файл, а ставить ничего не нужно. */
const db = new DatabaseSync(DB_PATH);
db.exec("PRAGMA journal_mode = WAL");
db.exec("PRAGMA foreign_keys = ON");
db.exec("PRAGMA busy_timeout = 5000");

/* У встроенного SQLite нет обёртки транзакций, поэтому своя — с поддержкой
   вложенности через точки сохранения: perform() внутри себя зовёт saveState(). */
let depth = 0;
db.transaction = function(fn){
  return function(){
    const sp = "sp" + depth;
    db.exec(depth === 0 ? "BEGIN" : "SAVEPOINT " + sp);
    depth++;
    try{
      const out = fn.apply(this, arguments);
      depth--;
      db.exec(depth === 0 ? "COMMIT" : "RELEASE " + sp);
      return out;
    }catch(e){
      depth--;
      db.exec(depth === 0 ? "ROLLBACK" : "ROLLBACK TO " + sp);
      throw e;
    }
  };
};

/* Схема раскатывается через CREATE TABLE IF NOT EXISTS, а он не добавляет
   колонки в уже существующую таблицу. У игроков базы с прошлых версий, поэтому
   недостающие колонки досыпаем руками. */
const ADDED_COLUMNS = [
  ["farms", "bailout_day", "TEXT"]
];
function addMissingColumns(){
  ADDED_COLUMNS.forEach(([table, col, decl]) => {
    const has = db.prepare("SELECT COUNT(*) n FROM pragma_table_info(?) WHERE name = ?").get(table, col).n;
    if(!has) db.exec("ALTER TABLE " + table + " ADD COLUMN " + col + " " + decl);
  });
}
function migrate(){
  db.exec(global.__SCHEMA_SQL || fs.readFileSync(SCHEMA_PATH, "utf8"));
  addMissingColumns();
  return db.prepare("SELECT value FROM schema_meta WHERE key = 'version'").get().value;
}
const now = () => Date.now();

/** Простой счётчик обращений: n попыток за окно в windowMs. */
function rateLimit(bucket, n, windowMs){
  const t = now();
  const row = db.prepare("SELECT window_at, hits FROM rate_limits WHERE bucket = ?").get(bucket);
  if(!row || t - row.window_at > windowMs){
    db.prepare("INSERT INTO rate_limits(bucket, window_at, hits) VALUES(?,?,1) " +
               "ON CONFLICT(bucket) DO UPDATE SET window_at = excluded.window_at, hits = 1").run(bucket, t);
    return {ok:true, left:n - 1};
  }
  if(row.hits >= n) return {ok:false, retryIn:Math.ceil((windowMs - (t - row.window_at)) / 1000)};
  db.prepare("UPDATE rate_limits SET hits = hits + 1 WHERE bucket = ?").run(bucket);
  return {ok:true, left:n - row.hits - 1};
}
function logEvent(farmId, type, payload){
  db.prepare("INSERT INTO events(farm_id, at, type, payload) VALUES(?,?,?,?)")
    .run(farmId, now(), type, payload ? JSON.stringify(payload) : null);
}
module.exports = {db, migrate, rateLimit, logEvent, now, DB_PATH};
