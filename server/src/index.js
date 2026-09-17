"use strict";
const path = require("path");
const express = require("express");
const {migrate, db, rateLimit, logEvent, now} = require("./db");
const A = require("./auth");
const G = require("./game");
const mail = require("./mail");
const CONTENT = require("../../public/content.js");

migrate();

const PORT = Number(process.env.PORT || 3000);
const PUBLIC_URL = (process.env.PUBLIC_URL || ("http://localhost:" + PORT)).replace(/\/+$/, "");
const SECURE = PUBLIC_URL.startsWith("https://");
const COOKIE = "dyshlo_sid";

const app = express();
app.disable("x-powered-by");
app.use(express.json({limit:"32kb"}));
app.use(express.static(path.join(__dirname, "..", "..", "public"), {extensions:["html"]}));

/* ------------------------------------------------------------------ мелочи */
function cookies(req){
  const out = {};
  String(req.headers.cookie || "").split(";").forEach(p => {
    const i = p.indexOf("=");
    if(i > 0) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}
function setSession(res, token, maxAgeMs){
  const parts = [COOKIE + "=" + encodeURIComponent(token), "Path=/", "HttpOnly", "SameSite=Lax",
                 "Max-Age=" + Math.floor(maxAgeMs / 1000)];
  if(SECURE) parts.push("Secure");
  res.setHeader("Set-Cookie", parts.join("; "));
}
function clearSession(res){
  res.setHeader("Set-Cookie", COOKIE + "=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0");
}
const ipOf = req => (req.headers["x-forwarded-for"] || "").split(",")[0].trim() || req.socket.remoteAddress || "";
function auth(req, res, next){
  const u = A.userBySession(cookies(req)[COOKIE]);
  if(!u) return res.status(401).json({error:"Нужно войти.", code:"no_session"});
  req.user = u;
  next();
}
function requireVerified(req, res, next){
  if(!req.user.email_verified_at){
    return res.status(403).json({error:"Подтвердите почту — мы прислали ссылку.", code:"email_unverified"});
  }
  next();
}
function farmId(user){
  const f = G.farmOfUser(user.id);
  return f ? f.id : G.createFarm(user.id, user.nick);
}
const pub = u => ({id:u.id, email:u.email, nick:u.nick, verified:!!u.email_verified_at});

/* ------------------------------------------------------------------ аккаунты */
app.post("/api/auth/register", async (req, res) => {
  const rl = rateLimit("reg:" + ipOf(req), 10, 3600 * 1000);
  if(!rl.ok) return res.status(429).json({error:"Слишком часто. Попробуйте через " + rl.retryIn + " с."});
  const e = A.checkEmail(req.body.email);
  if(!e.ok) return res.status(400).json({error:e.msg});
  const p = A.checkPassword(req.body.password);
  if(!p.ok) return res.status(400).json({error:p.msg});
  const n = A.checkNick(req.body.nick, e.email);
  if(!n.ok) return res.status(400).json({error:n.msg});

  const existing = A.userByEmail(e.email);
  if(existing){
    /* Не говорим, занят ли адрес: это утечка. Если аккаунт есть и не подтверждён — шлём ссылку заново. */
    if(!existing.email_verified_at){
      const token = A.issueEmailToken(existing.id, "verify");
      await mail.sendVerify(existing.email, PUBLIC_URL + "/api/auth/verify?token=" + token).catch(err => console.error(err));
    }
    return res.json({ok:true, message:"Если адрес свободен, письмо уже в пути. Проверьте почту."});
  }
  const user = A.createUser(e.email, p.pw, n.nick);
  G.createFarm(user.id, user.nick);
  const token = A.issueEmailToken(user.id, "verify");
  await mail.sendVerify(user.email, PUBLIC_URL + "/api/auth/verify?token=" + token).catch(err => console.error(err));
  logEvent(null, "register", {user:user.id});
  res.json({ok:true, message:"Готово. Ссылка для подтверждения ушла на " + user.email + "."});
});

app.get("/api/auth/verify", (req, res) => {
  const userId = A.consumeEmailToken(String(req.query.token || ""), "verify");
  if(!userId) return res.redirect("/?verify=fail");
  A.markVerified(userId);
  const token = A.createSession(userId, req.headers["user-agent"], ipOf(req));
  setSession(res, token, A.SESSION_TTL);
  res.redirect("/?verify=ok");
});

app.post("/api/auth/resend", async (req, res) => {
  const e = A.checkEmail(req.body.email);
  if(!e.ok) return res.status(400).json({error:e.msg});
  const rl = rateLimit("resend:" + e.email, 5, 3600 * 1000);
  if(!rl.ok) return res.status(429).json({error:"Письмо уже отправляли. Подождите " + rl.retryIn + " с."});
  const u = A.userByEmail(e.email);
  if(u && !u.email_verified_at){
    const token = A.issueEmailToken(u.id, "verify");
    await mail.sendVerify(u.email, PUBLIC_URL + "/api/auth/verify?token=" + token).catch(err => console.error(err));
  }
  res.json({ok:true, message:"Если адрес у нас есть и не подтверждён, письмо ушло."});
});

app.post("/api/auth/login", (req, res) => {
  const e = A.checkEmail(req.body.email);
  if(!e.ok) return res.status(400).json({error:e.msg});
  const rl = rateLimit("login:" + e.email, 10, 15 * 60 * 1000);
  if(!rl.ok) return res.status(429).json({error:"Много попыток. Подождите " + rl.retryIn + " с."});
  const u = A.userByEmail(e.email);
  if(!u || !A.verifyPassword(String(req.body.password || ""), u.password_hash)){
    return res.status(401).json({error:"Почта или пароль не подходят."});
  }
  if(u.status !== "active") return res.status(403).json({error:"Аккаунт заблокирован."});
  db.prepare("UPDATE users SET last_login_at = ? WHERE id = ?").run(now(), u.id);
  const token = A.createSession(u.id, req.headers["user-agent"], ipOf(req));
  setSession(res, token, A.SESSION_TTL);
  farmId(u);
  res.json({ok:true, user:pub(u)});
});

app.post("/api/auth/logout", (req, res) => {
  A.revokeSession(cookies(req)[COOKIE]);
  clearSession(res);
  res.json({ok:true});
});

app.get("/api/auth/me", (req, res) => {
  const u = A.userBySession(cookies(req)[COOKIE]);
  res.json({user:u ? pub(u) : null});
});

app.post("/api/auth/forgot", async (req, res) => {
  const e = A.checkEmail(req.body.email);
  if(!e.ok) return res.status(400).json({error:e.msg});
  const rl = rateLimit("forgot:" + e.email, 5, 3600 * 1000);
  if(!rl.ok) return res.status(429).json({error:"Письмо уже отправляли. Подождите " + rl.retryIn + " с."});
  const u = A.userByEmail(e.email);
  if(u){
    const token = A.issueEmailToken(u.id, "reset");
    await mail.sendReset(u.email, PUBLIC_URL + "/?reset=" + token).catch(err => console.error(err));
  }
  res.json({ok:true, message:"Если такой адрес есть, письмо со ссылкой ушло."});
});

app.post("/api/auth/reset", (req, res) => {
  const p = A.checkPassword(req.body.password);
  if(!p.ok) return res.status(400).json({error:p.msg});
  const userId = A.consumeEmailToken(String(req.body.token || ""), "reset");
  if(!userId) return res.status(400).json({error:"Ссылка больше не работает — запросите новую."});
  A.setPassword(userId, p.pw);
  A.markVerified(userId);
  res.json({ok:true, message:"Пароль изменён, войдите заново."});
});

/* ------------------------------------------------------------------ игра */
app.get("/api/content", (req, res) => res.json(CONTENT));

app.get("/api/game", auth, requireVerified, (req, res) => {
  try{
    res.json(G.perform(farmId(req.user), "sync", {}));
  }catch(err){ gameError(res, err); }
});

app.post("/api/game/:action", auth, requireVerified, (req, res) => {
  try{
    res.json(G.perform(farmId(req.user), String(req.params.action), req.body || {}));
  }catch(err){ gameError(res, err); }
});

app.get("/api/top", (req, res) => res.json({top:G.leaderboard(100)}));

function gameError(res, err){
  if(err && err.gameError) return res.status(400).json({error:err.message});
  console.error(err);
  res.status(500).json({error:"Что-то сломалось на сервере."});
}

app.use((req, res) => res.status(404).json({error:"Нет такой страницы."}));

if(require.main === module){
  app.listen(PORT, () => {
    console.log("Колхоз слушает " + PUBLIC_URL);
    if(!mail.realSmtp) console.log("Почта: SMTP не настроен, письма падают в var/mail и печатаются сюда же.");
  });
}
module.exports = app;
