# Капсулики Bot v0.2 — питомцы с картинками

**Капсулики** — Telegram-бот-игра про капсулы, коллекцию питомцев, уход, экспедиции, обмены и групповые события.

В этой версии я уже вшил поддержку **10 картинок питомцев**. Когда игрок открывает капсулу или ловит питомца в групповом событии, бот отправляет **сообщение с картинкой питомца**.

---

## Что уже умеет бот

### Личное

```text
/start
/menu
/open
/my
/pet
/setfav PET_ID
/expedition
/finish
/top
```

### Обмен

```text
/trade @username PET_ID
/accepttrade ID
```

### Группы

```text
/spawn  # админ проекта, спавн редкого капсулика
/boss   # админ проекта, спавн босса
```

### Админ

```text
/admin_stats
```

---

## Куда класть картинки питомцев

Папка внутри проекта:

```text
app/assets/pets/
```

Бот ищет файлы с именами:

```text
pet1.png
pet2.png
pet3.png
pet4.png
pet5.png
pet6.png
pet7.png
pet8.png
pet9.png
pet10.png
```

Поддерживаются и такие форматы:

```text
.png
.jpg
.jpeg
.webp
```

То есть можно, например, положить `pet1.png`, `pet2.png`, `pet3.webp` — бот найдёт их сам.

---

## Какой файл какому питомцу соответствует

| Файл | Питомец | Редкость |
|---|---|---|
| pet1 | Сапфирис | rare |
| pet2 | Листопанцирь | common |
| pet3 | Розалотль | uncommon |
| pet4 | Неонорик | uncommon |
| pet5 | Полярикс | rare |
| pet6 | Пиродрак | legendary |
| pet7 | Лунорог | epic |
| pet8 | Аметис | epic |
| pet9 | Солярис | legendary |
| pet10 | Созвезай | mythic |

---

## Что именно сделано

- каждому из 10 питомцев назначен свой файл изображения;
- при `/open` бот присылает **картинку питомца + подпись**;
- при ловле питомца в групповом событии бот тоже присылает **картинку + подпись**;
- при `/pet` и кнопке **Любимчик** бот показывает карточку питомца тоже с его картинкой;
- если файла нет, бот не падает, а просто отправляет обычный текст.

---

## Запуск локально Windows PowerShell

```powershell
cd capsuliki_bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m app.main
```

В `.env` укажи минимум:

```env
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=твой_telegram_id
```

Если хочешь запуск только API без Telegram polling:

```env
RUN_BOT_POLLING=false
```

Проверка health:

```text
http://localhost:8080/api/health
http://localhost:8080/api/ready
```

---

## PostgreSQL локально

```powershell
docker compose up -d postgres
```

И в `.env`:

```env
DATABASE_URL=postgresql+psycopg://capsuliki:capsuliki@localhost:5432/capsuliki
```

---

## Railway

Env для Railway:

```env
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=твой_telegram_id
DATABASE_URL=${{Postgres.DATABASE_URL}}
RUN_BOT_POLLING=true
APP_SECRET=любой_длинный_секрет_32+_символа
ENABLE_GROUP_EVENTS=true
```

---

## Проверка проекта

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
```

---

## Что можно сделать дальше

- красивые PNG-карточки редкости;
- анимацию открытия капсулы;
- отдельные баннеры для mythic/legendary;
- инвентарь с кнопками листания;
- магазин капсул и донатные капсулы;
- альбом/питомник с прогрессом по коллекции.
