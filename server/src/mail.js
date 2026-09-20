"use strict";
const fs = require("fs");
const path = require("path");
const nodemailer = require("nodemailer");

const ROOT = path.join(__dirname, "..", "..");
const MAIL_DIR = path.join(ROOT, "var", "mail");
const FROM = process.env.MAIL_FROM || "Колхоз «Червонэ дышло» <noreply@localhost>";

/* Если SMTP настроен — письма уходят по-настоящему. Если нет (обычный случай при разработке),
   письмо складывается в var/mail/*.eml, а ссылка печатается в консоль. Никаких молчаливых потерь. */
let transport = null;
let realSmtp = false;
if(process.env.SMTP_HOST){
  transport = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: String(process.env.SMTP_SECURE || "false") === "true",
    auth: process.env.SMTP_USER ? {user:process.env.SMTP_USER, pass:process.env.SMTP_PASS} : undefined
  });
  realSmtp = true;
} else {
  fs.mkdirSync(MAIL_DIR, {recursive:true});
  transport = nodemailer.createTransport({streamTransport:true, newline:"unix", buffer:true});
}

async function send(to, subject, text, html){
  const info = await transport.sendMail({from:FROM, to, subject, text, html});
  if(!realSmtp){
    const file = path.join(MAIL_DIR, Date.now() + "-" + to.replace(/[^\w.@-]/g, "_") + ".eml");
    fs.writeFileSync(file, info.message);
    console.log("[почта] SMTP не настроен, письмо сохранено: " + file);
  }
  return info;
}
function letter(title, body, link, linkLabel){
  const text = title + "\n\n" + body + "\n\n" + linkLabel + ":\n" + link + "\n\nЕсли это были не вы, просто удалите письмо.";
  const html = '<div style="font-family:Georgia,serif;max-width:520px;color:#3b2614">' +
    '<h2 style="margin:0 0 8px">' + title + "</h2>" +
    "<p>" + body + "</p>" +
    '<p><a href="' + link + '" style="display:inline-block;padding:10px 18px;background:#e0ab3e;' +
    'border:3px solid #5f3d1c;border-radius:8px;color:#3b2614;text-decoration:none;font-weight:bold">' +
    linkLabel + "</a></p>" +
    '<p style="font-size:12px;color:#7a5a38">Если ссылка не нажимается, скопируйте её: ' + link + "</p>" +
    '<p style="font-size:12px;color:#7a5a38">Если это были не вы, просто удалите письмо.</p></div>';
  return {text, html};
}
/* Подтверждение идёт двумя путями сразу: код можно вписать в игре, не уходя
   с экрана, а ссылка выручает, когда почту открывают на другом устройстве.
   Что сработает первым, то и засчитается — строка в базе у них одна. */
async function sendVerify(to, link, code){
  const l = letter("Подтвердите почту",
    "Вы завели колхоз в игре «Червонэ дышло». Впишите в игре код <b>" + code +
    "</b> — или откройте ссылку ниже. И код, и ссылка живут сутки.",
    link, "Подтвердить почту");
  const text = "Подтвердите почту\n\nКод: " + code +
    "\n\nИли откройте ссылку:\n" + link +
    "\n\nИ код, и ссылка живут сутки. Если это были не вы, просто удалите письмо.";
  const html = l.html.replace("<p><a href=",
    '<p style="font:bold 30px/1.2 Georgia,serif;letter-spacing:6px;background:#fff3d4;' +
    'border:3px solid #5f3d1c;border-radius:8px;padding:12px 18px;display:inline-block">' +
    code + "</p><p><a href=");
  console.log("[почта] подтверждение для " + to + ": код " + code + ", ссылка " + link);
  return send(to, "Подтверждение почты — Червонэ дышло", text, html);
}
async function sendReset(to, link){
  const l = letter("Сброс пароля", "Кто-то запросил сброс пароля для вашего колхоза. Ссылка действует час.", link, "Задать новый пароль");
  console.log("[почта] сброс пароля для " + to + ": " + link);
  return send(to, "Сброс пароля — Червонэ дышло", l.text, l.html);
}
module.exports = {sendVerify, sendReset, realSmtp, MAIL_DIR};
