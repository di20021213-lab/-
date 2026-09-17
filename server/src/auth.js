"use strict";
const crypto = require("crypto");
const {db, now, rateLimit} = require("./db");

const SESSION_TTL = 30 * 24 * 3600 * 1000;   // месяц
const VERIFY_TTL  = 24 * 3600 * 1000;        // сутки
const RESET_TTL   = 3600 * 1000;             // час

/* ---------- пароли: scrypt из стандартной библиотеки, без сторонних зависимостей ---------- */
const N = 16384, R = 8, P = 1, KEYLEN = 64;
function hashPassword(pw){
  const salt = crypto.randomBytes(16);
  const key = crypto.scryptSync(pw, salt, KEYLEN, {N, r:R, p:P, maxmem:64 * 1024 * 1024});
  return ["scrypt", N, R, P, salt.toString("base64"), key.toString("base64")].join("$");
}
function verifyPassword(pw, stored){
  try{
    const [alg, n, r, p, salt, key] = String(stored).split("$");
    if(alg !== "scrypt") return false;
    const want = Buffer.from(key, "base64");
    const got = crypto.scryptSync(pw, Buffer.from(salt, "base64"), want.length,
      {N:Number(n), r:Number(r), p:Number(p), maxmem:64 * 1024 * 1024});
    return crypto.timingSafeEqual(want, got);
  }catch(e){ return false; }
}

/* ---------- одноразовые токены: в базе только хеш ---------- */
const sha = t => crypto.createHash("sha256").update(t).digest("hex");
const rawToken = () => crypto.randomBytes(32).toString("base64url");

function issueEmailToken(userId, kind){
  const raw = rawToken();
  const ttl = kind === "verify" ? VERIFY_TTL : RESET_TTL;
  db.prepare("UPDATE email_tokens SET used_at = ? WHERE user_id = ? AND kind = ? AND used_at IS NULL")
    .run(now(), userId, kind);
  db.prepare("INSERT INTO email_tokens(user_id, kind, token_hash, created_at, expires_at) VALUES(?,?,?,?,?)")
    .run(userId, kind, sha(raw), now(), now() + ttl);
  return raw;
}
function consumeEmailToken(raw, kind){
  if(!raw) return null;
  const row = db.prepare("SELECT * FROM email_tokens WHERE token_hash = ? AND kind = ?").get(sha(raw), kind);
  if(!row || row.used_at || row.expires_at < now()) return null;
  db.prepare("UPDATE email_tokens SET used_at = ? WHERE id = ?").run(now(), row.id);
  return row.user_id;
}

/* ---------- сессии ---------- */
function createSession(userId, ua, ip){
  const raw = rawToken();
  db.prepare("INSERT INTO sessions(user_id, token_hash, created_at, expires_at, user_agent, ip) VALUES(?,?,?,?,?,?)")
    .run(userId, sha(raw), now(), now() + SESSION_TTL, String(ua || "").slice(0, 200), String(ip || "").slice(0, 60));
  return raw;
}
function userBySession(raw){
  if(!raw) return null;
  const row = db.prepare(
    "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id " +
    "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ? AND u.status = 'active'"
  ).get(sha(raw), now());
  return row || null;
}
function revokeSession(raw){
  if(!raw) return;
  db.prepare("UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL").run(now(), sha(raw));
}
function revokeAllSessions(userId){
  db.prepare("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL").run(now(), userId);
}

/* ---------- проверки ввода ---------- */
const EMAIL_RE = /^[^\s@]+@[^\s@.]+\.[^\s@]{2,}$/;
function checkEmail(v){
  const email = String(v || "").trim().toLowerCase();
  if(!EMAIL_RE.test(email) || email.length > 254) return {ok:false, msg:"Почта выглядит неправильно."};
  return {ok:true, email};
}
function checkPassword(v){
  const pw = String(v || "");
  if(pw.length < 8) return {ok:false, msg:"Пароль короче восьми знаков."};
  if(pw.length > 200) return {ok:false, msg:"Пароль длиннее двухсот знаков."};
  return {ok:true, pw};
}
function checkNick(v, email){
  let nick = String(v || "").trim();
  if(!nick) nick = email.split("@")[0];
  nick = nick.slice(0, 24);
  if(nick.length < 2) return {ok:false, msg:"Имя короче двух знаков."};
  return {ok:true, nick};
}

function userByEmail(email){ return db.prepare("SELECT * FROM users WHERE email = ?").get(email) || null; }
function createUser(email, password, nick){
  const t = now();
  const r = db.prepare(
    "INSERT INTO users(email, password_hash, nick, created_at) VALUES(?,?,?,?)"
  ).run(email, hashPassword(password), nick, t);
  return db.prepare("SELECT * FROM users WHERE id = ?").get(r.lastInsertRowid);
}
function setPassword(userId, password){
  db.prepare("UPDATE users SET password_hash = ? WHERE id = ?").run(hashPassword(password), userId);
  revokeAllSessions(userId);
}
function markVerified(userId){
  db.prepare("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) WHERE id = ?").run(now(), userId);
}

module.exports = {
  hashPassword, verifyPassword, issueEmailToken, consumeEmailToken,
  createSession, userBySession, revokeSession, revokeAllSessions,
  checkEmail, checkPassword, checkNick, userByEmail, createUser, setPassword, markVerified,
  rateLimit, SESSION_TTL
};
