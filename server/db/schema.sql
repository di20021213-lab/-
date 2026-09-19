-- Колхоз «Червонэ дышло» — схема базы.
-- Диалект: SQLite. Переезд на PostgreSQL: INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL PRIMARY KEY,
-- INTEGER-время (epoch ms) -> BIGINT, REAL -> NUMERIC(12,2), остальное переносится без правок.

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------ аккаунты
CREATE TABLE IF NOT EXISTS users (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  email           TEXT    NOT NULL,                    -- хранится в нижнем регистре
  password_hash   TEXT    NOT NULL,                    -- scrypt$N$r$p$соль$хеш
  nick            TEXT    NOT NULL,
  status          TEXT    NOT NULL DEFAULT 'active',   -- active | blocked
  email_verified_at INTEGER,                           -- NULL = почта не подтверждена
  created_at      INTEGER NOT NULL,
  last_login_at   INTEGER,
  CHECK (status IN ('active','blocked')),
  CHECK (length(email) BETWEEN 3 AND 254)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(email);

-- Письма с одноразовыми ссылками: подтверждение почты и сброс пароля.
-- В базе лежит только SHA-256 токена, сам токен уходит письмом и больше нигде не хранится.
CREATE TABLE IF NOT EXISTS email_tokens (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        TEXT    NOT NULL,                        -- verify | reset
  token_hash  TEXT    NOT NULL,
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL,
  used_at     INTEGER,
  CHECK (kind IN ('verify','reset'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_email_tokens_hash ON email_tokens(token_hash);
CREATE INDEX IF NOT EXISTS ix_email_tokens_user ON email_tokens(user_id, kind);

-- Сессии: в куке лежит токен, в базе — его хеш. Разлогинить можно с сервера.
CREATE TABLE IF NOT EXISTS sessions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT    NOT NULL,
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL,
  revoked_at  INTEGER,
  user_agent  TEXT,
  ip          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

-- Ограничитель частоты: и на вход, и на отправку писем.
CREATE TABLE IF NOT EXISTS rate_limits (
  bucket      TEXT    NOT NULL,                        -- 'login:user@mail', 'verify:1.2.3.4'
  window_at   INTEGER NOT NULL,
  hits        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket)
);

-- ------------------------------------------------------------------- хозяйство
CREATE TABLE IF NOT EXISTS farms (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          TEXT    NOT NULL DEFAULT 'Червонэ дышло',
  silver        INTEGER NOT NULL DEFAULT 500,
  gems          REAL    NOT NULL DEFAULT 0,
  xp            INTEGER NOT NULL DEFAULT 0,
  level         INTEGER NOT NULL DEFAULT 1,
  energy        INTEGER NOT NULL DEFAULT 33,
  energy_at     INTEGER NOT NULL,
  dog           INTEGER NOT NULL DEFAULT 60,
  cat           INTEGER NOT NULL DEFAULT 60,
  pet_at        INTEGER NOT NULL,
  quest_index   INTEGER NOT NULL DEFAULT 0,
  boost_until   INTEGER NOT NULL DEFAULT 0,
  vympel_until  INTEGER NOT NULL DEFAULT 0,
  helper_at     INTEGER NOT NULL DEFAULT 0,
  daily_date    TEXT,
  daily_streak  INTEGER NOT NULL DEFAULT 0,
  daily_opened  INTEGER NOT NULL DEFAULT 0,
  daily_picked  INTEGER NOT NULL DEFAULT -1,
  bailout_day   TEXT,                                  -- когда правление в последний раз выдавало подъёмные
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  CHECK (silver >= 0 AND gems >= 0 AND energy >= 0 AND level >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_farms_user ON farms(user_id);
CREATE INDEX IF NOT EXISTS ix_farms_rank ON farms(level DESC, xp DESC);

CREATE TABLE IF NOT EXISTS buildings (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  farm_id   INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  kind      TEXT    NOT NULL,                          -- kury | ogorod | gusi | ...
  level     INTEGER NOT NULL DEFAULT 1,
  CHECK (level BETWEEN 1 AND 4)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_buildings ON buildings(farm_id, kind);

-- Занятое место: курица на насесте, картошка на грядке.
CREATE TABLE IF NOT EXISTS slots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  building_id   INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
  breed         TEXT    NOT NULL,                      -- id породы или сорта
  seasons_left  INTEGER NOT NULL,
  fed           INTEGER NOT NULL DEFAULT 0,
  ready_at      INTEGER NOT NULL DEFAULT 0,            -- epoch ms, когда созреет
  feed_id       TEXT    NOT NULL DEFAULT 'low',
  created_at    INTEGER NOT NULL,
  CHECK (seasons_left >= 0 AND fed IN (0,1))
);
CREATE INDEX IF NOT EXISTS ix_slots_building ON slots(building_id);
CREATE INDEX IF NOT EXISTS ix_slots_ready ON slots(ready_at) WHERE fed = 1;

-- Корма, ресурсы, подарки, бонусы — одной таблицей, различаются видом.
CREATE TABLE IF NOT EXISTS inventory (
  farm_id  INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  kind     TEXT    NOT NULL,                           -- feed | res | gift | item
  item_id  TEXT    NOT NULL,
  qty      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (farm_id, kind, item_id),
  CHECK (qty >= 0),
  CHECK (kind IN ('feed','res','gift','item'))
);

-- Склад продукции по постройкам: сколько единиц и на сколько серебра.
CREATE TABLE IF NOT EXISTS products (
  farm_id  INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  house    TEXT    NOT NULL,
  units    INTEGER NOT NULL DEFAULT 0,
  value    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (farm_id, house),
  CHECK (units >= 0 AND value >= 0)
);

CREATE TABLE IF NOT EXISTS decor (
  farm_id   INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  decor_id  TEXT    NOT NULL,
  bought_at INTEGER NOT NULL,
  PRIMARY KEY (farm_id, decor_id)
);

CREATE TABLE IF NOT EXISTS helpers (
  farm_id   INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  helper_id TEXT    NOT NULL,
  hired_at  INTEGER NOT NULL,
  PRIMARY KEY (farm_id, helper_id)
);

-- Счётчики для заданий: сколько раз покормил, сколько собрал и так далее.
CREATE TABLE IF NOT EXISTS counters (
  farm_id  INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  key      TEXT    NOT NULL,
  value    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (farm_id, key)
);

-- Кому сегодня уже помогали (соседи пока неигровые, но помощь раз в сутки).
CREATE TABLE IF NOT EXISTS friend_help (
  farm_id     INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  friend_idx  INTEGER NOT NULL,
  day         TEXT    NOT NULL,
  PRIMARY KEY (farm_id, friend_idx, day)
);

-- План сдачи государству: три заказа на продукцию, дают серебро и почти весь опыт.
CREATE TABLE IF NOT EXISTS contracts (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  farm_id   INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  house     TEXT    NOT NULL,
  need      INTEGER NOT NULL,
  silver    INTEGER NOT NULL,
  xp        INTEGER NOT NULL,
  gems      INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  CHECK (need > 0)
);
CREATE INDEX IF NOT EXISTS ix_contracts_farm ON contracts(farm_id);

-- Журнал действий: и отладка, и материал для ловли накрутчиков.
CREATE TABLE IF NOT EXISTS events (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  farm_id  INTEGER REFERENCES farms(id) ON DELETE CASCADE,
  at       INTEGER NOT NULL,
  type     TEXT    NOT NULL,
  payload  TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_farm ON events(farm_id, at DESC);

-- Таблица рекордов для вкладки TOP 100.
CREATE VIEW IF NOT EXISTS leaderboard AS
SELECT
  f.id                          AS farm_id,
  u.nick                        AS nick,
  f.name                        AS farm,
  f.level                       AS level,
  f.xp                          AS xp,
  f.level * 1000 + f.xp         AS score
FROM farms f
JOIN users u ON u.id = f.user_id
WHERE u.status = 'active'
ORDER BY score DESC;

CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', '1');
