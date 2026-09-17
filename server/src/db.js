"use strict";
const fs = require("fs");
const path = require("path");
const Database = require("better-sqlite3");

const ROOT = path.join(__dirname, "..", "..");
const DB_PATH = process.env.DB_PATH || path.join(ROOT, "var", "kolhoz.db");
const SCHEMA_PATH = path.join(ROOT, "server", "db", "schema.sql");

fs.mkdirSync(path.dirname(DB_PATH), {recursive:true});

const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");
db.pragma("busy_timeout = 5000");

function migrate(){
  db.exec(fs.readFileSync(SCHEMA_PATH, "utf8"));
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
