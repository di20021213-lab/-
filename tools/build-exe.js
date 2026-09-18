"use strict";
/* Собирает сервер вместе с базой и клиентом в один исполняемый файл.

   Внутрь попадают: код сервера, express и nodemailer, схема базы и клиентская
   страница со всей графикой. Ставить на машину ничего не нужно — ни Node,
   ни модулей. База создаётся рядом с файлом, в папке var.

   Запуск:  node tools/build-exe.js [win|linux|both]
   Итог:    dist/kolhoz-server.exe  и/или  dist/kolhoz-server
*/
const fs = require("fs");
const os = require("os");
const path = require("path");
const {execFileSync} = require("child_process");
const esbuild = require("esbuild");
const postject = require("postject");

const ROOT = path.join(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const BUILD = path.join(ROOT, "build");
const NODE_V = process.versions.node;
const target = (process.argv[2] || "both").toLowerCase();

fs.mkdirSync(DIST, {recursive:true});
fs.mkdirSync(BUILD, {recursive:true});

/* --- 1. клиент и схема как строки внутри сборки --- */
const clientPath = path.join(DIST, "client.html");
if(!fs.existsSync(clientPath)){
  console.log("сначала собираю клиента…");
  execFileSync(process.execPath, [path.join(__dirname, "build-standalone.js")], {stdio:"inherit"});
}
const entry = path.join(BUILD, "entry.js");
fs.writeFileSync(entry, [
  '"use strict";',
  "global.__SEA = true;",
  "global.__SCHEMA_SQL = " + JSON.stringify(fs.readFileSync(path.join(ROOT, "server/db/schema.sql"), "utf8")) + ";",
  "global.__CLIENT_HTML = " + JSON.stringify(fs.readFileSync(clientPath, "utf8")) + ";",
  'require(' + JSON.stringify(path.join(ROOT, "server/src/index.js")) + ");",
  ""
].join("\n"));

/* --- 2. всё в один js --- */
const bundleFile = path.join(BUILD, "server.bundle.js");
esbuild.buildSync({
  entryPoints:[entry], bundle:true, platform:"node", target:"node22",
  outfile:bundleFile, format:"cjs", legalComments:"none",
  external:["node:sqlite"], define:{"process.env.NODE_ENV":'"production"'}
});
console.log("сборка кода: " + (fs.statSync(bundleFile).size / 1048576).toFixed(2) + " МБ");

/* --- 3. заготовка для встраивания --- */
const seaCfg = path.join(BUILD, "sea-config.json");
const blob = path.join(BUILD, "sea-prep.blob");
fs.writeFileSync(seaCfg, JSON.stringify({
  main: bundleFile, output: blob, disableExperimentalSEAWarning: true, useSnapshot: false, useCodeCache: false
}, null, 2));
execFileSync(process.execPath, ["--experimental-sea-config", seaCfg], {stdio:"inherit"});

/* --- 4. берём чистый Node и вшиваем в него заготовку --- */
async function make(platform){
  const isWin = platform === "win";
  const out = path.join(DIST, isWin ? "kolhoz-server.exe" : "kolhoz-server");
  let base;
  if(isWin){
    base = path.join(BUILD, "node-" + NODE_V + ".exe");
    if(!fs.existsSync(base)){
      const url = "https://nodejs.org/dist/v" + NODE_V + "/win-x64/node.exe";
      console.log("качаю Node для Windows: " + url);
      execFileSync("curl", ["-sL", "-o", base, url]);
    }
  } else {
    base = path.join(BUILD, "node-" + NODE_V);
    if(!fs.existsSync(base)) fs.copyFileSync(process.execPath, base);
  }
  fs.copyFileSync(base, out);
  await postject.inject(out, "NODE_SEA_BLOB", fs.readFileSync(blob), {
    sentinelFuse: "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2"
  });
  if(!isWin) fs.chmodSync(out, 0o755);
  console.log((isWin ? "Windows: " : "Linux:   ") + out + " — " + (fs.statSync(out).size / 1048576).toFixed(0) + " МБ");
}

(async () => {
  if(target === "win" || target === "both") await make("win");
  if(target === "linux" || target === "both") await make("linux");
  console.log("\nГотово. Рядом с файлом появится папка var с базой при первом запуске.");
})();
