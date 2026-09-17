"use strict";
const {migrate, DB_PATH} = require("./db");
const v = migrate();
console.log("База готова: " + DB_PATH + " (версия схемы " + v + ")");
