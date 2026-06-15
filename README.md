# Капсулики Bot v1.3.1 — PostgreSQL + Redis

Telegram-бот-игра про капсулы, питомцев, коллекции, уход, экспедиции, обмены, донат через Telegram Stars и групповые события.

## Что сделано в v1.3.1

- PostgreSQL теперь основной режим для локального запуска и Railway.
- `DATABASE_URL` автоматически нормализуется:
  - `postgres://...` → `postgresql+psycopg://...`
  - `postgresql://...` → `postgresql+psycopg://...`
  - это убирает падение из-за отсутствующего `psycopg2`.
- Добавлены настройки пула БД:
  - `DB_POOL_SIZE`
  - `DB_MAX_OVERFLOW`
  - `DB_POOL_RECYCLE_SECONDS`
  - `DB_ECHO`
- `/api/health`, `/api/ready` и `/admin_health` показывают тип БД и драйвер.
- Добавлен `scripts/check_database.py` для быстрой проверки подключения и миграций.
- `.env.example` теперь настроен под локальный PostgreSQL + Redis из `docker-compose.yml`.
- `.env.sqlite.example` оставлен только как запасной режим для простого локального теста.
- Redis-слой из v1.3 сохранён: lock-и, rate-limit, защита от дублей и два события в группе.

## Что было сделано в v1.3

- Добавлен Redis-слой `app/redis_store.py`.
- Inline-кнопки сначала лимитятся через Redis, а при недоступном Redis откатываются на DB-лимитер.
- Добавлены distributed locks, чтобы при нескольких процессах/рестартах не плодились дубли событий.
- В одной группе может быть до двух активных событий: `catch` + `boss`.
- События одного типа не дублируются.
- Ручные команды `/spawn` и `/boss` защищены lock-ами.
- Клики по ловле и удару босса защищены lock-ом на конкретное событие.
- `docker-compose.yml` поднимает PostgreSQL + Redis.

## Структура

```text
app/
  bot.py             # Telegram bot handlers
  game.py            # игровая логика
  db.py              # SQLAlchemy engine/session/init/migrations
  config.py          # env-настройки + нормализация DATABASE_URL
  redis_store.py     # Redis locks/rate-limit helpers
  models.py          # SQLAlchemy models
  web.py             # /api/health и /api/ready
scripts/
  check_database.py  # проверка подключения к БД
static/
  index.html         # простая web-заглушка
```

## Локальный запуск через PostgreSQL + Redis

Из корня проекта:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
docker compose up -d postgres redis
python scripts/check_database.py
python -m app.main
```

На Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres redis
python scripts/check_database.py
python -m app.main
```

Минимальный `.env` для локального запуска:

```env
BOT_TOKEN=твой_токен_бота
ADMIN_IDS=твой_telegram_id
DATABASE_URL=postgresql+psycopg://capsuliki:capsuliki@localhost:5432/capsuliki
REDIS_URL=redis://localhost:6379/0
RUN_BOT_POLLING=true
GROUP_EVENTS_PER_GROUP=2
```

Проверка:

```text
http://localhost:8080/api/health
http://localhost:8080/api/ready
```

## Railway: как правильно связать Web + Postgres + Redis

На скрине у тебя уже есть три сервиса: `web`, `Postgres`, `Redis`. Теперь главное — в **web service** прописать переменные, которые ссылаются на соседние сервисы.

В Railway открой:

```text
web → Variables
```

Добавь или проверь:

```env
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=твой_telegram_id
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
RUN_BOT_POLLING=true
HOST=0.0.0.0
PORT=${{PORT}}
APP_SECRET=любой_длинный_секрет_32+_символа
REDIS_ENABLED=true
REDIS_REQUIRED=false
ENABLE_GROUP_EVENTS=true
GROUP_EVENTS_PER_GROUP=2
GROUP_EVENT_BATCH_SIZE=10
GROUP_EVENT_POLL_SECONDS=60
GROUP_EVENT_LOCK_SECONDS=120
GROUP_BOSS_INTERVAL_HOURS=24
STARS_ENABLED=true
STARS_CURRENCY=XTR
```

Если твой сервис базы в Railway называется не `Postgres`, а например `postgres` или `Capsuliki DB`, то reference надо писать с его точным именем:

```env
DATABASE_URL=${{ТОЧНОЕ_ИМЯ_СЕРВИСА_БД.DATABASE_URL}}
```

То же самое с Redis:

```env
REDIS_URL=${{ТОЧНОЕ_ИМЯ_REDIS.REDIS_URL}}
```

После изменения variables нажми redeploy у `web`.

## Как понять, что PostgreSQL реально подключился

Открой:

```text
https://твой-web-домен.up.railway.app/api/health
```

Должно быть примерно так:

```json
{
  "status": "ok",
  "service": "capsuliki-bot",
  "database": {
    "kind": "postgres",
    "driver": "postgresql+psycopg"
  },
  "redis": "ok"
}
```

Потом открой:

```text
https://твой-web-домен.up.railway.app/api/ready
```

Там уже проверяется реальный `SELECT 1` в БД. Если `ready`, значит Postgres живой и доступен из приложения.

В боте у админа также есть:

```text
/admin_health
```

## Важный момент про старую SQLite-базу

Этот архив не переносит данные из старого `capsuliki.db` в PostgreSQL автоматически. Если у тебя уже были реальные игроки в SQLite и их надо сохранить, сначала надо сделать отдельную миграцию данных. Если игроков пока не жалко — просто деплой с PostgreSQL и таблицы создадутся сами.

## Запуск только API без polling

Для диагностики можно временно выключить Telegram polling:

```env
RUN_BOT_POLLING=false
```

Тогда web-сервис стартует, `/api/health` и `/api/ready` будут работать, но бот не будет читать апдейты Telegram.

## Redis и два события

Главная настройка:

```env
GROUP_EVENTS_PER_GROUP=2
```

Как работает:

- в одной группе может быть активна ловля и босс одновременно;
- две ловли сразу не создаются;
- два босса сразу не создаются;
- Redis защищает спавн и клики от дублей;
- если Redis временно упал, бот продолжит работать в DB-only режиме;
- если хочешь жёстко требовать Redis для готовности сервиса, поставь `REDIS_REQUIRED=true`.

## Проверка проекта

```powershell
python -m compileall app scripts tests
python -m unittest discover -s tests -v
```

## Частые проблемы

### `/api/health` показывает `sqlite`

Значит `DATABASE_URL` не попал в `web` service. Проверь именно `web → Variables`, а не variables внутри Postgres.

### Ошибка `No module named psycopg2`

В этой версии исправлено: обычные Railway URL автоматически переводятся на `postgresql+psycopg://`. Если ошибка осталась, значит на Railway задеплоен старый архив.

### Redis показывает `disabled`

Значит `REDIS_URL` пустой или не попал в `web` service.

### Redis показывает `error`

Переменная есть, но приложение не может подключиться. Проверь reference `REDIS_URL=${{Redis.REDIS_URL}}` и redeploy.

### Бот не отвечает, но сайт живой

Проверь:

```env
RUN_BOT_POLLING=true
BOT_TOKEN=реальный_токен
```

И убедись, что этот же бот не запущен где-то ещё вторым polling-процессом. Telegram polling такого не любит, он начинает капризничать как принцесса на горошине.
