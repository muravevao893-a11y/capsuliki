from __future__ import annotations

import json
import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import database_status
from app.models import ActionLog, AppConfig, ErrorLog, EventStatus, Expedition, GroupChat, GroupEvent, Pet, Player, Rarity, StarPurchase, Trade, TradeStatus, utcnow


RARITY_META: dict[str, dict[str, Any]] = {
    Rarity.COMMON.value: {"name": "обычный", "emoji": "⚪", "weight": 560, "xp": 8},
    Rarity.UNCOMMON.value: {"name": "необычный", "emoji": "🟢", "weight": 260, "xp": 14},
    Rarity.RARE.value: {"name": "редкий", "emoji": "🔵", "weight": 120, "xp": 24},
    Rarity.EPIC.value: {"name": "эпический", "emoji": "🟣", "weight": 45, "xp": 45},
    Rarity.LEGENDARY.value: {"name": "легендарный", "emoji": "🟡", "weight": 13, "xp": 90},
    Rarity.MYTHIC.value: {"name": "мифический", "emoji": "🔴", "weight": 2, "xp": 180},
}

RARITY_ORDER = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]

CAPSULE_TYPES: dict[str, dict[str, Any]] = {
    "daily": {
        "name": "🎁 Ежедневная капсула",
        "cost": None,
        "weights": {"common": 560, "uncommon": 260, "rare": 120, "epic": 45, "legendary": 13, "mythic": 2},
        "description": "бесплатная капсула раз в 20 часов",
    },
    "common": {
        "name": "⚪ Обычная капсула",
        "cost": {"coins": 100},
        "weights": {"common": 640, "uncommon": 250, "rare": 85, "epic": 22, "legendary": 3, "mythic": 0},
        "description": "дешёвая капсула для добора коллекции",
    },
    "rare": {
        "name": "🔵 Редкая капсула",
        "cost": {"crystals": 15},
        "weights": {"common": 0, "uncommon": 0, "rare": 730, "epic": 220, "legendary": 45, "mythic": 5},
        "description": "гарантирует редкого или выше",
    },
    "epic": {
        "name": "🟣 Эпическая капсула",
        "cost": {"crystals": 45},
        "weights": {"common": 0, "uncommon": 0, "rare": 0, "epic": 820, "legendary": 160, "mythic": 20},
        "description": "гарантирует эпического или выше",
    },
    "legendary": {
        "name": "🟡 Легендарная капсула",
        "cost": {"dust": 600},
        "weights": {"common": 0, "uncommon": 0, "rare": 0, "epic": 0, "legendary": 930, "mythic": 70},
        "description": "легендарная капсула за пыль дубликатов",
    },
}

DUPLICATE_DUST: dict[str, int] = {
    "common": 8,
    "uncommon": 14,
    "rare": 28,
    "epic": 70,
    "legendary": 180,
    "mythic": 500,
}

CONFIG_KEYS: dict[str, dict[str, Any]] = {
    "maintenance_mode": {"type": "bool", "default": "false", "title": "Maintenance mode"},
    "free_open_daily_limit": {"type": "int", "default": "1", "title": "Free opens per day"},
    "paid_open_daily_limit": {"type": "int", "default": "8", "title": "Paid opens per day"},
    "care_daily_limit": {"type": "int", "default": "20", "title": "Care actions per day"},
    "expedition_daily_limit": {"type": "int", "default": "5", "title": "Expeditions per day"},
    "group_catch_daily_limit": {"type": "int", "default": "10", "title": "Group catches per day"},
    "group_event_interval_minutes": {"type": "int", "default": "45", "title": "Group event interval"},
    "group_event_batch_size": {"type": "int", "default": "10", "title": "Groups per event tick"},
    "group_events_per_group": {"type": "int", "default": "2", "title": "Max active event types per group"},
    "group_boss_interval_hours": {"type": "int", "default": "24", "title": "Boss cooldown hours"},
}




SPECIES: list[dict[str, Any]] = [
    {"key": "murkos", "emoji": "🦊", "name": "Сапфирис", "element": "небо", "rarity": "rare", "image": "pet1", "skill": "чаще приносит кристаллы из небесных мест", "chars": ["сияющий", "быстрый", "любопытный"]},
    {"key": "zhabkin", "emoji": "🐢", "name": "Листопанцирь", "element": "лес", "rarity": "common", "image": "pet2", "skill": "лучше ищет монеты в спокойных экспедициях", "chars": ["мудрый", "добрый", "неторопливый"]},
    {"key": "pakostnik", "emoji": "🦎", "name": "Розалотль", "element": "вода", "rarity": "uncommon", "image": "pet3", "skill": "быстрее восстанавливает настроение", "chars": ["нежный", "весёлый", "игривый"]},
    {"key": "pingviboss", "emoji": "🦝", "name": "Неонорик", "element": "неон", "rarity": "uncommon", "image": "pet4", "skill": "может найти лишнюю капсулу", "chars": ["хитрый", "шустрый", "дерзкий"]},
    {"key": "ognelis", "emoji": "🐧", "name": "Полярикс", "element": "север", "rarity": "rare", "image": "pet5", "skill": "лучше ходит в холодные экспедиции", "chars": ["смелый", "яркий", "деловой"]},
    {"key": "bronecherep", "emoji": "🐉", "name": "Пиродрак", "element": "огонь", "rarity": "legendary", "image": "pet6", "skill": "сильнее в вулкане", "chars": ["гордый", "пылкий", "опасно милый"]},
    {"key": "saharorog", "emoji": "🦌", "name": "Лунорог", "element": "луна", "rarity": "epic", "image": "pet7", "skill": "улучшает настроение коллекции", "chars": ["нежный", "волшебный", "тихий"]},
    {"key": "dymodragon", "emoji": "🦉", "name": "Аметис", "element": "кристалл", "rarity": "epic", "image": "pet8", "skill": "даёт повышенный шанс кристаллов", "chars": ["мудрый", "сияющий", "спокойный"]},
    {"key": "cosmozay", "emoji": "🦁", "name": "Солярис", "element": "солнце", "rarity": "legendary", "image": "pet9", "skill": "лучше проходит героические вылазки", "chars": ["лидер", "смелый", "харизматичный"]},
    {"key": "mifokit", "emoji": "🐰", "name": "Созвезай", "element": "космос", "rarity": "mythic", "image": "pet10", "skill": "редко приносит мифическую капсулу", "chars": ["волшебный", "быстрый", "сияющий"]},
    {"key": "iskrohvost", "emoji": "🐿️", "name": "Искрохвост", "element": "молния", "rarity": "common", "image": "pet11", "skill": "чуть быстрее возвращается из коротких экспедиций", "chars": ["живой", "прыгучий", "шумный"]},
    {"key": "medokryl", "emoji": "🐝", "name": "Медокрыл", "element": "луг", "rarity": "common", "image": "pet12", "skill": "чаще приносит монеты из леса", "chars": ["трудолюбивый", "милый", "звонкий"]},
    {"key": "tumanush", "emoji": "🐭", "name": "Тумануш", "element": "туман", "rarity": "common", "image": "pet13", "skill": "лучше прячется от усталости", "chars": ["тихий", "осторожный", "сонный"]},
    {"key": "kaplyusha", "emoji": "🐸", "name": "Каплюша", "element": "дождь", "rarity": "common", "image": "pet14", "skill": "быстрее восстанавливает чистоту", "chars": ["добрый", "мокрый", "забавный"]},
    {"key": "peskolap", "emoji": "🦔", "name": "Песколап", "element": "песок", "rarity": "common", "image": "pet15", "skill": "стабильно находит мелкие награды", "chars": ["упрямый", "надёжный", "колючий"]},
    {"key": "yantarik", "emoji": "🐹", "name": "Янтарик", "element": "янтарь", "rarity": "uncommon", "image": "pet16", "skill": "может сохранить часть энергии после ухода", "chars": ["тёплый", "ласковый", "бережливый"]},
    {"key": "snezhmord", "emoji": "🦭", "name": "Снежморд", "element": "лёд", "rarity": "uncommon", "image": "pet17", "skill": "лучше проходит северные вылазки", "chars": ["пухлый", "весёлый", "морозный"]},
    {"key": "bambukot", "emoji": "🐼", "name": "Бамбукот", "element": "бамбук", "rarity": "uncommon", "image": "pet18", "skill": "медленнее теряет настроение", "chars": ["ленивый", "мирный", "сильный"]},
    {"key": "iskroryb", "emoji": "🐟", "name": "Искрорыб", "element": "река", "rarity": "uncommon", "image": "pet19", "skill": "чаще приносит кристаллы из воды", "chars": ["быстрый", "скользкий", "яркий"]},
    {"key": "shoroh", "emoji": "🦇", "name": "Шорох", "element": "ночь", "rarity": "uncommon", "image": "pet20", "skill": "лучше ищет редкие вещи ночью", "chars": ["скрытный", "умный", "резкий"]},
    {"key": "gromik", "emoji": "🐺", "name": "Громик", "element": "гроза", "rarity": "rare", "image": "pet21", "skill": "добавляет силу в опасных экспедициях", "chars": ["верный", "грозный", "смелый"]},
    {"key": "rubinor", "emoji": "🦜", "name": "Рубинор", "element": "рубин", "rarity": "rare", "image": "pet22", "skill": "чаще приносит пыль капсул", "chars": ["громкий", "красивый", "самоуверенный"]},
    {"key": "glazur", "emoji": "🐱", "name": "Глазур", "element": "звезда", "rarity": "rare", "image": "pet23", "skill": "может дать бонус к очкам сезона", "chars": ["изящный", "хитрый", "сияющий"]},
    {"key": "vetrun", "emoji": "🦅", "name": "Ветрун", "element": "ветер", "rarity": "rare", "image": "pet24", "skill": "ускоряет дальние экспедиции", "chars": ["свободный", "гордый", "меткий"]},
    {"key": "korallik", "emoji": "🐬", "name": "Кораллик", "element": "коралл", "rarity": "rare", "image": "pet25", "skill": "лучше находит награды на пляже", "chars": ["добрый", "умный", "морской"]},
    {"key": "noctiris", "emoji": "🦊", "name": "Ноктирис", "element": "сумрак", "rarity": "epic", "image": "pet26", "skill": "повышает шанс редкой находки", "chars": ["таинственный", "быстрый", "лукавый"]},
    {"key": "kristalisk", "emoji": "🦎", "name": "Кристалиск", "element": "кристалл", "rarity": "epic", "image": "pet27", "skill": "приносит больше кристаллов", "chars": ["острый", "сияющий", "хладнокровный"]},
    {"key": "aurapuh", "emoji": "🦄", "name": "Аурапух", "element": "аура", "rarity": "epic", "image": "pet28", "skill": "улучшает настроение любимчика", "chars": ["нежный", "редкий", "магический"]},
    {"key": "plazmokot", "emoji": "🐈\u200d⬛", "name": "Плазмокот", "element": "плазма", "rarity": "epic", "image": "pet29", "skill": "усиливает награды за события", "chars": ["дерзкий", "быстрый", "искристый"]},
    {"key": "vulkash", "emoji": "🐲", "name": "Вулкаш", "element": "лава", "rarity": "legendary", "image": "pet30", "skill": "значительно сильнее в вулкане", "chars": ["горячий", "смелый", "упрямый"]},
    {"key": "nebulion", "emoji": "🦁", "name": "Небулион", "element": "туманность", "rarity": "legendary", "image": "pet31", "skill": "даёт большой бонус к сезонным очкам", "chars": ["царственный", "космический", "спокойный"]},
    {"key": "zlatokryl", "emoji": "🦚", "name": "Златокрыл", "element": "золото", "rarity": "legendary", "image": "pet32", "skill": "может принести много монет", "chars": ["гордый", "богатый", "яркий"]},
    {"key": "tenemir", "emoji": "🐺", "name": "Тенемир", "element": "тень", "rarity": "legendary", "image": "pet33", "skill": "лучше проходит рискованные вылазки", "chars": ["молчаливый", "опасный", "верный"]},
    {"key": "astralot", "emoji": "🐉", "name": "Астралот", "element": "астрал", "rarity": "mythic", "image": "pet34", "skill": "редко приносит легендарную капсулу", "chars": ["древний", "сияющий", "мудрый"]},
    {"key": "hronozay", "emoji": "🐇", "name": "Хронозай", "element": "время", "rarity": "mythic", "image": "pet35", "skill": "иногда сокращает ожидание наград", "chars": ["быстрый", "странный", "милый"]},
    {"key": "efiril", "emoji": "🦋", "name": "Эфирил", "element": "эфир", "rarity": "mythic", "image": "pet36", "skill": "даёт шанс на мифическую находку", "chars": ["лёгкий", "волшебный", "невесомый"]},
]

SPECIES_BY_KEY: dict[str, dict[str, Any]] = {item["key"]: item for item in SPECIES}

CURRENT_SEASON: dict[str, Any] = {
    "key": "moon_01",
    "name": "🌙 Сезон Луны",
    "description": "Первый тестовый сезон Капсуликов.",
    "days": 30,
}

STAR_PRODUCTS: dict[str, dict[str, Any]] = {
    "support_15": {
        "title": "⭐ Малый набор",
        "description": "30 кристаллов, 120 пыли и 120 очков сезона.",
        "stars": 15,
        "reward": {"coins": 0, "crystals": 30, "dust": 120, "season_score": 120},
    },
    "rare_pack_35": {
        "title": "🔵 Редкий набор",
        "description": "80 кристаллов, 320 пыли и 300 очков сезона.",
        "stars": 35,
        "reward": {"coins": 300, "crystals": 80, "dust": 320, "season_score": 300},
    },
    "epic_pack_75": {
        "title": "🟣 Эпический набор",
        "description": "180 кристаллов, 850 пыли и 850 очков сезона.",
        "stars": 75,
        "reward": {"coins": 700, "crystals": 180, "dust": 850, "season_score": 850},
    },
    "legend_pack_149": {
        "title": "🟡 Легендарный набор",
        "description": "400 кристаллов, 1800 пыли и 2000 очков сезона.",
        "stars": 149,
        "reward": {"coins": 1500, "crystals": 400, "dust": 1800, "season_score": 2000},
    },
}


EXPEDITIONS: dict[str, dict[str, Any]] = {
    "forest": {"name": "🌲 Лес", "minutes": 60, "min_power": 8, "coins": (20, 50), "crystals": (0, 1)},
    "beach": {"name": "🏖 Пляж", "minutes": 90, "min_power": 14, "coins": (35, 70), "crystals": (0, 2)},
    "volcano": {"name": "🌋 Вулкан", "minutes": 120, "min_power": 28, "coins": (55, 110), "crystals": (1, 3)},
    "ruins": {"name": "🏰 Руины", "minutes": 150, "min_power": 38, "coins": (70, 140), "crystals": (1, 4)},
    "space": {"name": "🌌 Космос", "minutes": 180, "min_power": 50, "coins": (100, 190), "crystals": (2, 6)},
}

CARE_ACTIONS: dict[str, dict[str, Any]] = {
    "feed": {"name": "🍖 Покормить", "field": "hunger", "delta": 18, "cost": 5, "xp": 4},
    "play": {"name": "🎮 Поиграть", "field": "mood", "delta": 16, "cost": 0, "xp": 4, "energy": -8},
    "wash": {"name": "🧼 Помыть", "field": "clean", "delta": 20, "cost": 3, "xp": 3},
    "train": {"name": "🏋️ Тренировать", "field": "power", "delta": 2, "cost": 10, "xp": 8, "energy": -12},
    "sleep": {"name": "💤 Уложить", "field": "energy", "delta": 28, "cost": 0, "xp": 2},
}

BOSS_POOL = [
    {"emoji": "🐲", "name": "Дракон из автомата", "hp": 120},
    {"emoji": "🦖", "name": "Пылезавр", "hp": 150},
    {"emoji": "👾", "name": "Глитч-Монстр", "hp": 180},
]


def aware(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def hname(player: Player) -> str:
    if player.username:
        return f"@{player.username}"
    return player.first_name or "Игрок"


def log(db: Session, player_id: int | None, chat_id: int | None, action: str, text: str = "") -> None:
    db.add(ActionLog(player_id=player_id, chat_id=chat_id, action=action, text=text[:2000]))



def add_season_score(player: Player, amount: int) -> None:
    if amount <= 0:
        return
    player.season_score = int(getattr(player, "season_score", 0) or 0) + int(amount)




def get_config_value(db: Session, key: str, default: Any = None) -> str:
    item = db.get(AppConfig, key)
    if item:
        return item.value
    meta = CONFIG_KEYS.get(key)
    if meta:
        return str(meta["default"])
    return str(default) if default is not None else ""


def get_config_int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_config_value(db, key, default))
    except Exception:
        return int(default)


def get_config_bool(db: Session, key: str, default: bool = False) -> bool:
    raw = str(get_config_value(db, key, "true" if default else "false")).strip().lower()
    return raw in {"1", "true", "yes", "on", "да"}


def set_config_value(db: Session, key: str, value: str) -> tuple[bool, str]:
    if key not in CONFIG_KEYS:
        return False, "Неизвестный ключ конфига."
    meta = CONFIG_KEYS[key]
    value = str(value).strip()
    if meta["type"] == "int":
        try:
            parsed = int(value)
        except ValueError:
            return False, "Нужно целое число."
        if parsed < 0:
            return False, "Значение не может быть меньше 0."
        value = str(parsed)
    elif meta["type"] == "bool":
        value = "true" if value.lower() in {"1", "true", "yes", "on", "да"} else "false"

    item = db.get(AppConfig, key)
    if not item:
        item = AppConfig(key=key, value=value)
        db.add(item)
    else:
        item.value = value
        item.updated_at = utcnow()
    db.flush()
    return True, f"{key} = {value}"


def admin_config_payload(db: Session) -> list[dict[str, Any]]:
    result = []
    for key, meta in CONFIG_KEYS.items():
        result.append({
            "key": key,
            "title": meta["title"],
            "type": meta["type"],
            "value": get_config_value(db, key, meta["default"]),
            "default": meta["default"],
        })
    return result


def is_banned_player(player: Player | None) -> bool:
    return bool(player and int(getattr(player, "is_banned", 0) or 0) == 1)


def banned_message(player: Player) -> str:
    reason = (getattr(player, "ban_reason", None) or "без причины").strip()
    return f"Аккаунт заблокирован. Причина: {reason}"


def require_not_banned(player: Player) -> tuple[bool, str]:
    if is_banned_player(player):
        return False, banned_message(player)
    return True, ""


def _action_count_today(db: Session, player: Player, action: str | None = None, prefix: str | None = None) -> int:
    q = select(func.count(ActionLog.id)).where(ActionLog.player_id == player.id, ActionLog.created_at >= day_start_utc())
    if action:
        q = q.where(ActionLog.action == action)
    if prefix:
        q = q.where(ActionLog.action.like(f"{prefix}%"))
    return int(db.scalar(q) or 0)



def open_action_name(capsule_type: str) -> str:
    return "open_daily" if capsule_type == "daily" else "open_paid"


def player_limits_payload(db: Session, player: Player) -> dict[str, Any]:
    settings = get_settings()
    return {
        "free_open": {
            "used": _action_count_today(db, player, "open_daily"),
            "limit": get_config_int(db, "free_open_daily_limit", settings.free_open_daily_limit),
        },
        "paid_open": {
            "used": _action_count_today(db, player, "open_paid"),
            "limit": get_config_int(db, "paid_open_daily_limit", settings.paid_open_daily_limit),
        },
        "care": {
            "used": _action_count_today(db, player, prefix="care_"),
            "limit": get_config_int(db, "care_daily_limit", settings.care_daily_limit),
        },
        "expedition": {
            "used": _action_count_today(db, player, "expedition_start"),
            "limit": get_config_int(db, "expedition_daily_limit", settings.expedition_daily_limit),
        },
        "group_catch": {
            "used": _action_count_today(db, player, "group_catch"),
            "limit": get_config_int(db, "group_catch_daily_limit", settings.group_catch_daily_limit),
        },
        "last_daily_open_at": aware(player.last_open_at).isoformat() if aware(player.last_open_at) else "",
        "next_daily_open_at": (aware(player.last_open_at) + timedelta(hours=20)).isoformat() if aware(player.last_open_at) else "",
    }



def check_daily_limit(db: Session, player: Player, action: str | None, limit: int, prefix: str | None = None) -> tuple[bool, str]:
    if limit <= 0:
        return True, ""
    used = _action_count_today(db, player, action=action, prefix=prefix)
    if used >= limit:
        return False, f"Дневной лимит исчерпан: {used}/{limit}."
    return True, ""


def ban_player(db: Session, telegram_user_id: int, reason: str = "") -> tuple[bool, str]:
    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    if not player:
        return False, "Игрок не найден."
    player.is_banned = 1
    player.ban_reason = reason or "без причины"
    player.banned_at = utcnow()
    log(db, player.id, None, "admin_ban", player.ban_reason)
    db.flush()
    return True, f"Игрок {hname(player)} заблокирован."


def unban_player(db: Session, telegram_user_id: int) -> tuple[bool, str]:
    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    if not player:
        return False, "Игрок не найден."
    player.is_banned = 0
    player.ban_reason = None
    player.banned_at = None
    log(db, player.id, None, "admin_unban", "")
    db.flush()
    return True, f"Игрок {hname(player)} разблокирован."


def banned_players_payload(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.scalars(select(Player).where(Player.is_banned == 1).order_by(desc(Player.banned_at)).limit(limit)).all()
    return [
        {
            "telegram_user_id": p.telegram_user_id,
            "username": p.username,
            "name": hname(p),
            "reason": p.ban_reason or "",
            "banned_at": p.banned_at.isoformat() if p.banned_at else "",
        }
        for p in rows
    ]


def clear_errors(db: Session) -> int:
    count = int(db.scalar(select(func.count(ErrorLog.id))) or 0)
    db.query(ErrorLog).delete()
    db.flush()
    return count


def last_actions_payload(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.scalars(select(ActionLog).order_by(desc(ActionLog.created_at)).limit(limit)).all()
    return [
        {
            "id": item.id,
            "player_id": item.player_id,
            "chat_id": item.chat_id,
            "action": item.action,
            "text": item.text,
            "created_at": item.created_at.isoformat(),
        }
        for item in rows
    ]


def admin_health_payload(db: Session) -> dict[str, Any]:
    settings = get_settings()
    return {
        "database": "ok",
        "database_info": database_status(),
        "maintenance": bool(settings.maintenance_mode),
        "players": int(db.scalar(select(func.count(Player.id))) or 0),
        "banned": int(db.scalar(select(func.count(Player.id)).where(Player.is_banned == 1)) or 0),
        "errors": int(db.scalar(select(func.count(ErrorLog.id))) or 0),
        "active_events": int(db.scalar(select(func.count(GroupEvent.id)).where(GroupEvent.status == EventStatus.ACTIVE.value)) or 0),
        "stars_enabled": bool(settings.stars_enabled),
        "config": {item["key"]: item["value"] for item in admin_config_payload(db)},
    }


def backup_payload(db: Session) -> dict[str, Any]:
    def rows_for(model, limit: int | None = None):
        q = select(model)
        if limit:
            q = q.limit(limit)
        rows = db.scalars(q).all()
        result = []
        for row in rows:
            item = {}
            for col in row.__table__.columns:
                value = getattr(row, col.name)
                if isinstance(value, datetime):
                    value = value.isoformat()
                item[col.name] = value
            result.append(item)
        return result

    return {
        "created_at": utcnow().isoformat(),
        "schema": "1.0",
        "players": rows_for(Player),
        "pets": rows_for(Pet),
        "groups": rows_for(GroupChat),
        "events": rows_for(GroupEvent),
        "trades": rows_for(Trade),
        "purchases": rows_for(StarPurchase),
        "actions_tail": rows_for(ActionLog, limit=500),
    }


def log_error(
    db: Session,
    source: str,
    error: BaseException | str,
    traceback_text: str | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
    update_json: str | None = None,
) -> ErrorLog:
    if isinstance(error, BaseException):
        error_type = error.__class__.__name__
        message = str(error) or error_type
    else:
        error_type = "Error"
        message = str(error)
    item = ErrorLog(
        source=str(source or "bot")[:80],
        error_type=error_type[:160],
        message=message[:4000],
        traceback_text=(traceback_text or "")[:12000] or None,
        chat_id=chat_id,
        user_id=user_id,
        update_json=(update_json or "")[:12000] or None,
    )
    db.add(item)
    db.flush()
    return item


def admin_errors_payload(db: Session, limit: int = 12) -> list[dict[str, Any]]:
    rows = db.scalars(select(ErrorLog).order_by(desc(ErrorLog.created_at)).limit(limit)).all()
    return [
        {
            "id": item.id,
            "source": item.source,
            "type": item.error_type,
            "message": item.message,
            "chat_id": item.chat_id,
            "user_id": item.user_id,
            "created_at": item.created_at.isoformat(),
        }
        for item in rows
    ]


def register_group_chat(db: Session, chat_id: int, title: str | None, player: Player | None = None) -> GroupChat:
    group = db.scalar(select(GroupChat).where(GroupChat.chat_id == chat_id))
    if not group:
        group = GroupChat(chat_id=chat_id, title=title or "Чат", last_activity_at=utcnow())
        db.add(group)
        db.flush()
    else:
        group.title = title or group.title
        group.last_activity_at = utcnow()
    group.messages_seen += 1
    if player:
        seen = db.scalar(
            select(ActionLog.id)
            .where(ActionLog.chat_id == chat_id, ActionLog.player_id == player.id, ActionLog.action == "group_seen")
            .limit(1)
        )
        if not seen:
            group.players_seen += 1
            log(db, player.id, chat_id, "group_seen", "player seen in group")
    return group


def group_chats_for_events(db: Session, limit: int = 10, min_minutes: int = 45) -> list[GroupChat]:
    cutoff = utcnow() - timedelta(minutes=max(5, min_minutes))
    return db.scalars(
        select(GroupChat)
        .where(
            GroupChat.status == "active",
            GroupChat.last_activity_at.is_not(None),
            (GroupChat.last_event_at.is_(None) | (GroupChat.last_event_at <= cutoff)),
        )
        .order_by(GroupChat.last_event_at.asc().nullsfirst())
        .limit(limit)
    ).all()


def mark_group_event_sent(group: GroupChat) -> None:
    group.last_event_at = utcnow()


def button_rate_limited(db: Session, chat_id: int, player: Player, action: str, seconds: int = 2) -> tuple[bool, int]:
    since = utcnow() - timedelta(seconds=max(1, seconds))
    row = db.scalar(
        select(ActionLog)
        .where(
            ActionLog.chat_id == chat_id,
            ActionLog.player_id == player.id,
            ActionLog.action == action,
            ActionLog.created_at >= since,
        )
        .order_by(desc(ActionLog.created_at))
        .limit(1)
    )
    if row:
        left = max(1, int(((aware(row.created_at) + timedelta(seconds=seconds)) - utcnow()).total_seconds()) + 1)
        return True, left
    log(db, player.id, chat_id, action, "rate marker")
    db.flush()
    return False, 0


def profile_payload(db: Session, player: Player) -> dict[str, Any]:
    pets = db.scalars(select(Pet).where(Pet.owner_player_id == player.id)).all()
    favorite = favorite_pet(db, player)
    rarest = None
    rarity_rank = {name: idx for idx, name in enumerate(RARITY_ORDER)}
    for pet in pets:
        if rarest is None or rarity_rank.get(pet.rarity, 0) > rarity_rank.get(rarest.rarity, 0):
            rarest = pet
    return {
        "name": hname(player),
        "level": player.level,
        "xp": player.xp,
        "coins": player.coins,
        "crystals": player.crystals,
        "dust": int(getattr(player, "capsule_dust", 0) or 0),
        "capsules_opened": player.capsules_opened,
        "pets_total": len(pets),
        "collection_total": len(SPECIES),
        "favorite": pet_payload(favorite) if favorite else None,
        "rarest": pet_payload(rarest) if rarest else None,
    }


def group_registry_payload(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.scalars(select(GroupChat).order_by(desc(GroupChat.last_activity_at)).limit(limit)).all()
    return [
        {
            "chat_id": item.chat_id,
            "title": item.title,
            "status": item.status,
            "players_seen": item.players_seen,
            "messages_seen": item.messages_seen,
            "last_activity_at": item.last_activity_at.isoformat() if item.last_activity_at else "",
            "last_event_at": item.last_event_at.isoformat() if item.last_event_at else "",
        }
        for item in rows
    ]


def get_or_create_player(db: Session, telegram_user_id: int, username: str | None, first_name: str | None) -> tuple[Player, bool]:
    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    created = False
    if not player:
        player = Player(telegram_user_id=telegram_user_id, username=username, first_name=first_name or "Игрок")
        db.add(player)
        db.flush()
        created = True
    else:
        player.username = username
        player.first_name = first_name or player.first_name
        player.updated_at = utcnow()
    return player, created


def rarity_name(rarity: str) -> str:
    meta = RARITY_META.get(rarity, RARITY_META["common"])
    return f"{meta['emoji']} {meta['name']}"


def choose_rarity(capsule_type: str = "daily", player: Player | None = None) -> str:
    capsule = CAPSULE_TYPES.get(capsule_type, CAPSULE_TYPES["daily"])
    weights_map = dict(capsule["weights"])

    # Pity-система для ежедневной капсулы: игрок не должен слишком долго видеть только мусор.
    if capsule_type == "daily" and player is not None:
        next_open = int(player.capsules_opened or 0) + 1
        min_rarity = None
        if next_open % 80 == 0:
            min_rarity = "epic"
        elif next_open % 30 == 0:
            min_rarity = "rare"
        elif next_open % 10 == 0:
            min_rarity = "uncommon"
        if min_rarity:
            min_index = RARITY_ORDER.index(min_rarity)
            for rarity in RARITY_ORDER[:min_index]:
                weights_map[rarity] = 0

    values = list(RARITY_META.keys())
    weights = [int(weights_map.get(item, RARITY_META[item]["weight"])) for item in values]
    if sum(weights) <= 0:
        weights = [RARITY_META[item]["weight"] for item in values]
    return random.choices(values, weights=weights, k=1)[0]


def choose_species(rarity: str | None = None) -> dict[str, Any]:
    if rarity is None:
        rarity = choose_rarity()
    candidates = [s for s in SPECIES if s["rarity"] == rarity]
    if not candidates:
        candidates = SPECIES
    return random.choice(candidates)


def _pet_level_from_xp(xp: int) -> int:
    return max(1, min(100, int((xp / 80) ** 0.5) + 1))



def capsule_cost_text(capsule_type: str) -> str:
    capsule = CAPSULE_TYPES.get(capsule_type, CAPSULE_TYPES["daily"])
    cost = capsule.get("cost")
    if not cost:
        return "бесплатно"
    parts = []
    if cost.get("coins"):
        parts.append(f"{cost['coins']} монет")
    if cost.get("crystals"):
        parts.append(f"{cost['crystals']} кристаллов")
    if cost.get("dust"):
        parts.append(f"{cost['dust']} пыли")
    return ", ".join(parts) or "бесплатно"


def can_pay_capsule(player: Player, capsule_type: str) -> tuple[bool, str]:
    capsule = CAPSULE_TYPES.get(capsule_type)
    if not capsule:
        return False, "Такой капсулы нет."
    cost = capsule.get("cost")
    if not cost:
        return True, ""
    if player.coins < int(cost.get("coins", 0)):
        return False, f"Нужно {cost['coins']} монет. У тебя {player.coins}."
    if player.crystals < int(cost.get("crystals", 0)):
        return False, f"Нужно {cost['crystals']} кристаллов. У тебя {player.crystals}."
    if int(getattr(player, "capsule_dust", 0) or 0) < int(cost.get("dust", 0)):
        return False, f"Нужно {cost['dust']} пыли капсул. У тебя {getattr(player, 'capsule_dust', 0) or 0}."
    return True, ""


def pay_capsule(player: Player, capsule_type: str) -> None:
    cost = CAPSULE_TYPES.get(capsule_type, {}).get("cost")
    if not cost:
        return
    player.coins -= int(cost.get("coins", 0))
    player.crystals -= int(cost.get("crystals", 0))
    player.capsule_dust = int(getattr(player, "capsule_dust", 0) or 0) - int(cost.get("dust", 0))


def capsule_drop_chance(capsule_type: str, rarity: str) -> str:
    weights = CAPSULE_TYPES.get(capsule_type, CAPSULE_TYPES["daily"])["weights"]
    total = sum(int(v) for v in weights.values())
    if total <= 0:
        return "?"
    value = int(weights.get(rarity, 0))
    if value <= 0:
        return "pity"
    chance = value / total * 100
    if chance >= 10:
        return f"{chance:.0f}%"
    if chance >= 1:
        return f"{chance:.1f}%"
    return f"{chance:.2f}%"


def player_has_species(db: Session, player: Player, species_key: str) -> bool:
    return bool(db.scalar(select(Pet.id).where(Pet.owner_player_id == player.id, Pet.species_key == species_key).limit(1)))


def shop_payload(player: Player) -> dict[str, Any]:
    return {
        "coins": player.coins,
        "crystals": player.crystals,
        "dust": int(getattr(player, "capsule_dust", 0) or 0),
        "capsules": [
            {
                "key": key,
                "name": spec["name"],
                "cost": capsule_cost_text(key),
                "description": spec["description"],
            }
            for key, spec in CAPSULE_TYPES.items()
            if key != "daily"
        ],
    }


def album_payload(db: Session, player: Player, page: int = 0) -> dict[str, Any]:
    pets = db.scalars(select(Pet).where(Pet.owner_player_id == player.id).order_by(desc(Pet.obtained_at))).all()
    total = len(pets)
    if total == 0:
        return {"total": 0, "page": 0, "pet": None}
    page = max(0, min(page, total - 1))
    return {
        "total": total,
        "page": page,
        "pet": pet_payload(pets[page]),
    }


def create_pet_from_species(db: Session, owner: Player, species: dict[str, Any]) -> Pet:
    rarity = species["rarity"]
    base_power = {"common": 8, "uncommon": 13, "rare": 21, "epic": 34, "legendary": 55, "mythic": 88}.get(rarity, 8)
    pet = Pet(
        owner_player_id=owner.id,
        species_key=species["key"],
        emoji=species["emoji"],
        name=species["name"],
        rarity=rarity,
        element=species["element"],
        character=random.choice(species["chars"]),
        skill=species["skill"],
        power=base_power + random.randint(0, 8),
    )
    db.add(pet)
    db.flush()
    if not owner.favorite_pet_id:
        owner.favorite_pet_id = pet.id
    return pet


def open_capsule(db: Session, player: Player, force: bool = False, capsule_type: str = "daily") -> tuple[bool, str, Pet | None]:
    capsule_type = (capsule_type or "daily").strip().lower()
    if capsule_type not in CAPSULE_TYPES:
        return False, "Такой капсулы нет.", None

    ok_ban, ban_text = require_not_banned(player)
    if not ok_ban and not force:
        return False, ban_text, None

    now = utcnow()
    last = aware(player.last_open_at)

    # Ежедневная капсула ограничена для всех, включая админа.
    # Обычные /open и кнопки НЕ передают force=True.
    if capsule_type == "daily" and last and not force and now < last + timedelta(hours=20):
        left_seconds = int(((last + timedelta(hours=20)) - now).total_seconds())
        left_hours = max(1, left_seconds // 3600 + (1 if left_seconds % 3600 else 0))
        return False, f"Ежедневная капсула уже открыта. Осталось примерно {left_hours} ч.", None

    settings = get_settings()
    if not force:
        if capsule_type == "daily":
            limit = get_config_int(db, "free_open_daily_limit", settings.free_open_daily_limit)
            action = "open_daily"
        else:
            limit = get_config_int(db, "paid_open_daily_limit", settings.paid_open_daily_limit)
            action = "open_paid"
        ok_limit, limit_text = check_daily_limit(db, player, action, limit)
        if not ok_limit:
            return False, limit_text, None

    ok, reason = can_pay_capsule(player, capsule_type)
    if not ok and not force:
        return False, reason, None

    if not force:
        pay_capsule(player, capsule_type)

    rarity = choose_rarity(capsule_type, player)
    species = choose_species(rarity)
    duplicate = player_has_species(db, player, species["key"])
    pet = create_pet_from_species(db, player, species)

    player.capsules_opened += 1
    if capsule_type == "daily":
        player.last_open_at = now
        player.daily_streak += 1

    xp = int(RARITY_META[rarity]["xp"])
    player.xp += xp
    player.coins += 15 + xp
    player.level = max(player.level, _pet_level_from_xp(player.xp))

    duplicate_text = ""
    if duplicate:
        dust = int(DUPLICATE_DUST.get(rarity, 8))
        player.capsule_dust = int(getattr(player, "capsule_dust", 0) or 0) + dust
        pet.xp += dust
        pet.power += max(1, dust // 10)
        duplicate_text = f"\n\n🔁 Дубликат! Питомец усилен, получено <b>{dust}</b> пыли капсул."

    chance = capsule_drop_chance(capsule_type, rarity)
    capsule_name = CAPSULE_TYPES[capsule_type]["name"]
    add_season_score(player, {"common": 3, "uncommon": 5, "rare": 10, "epic": 25, "legendary": 70, "mythic": 180}.get(rarity, 3))
    log(db, player.id, None, "open_capsule", f"{capsule_type}:{hname(player)} получил {pet.emoji} {pet.name}")
    log(db, player.id, None, open_action_name(capsule_type), capsule_type)
    db.flush()

    setattr(pet, "_drop_chance", chance)
    setattr(pet, "_drop_title", CAPSULE_TYPES[capsule_type]["name"])
    headline = {
        "mythic": "🔴 МИФИЧЕСКИЙ ПИТОМЕЦ!",
        "legendary": "🟡 ЛЕГЕНДАРНЫЙ ПИТОМЕЦ!",
        "epic": "🟣 ЭПИЧЕСКИЙ ПИТОМЕЦ!",
    }.get(rarity, "🎁 Капсула открыта!")
    text = (
        f"{headline}\n\n"
        f"Капсула: <b>{capsule_name}</b>\n"
        f"Выпал: <b>{pet.emoji} {pet.name}</b>\n"
        f"Редкость: <b>{rarity_name(pet.rarity)}</b>\n"
        f"Шанс: <b>{chance}</b>\n"
        f"Стихия: <b>{pet.element}</b>\n"
        f"Характер: <b>{pet.character}</b>\n"
        f"Сила: <b>{pet.power}</b>\n"
        f"Навык: <b>{species['skill']}</b>"
        f"{duplicate_text}"
    )
    return True, text, pet


def collection_payload(db: Session, player: Player) -> dict[str, Any]:
    pets = db.scalars(select(Pet).where(Pet.owner_player_id == player.id).order_by(desc(Pet.obtained_at))).all()
    rarity_counts = {key: 0 for key in RARITY_META}
    for pet in pets:
        rarity_counts[pet.rarity] = rarity_counts.get(pet.rarity, 0) + 1
    favorite = db.get(Pet, player.favorite_pet_id) if player.favorite_pet_id else (pets[0] if pets else None)
    return {
        "player": {
            "name": hname(player),
            "coins": player.coins,
            "crystals": player.crystals,
            "dust": int(getattr(player, "capsule_dust", 0) or 0),
            "level": player.level,
            "xp": player.xp,
            "streak": player.daily_streak,
            "opened": player.capsules_opened,
        },
        "total": len(pets),
        "rarity_counts": rarity_counts,
        "favorite": pet_payload(favorite) if favorite else None,
        "recent": [pet_payload(pet) for pet in pets[:8]],
    }


def pet_payload(pet: Pet | None) -> dict[str, Any] | None:
    if not pet:
        return None
    species = SPECIES_BY_KEY.get(pet.species_key, {})
    return {
        "id": pet.id,
        "title": f"{pet.emoji} {pet.nickname or pet.name}",
        "name": pet.nickname or pet.name,
        "base_name": pet.name,
        "emoji": pet.emoji,
        "rarity": pet.rarity,
        "rarity_name": rarity_name(pet.rarity),
        "element": pet.element,
        "character": pet.character,
        "skill": pet.skill,
        "level": pet.level,
        "xp": pet.xp,
        "power": pet.power,
        "hunger": pet.hunger,
        "mood": pet.mood,
        "clean": pet.clean,
        "energy": pet.energy,
        "species_key": pet.species_key,
        "image_key": species.get("image"),
        "drop_chance": getattr(pet, "_drop_chance", None),
        "drop_title": getattr(pet, "_drop_title", None),
    }


def pet_owner_payload(db: Session, pet: Pet | None) -> dict[str, Any] | None:
    if not pet:
        return None
    owner = db.get(Player, pet.owner_player_id)
    payload = pet_payload(pet)
    if not payload:
        return None
    payload["owner"] = {
        "id": owner.id if owner else None,
        "name": hname(owner) if owner else "неизвестно",
        "telegram_user_id": owner.telegram_user_id if owner else None,
    }
    return payload


def pet_info_payload(db: Session, pet_id: int) -> dict[str, Any] | None:
    pet = db.get(Pet, pet_id)
    return pet_owner_payload(db, pet)


def player_pets_payload(db: Session, player: Player, limit: int = 30) -> dict[str, Any]:
    pets = db.scalars(
        select(Pet)
        .where(Pet.owner_player_id == player.id)
        .order_by(desc(Pet.obtained_at))
        .limit(limit)
    ).all()
    return {
        "owner": hname(player),
        "total": int(db.scalar(select(func.count(Pet.id)).where(Pet.owner_player_id == player.id)) or 0),
        "items": [pet_payload(pet) for pet in pets],
    }


def pet_owner_name(db: Session, pet_id: int) -> str | None:
    pet = db.get(Pet, pet_id)
    if not pet:
        return None
    owner = db.get(Player, pet.owner_player_id)
    return hname(owner) if owner else "неизвестно"



def favorite_pet(db: Session, player: Player) -> Pet | None:
    if player.favorite_pet_id:
        pet = db.get(Pet, player.favorite_pet_id)
        if pet and pet.owner_player_id == player.id:
            return pet
    return db.scalar(select(Pet).where(Pet.owner_player_id == player.id).order_by(desc(Pet.obtained_at)))


def set_favorite(db: Session, player: Player, pet_id: int) -> tuple[bool, str]:
    pet = db.get(Pet, pet_id)
    if not pet or pet.owner_player_id != player.id:
        return False, "Такого питомца у тебя нет."
    player.favorite_pet_id = pet.id
    return True, f"Любимчик выбран: {pet.emoji} {pet.nickname or pet.name}."


def care_pet(db: Session, player: Player, action: str, pet_id: int | None = None) -> tuple[bool, str, dict[str, Any] | None]:
    ok_ban, ban_text = require_not_banned(player)
    if not ok_ban:
        return False, ban_text, None
    ok_limit, limit_text = check_daily_limit(db, player, None, get_config_int(db, "care_daily_limit", get_settings().care_daily_limit), prefix="care_")
    if not ok_limit:
        return False, limit_text, None
    spec = CARE_ACTIONS.get(action)
    if not spec:
        return False, "Такого ухода нет.", None
    pet = db.get(Pet, pet_id) if pet_id else favorite_pet(db, player)
    if not pet:
        return False, "Сначала получи питомца через /open.", None
    if pet.owner_player_id != player.id:
        return False, "Это не твой питомец.", None
    cost = int(spec.get("cost", 0))
    if player.coins < cost:
        return False, f"Нужно {cost} монет. У тебя {player.coins}.", pet_payload(pet)
    player.coins -= cost
    field = spec["field"]
    delta = int(spec["delta"])
    if field == "power":
        pet.power += delta
    else:
        setattr(pet, field, max(0, min(100, int(getattr(pet, field)) + delta)))
    if spec.get("energy"):
        pet.energy = max(0, min(100, pet.energy + int(spec["energy"])))
    pet.xp += int(spec.get("xp", 0))
    old_level = pet.level
    pet.level = _pet_level_from_xp(pet.xp)
    player.xp += int(spec.get("xp", 0))
    player.level = _pet_level_from_xp(player.xp)
    log(db, player.id, None, f"care_{action}", f"{hname(player)} ухаживает за {pet.name}")
    db.flush()
    lvl = " Уровень вырос!" if pet.level > old_level else ""
    return True, f"{spec['name']}: {pet.emoji} {pet.nickname or pet.name} доволен.{lvl}", pet_payload(pet)


def expedition_payload() -> dict[str, Any]:
    return {"locations": [{"key": k, **v} for k, v in EXPEDITIONS.items()]}


def active_expedition(db: Session, player: Player) -> Expedition | None:
    return db.scalar(select(Expedition).where(Expedition.player_id == player.id, Expedition.status == "active").order_by(desc(Expedition.started_at)))


def start_expedition(db: Session, player: Player, location_key: str, pet_id: int | None = None) -> tuple[bool, str, Expedition | None]:
    ok_ban, ban_text = require_not_banned(player)
    if not ok_ban:
        return False, ban_text, None
    ok_limit, limit_text = check_daily_limit(db, player, "expedition_start", get_config_int(db, "expedition_daily_limit", get_settings().expedition_daily_limit))
    if not ok_limit:
        return False, limit_text, None
    loc = EXPEDITIONS.get(location_key)
    if not loc:
        return False, "Такой экспедиции нет.", None
    if active_expedition(db, player):
        return False, "Одна экспедиция уже идёт. Дождись возвращения.", None
    pet = db.get(Pet, pet_id) if pet_id else favorite_pet(db, player)
    if not pet:
        return False, "Сначала получи питомца через /open.", None
    if pet.owner_player_id != player.id:
        return False, "Это не твой питомец.", None
    if pet.energy < 20:
        return False, f"{pet.emoji} {pet.name} устал. Уложи его спать.", None
    if pet.power < int(loc["min_power"]):
        return False, f"Нужна сила {loc['min_power']}. У питомца {pet.power}.", None
    pet.energy = max(0, pet.energy - 18)
    exp = Expedition(
        player_id=player.id,
        pet_id=pet.id,
        location_key=location_key,
        finishes_at=utcnow() + timedelta(minutes=int(loc["minutes"])),
    )
    db.add(exp)
    log(db, player.id, None, "expedition_start", f"{pet.name} ушёл в {loc['name']}")
    db.flush()
    return True, f"{pet.emoji} {pet.nickname or pet.name} отправился в {loc['name']}. Вернётся через {loc['minutes']} мин.", exp


def finish_expedition(db: Session, player: Player) -> tuple[bool, str]:
    exp = active_expedition(db, player)
    if not exp:
        return False, "Активной экспедиции нет."
    now = utcnow()
    if now < aware(exp.finishes_at):
        left = int((aware(exp.finishes_at) - now).total_seconds() // 60) + 1
        return False, f"Экспедиция ещё идёт. Осталось {left} мин."
    pet = db.get(Pet, exp.pet_id)
    loc = EXPEDITIONS[exp.location_key]
    coins = random.randint(*loc["coins"])
    crystals = random.randint(*loc["crystals"])
    bonus = 0
    found_capsule = False
    if pet:
        pet.xp += 18
        pet.level = _pet_level_from_xp(pet.xp)
        pet.hunger = max(0, pet.hunger - 10)
        pet.mood = min(100, pet.mood + 5)
        if pet.rarity in {"legendary", "mythic"}:
            crystals += 1
        if "капсулу" in pet.skill and random.random() < 0.12:
            found_capsule = True
        bonus = pet.level
    player.coins += coins + bonus
    player.crystals += crystals
    player.xp += 16
    exp.status = "finished"
    exp.result_json = json.dumps({"coins": coins + bonus, "crystals": crystals, "capsule": found_capsule}, ensure_ascii=False)
    if found_capsule:
        create_pet_from_species(db, player, choose_species(choose_rarity()))
    add_season_score(player, 8)
    log(db, player.id, None, "expedition_finish", f"Экспедиция принесла {coins + bonus} монет")
    db.flush()
    extra = "\n🎁 Питомец нашёл ещё одну капсулу!" if found_capsule else ""
    return True, f"🎒 Экспедиция завершена!\n\nМонеты: <b>{coins + bonus}</b>\nКристаллы: <b>{crystals}</b>{extra}"


def leaderboard(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    pet_count = func.count(Pet.id)
    rows = db.execute(
        select(Player, pet_count.label("pets"))
        .outerjoin(Pet, Pet.owner_player_id == Player.id)
        .group_by(Player.id)
        .order_by(desc(pet_count), desc(Player.level), desc(Player.crystals))
        .limit(limit)
    ).all()
    return [{"name": hname(p), "pets": int(c or 0), "level": p.level, "crystals": p.crystals} for p, c in rows]


def propose_trade(db: Session, proposer: Player, target: Player, offer_pet_id: int, want_pet_id: int | None = None) -> tuple[bool, str, Trade | None]:
    if proposer.id == target.id:
        return False, "Сам с собой обменяться нельзя.", None
    offer = db.get(Pet, offer_pet_id)
    if not offer or offer.owner_player_id != proposer.id:
        return False, "Питомец для обмена не найден.", None
    want = db.get(Pet, want_pet_id) if want_pet_id else None
    if want_pet_id and (not want or want.owner_player_id != target.id):
        return False, "Желаемый питомец у второго игрока не найден.", None
    trade = Trade(proposer_player_id=proposer.id, target_player_id=target.id, offer_pet_id=offer_pet_id, want_pet_id=want_pet_id)
    db.add(trade)
    db.flush()
    return True, f"Обмен создан: {offer.emoji} {offer.name}. Второй игрок может принять через /accepttrade {trade.id}", trade


def accept_trade(db: Session, player: Player, trade_id: int) -> tuple[bool, str]:
    trade = db.get(Trade, trade_id)
    if not trade or trade.status != TradeStatus.PENDING.value:
        return False, "Обмен не найден или уже закрыт."
    if trade.target_player_id != player.id:
        return False, "Этот обмен не тебе."
    offer = db.get(Pet, trade.offer_pet_id)
    want = db.get(Pet, trade.want_pet_id) if trade.want_pet_id else None
    if not offer or offer.owner_player_id != trade.proposer_player_id:
        trade.status = TradeStatus.CANCELLED.value
        return False, "Питомец больше недоступен."
    if want and want.owner_player_id != trade.target_player_id:
        trade.status = TradeStatus.CANCELLED.value
        return False, "Второй питомец больше недоступен."
    offer.owner_player_id = trade.target_player_id
    if want:
        want.owner_player_id = trade.proposer_player_id
    trade.status = TradeStatus.ACCEPTED.value
    db.flush()
    return True, "Обмен завершён."


def expire_old_group_events(db: Session, chat_id: int | None = None) -> int:
    now = utcnow()
    q = select(GroupEvent).where(
        GroupEvent.status == EventStatus.ACTIVE.value,
        GroupEvent.finishes_at.is_not(None),
        GroupEvent.finishes_at <= now,
    )
    if chat_id is not None:
        q = q.where(GroupEvent.chat_id == chat_id)
    events = db.scalars(q).all()
    for event in events:
        event.status = EventStatus.FINISHED.value
    if events:
        db.flush()
    return len(events)


def active_group_event(db: Session, chat_id: int, event_type: str | None = None) -> GroupEvent | None:
    expire_old_group_events(db, chat_id)
    q = select(GroupEvent).where(GroupEvent.chat_id == chat_id, GroupEvent.status == EventStatus.ACTIVE.value)
    if event_type:
        q = q.where(GroupEvent.event_type == event_type)
    return db.scalar(q.order_by(desc(GroupEvent.created_at)))


def last_group_event_at(db: Session, chat_id: int, event_type: str) -> datetime | None:
    event = db.scalar(
        select(GroupEvent)
        .where(GroupEvent.chat_id == chat_id, GroupEvent.event_type == event_type)
        .order_by(desc(GroupEvent.created_at))
        .limit(1)
    )
    return aware(event.created_at) if event else None


def spawn_catch_event(db: Session, chat_id: int, chat_title: str) -> GroupEvent:
    rarity = random.choice(["rare", "epic", "legendary"])
    species = choose_species(rarity)
    data = {"species": species, "rarity": rarity, "caught_by": None}
    event = GroupEvent(chat_id=chat_id, chat_title=chat_title or "Чат", event_type="catch", data_json=json.dumps(data, ensure_ascii=False), finishes_at=utcnow() + timedelta(minutes=10))
    db.add(event)
    db.flush()
    return event


def catch_group_pet(db: Session, chat_id: int, player: Player, event_id: int) -> tuple[bool, str, Pet | None]:
    ok_ban, ban_text = require_not_banned(player)
    if not ok_ban:
        return False, ban_text, None
    ok_limit, limit_text = check_daily_limit(db, player, "group_catch", get_config_int(db, "group_catch_daily_limit", get_settings().group_catch_daily_limit))
    if not ok_limit:
        return False, limit_text, None
    event = db.get(GroupEvent, event_id)
    if not event or event.chat_id != chat_id or event.status != EventStatus.ACTIVE.value or event.event_type != "catch":
        return False, "Капсулик уже убежал.", None
    data = json.loads(event.data_json or "{}")
    attempts = data.get("attempts") or []
    if player.telegram_user_id in attempts:
        return False, "Ты уже пробовал поймать этого капсулика.", None
    attempts.append(player.telegram_user_id)
    data["attempts"] = attempts
    event.data_json = json.dumps(data, ensure_ascii=False)
    chance = 45 + min(35, player.level * 2)
    if random.randint(1, 100) <= chance:
        species = data["species"]
        pet = create_pet_from_species(db, player, species)
        event.status = EventStatus.FINISHED.value
        data["caught_by"] = player.telegram_user_id
        event.data_json = json.dumps(data, ensure_ascii=False)
        add_season_score(player, 20)
        log(db, player.id, chat_id, "group_catch", f"{hname(player)} поймал {pet.name}")
        db.flush()
        return True, f"✨ {hname(player)} поймал {pet.emoji} <b>{pet.name}</b>!\nРедкость: <b>{rarity_name(pet.rarity)}</b>", pet
    log(db, player.id, chat_id, "group_catch_fail", f"{hname(player)} не поймал капсулика")
    return False, f"💨 {hname(player)} почти поймал, но капсулик выскользнул.", None


def spawn_boss_event(db: Session, chat_id: int, chat_title: str) -> GroupEvent:
    boss = random.choice(BOSS_POOL)
    data = {"boss": boss, "hp": boss["hp"], "max_hp": boss["hp"], "hits": {}}
    event = GroupEvent(chat_id=chat_id, chat_title=chat_title or "Чат", event_type="boss", data_json=json.dumps(data, ensure_ascii=False), finishes_at=utcnow() + timedelta(hours=6))
    db.add(event)
    db.flush()
    return event


def hit_boss(db: Session, chat_id: int, player: Player, event_id: int) -> tuple[bool, str, dict[str, Any] | None]:
    event = db.get(GroupEvent, event_id)
    if not event or event.chat_id != chat_id or event.status != EventStatus.ACTIVE.value or event.event_type != "boss":
        return False, "Босс уже ушёл.", None
    data = json.loads(event.data_json or "{}")
    hits = data.get("hits") or {}
    if str(player.id) in hits:
        return False, "Ты уже ударил босса. Ждём остальных.", data
    pet = favorite_pet(db, player)
    dmg = random.randint(8, 18) + (pet.power // 5 if pet else player.level)
    hits[str(player.id)] = dmg
    data["hits"] = hits
    data["hp"] = max(0, int(data["hp"]) - dmg)
    text = f"⚔️ {hname(player)} нанёс <b>{dmg}</b> урона."
    if data["hp"] <= 0:
        event.status = EventStatus.FINISHED.value
        reward = 60 + len(hits) * 10
        player.coins += reward
        player.crystals += 1
        text += f"\n\n🏆 Босс побеждён! Участники получают награды. Тебе: {reward} монет и 1 кристалл."
    event.data_json = json.dumps(data, ensure_ascii=False)
    db.flush()
    return True, text, data


def day_start_utc() -> datetime:
    now = utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _has_action_today(db: Session, player: Player, action: str | None = None, prefix: str | None = None) -> bool:
    q = select(ActionLog.id).where(ActionLog.player_id == player.id, ActionLog.created_at >= day_start_utc())
    if action:
        q = q.where(ActionLog.action == action)
    if prefix:
        q = q.where(ActionLog.action.like(f"{prefix}%"))
    return bool(db.scalar(q.limit(1)))


def _claimed_today(db: Session, player: Player, action: str) -> bool:
    return _has_action_today(db, player, action=action)


def quest_payload(db: Session, player: Player) -> dict[str, Any]:
    quests = [
        {
            "key": "open",
            "title": "Открой 1 капсулу",
            "done": _has_action_today(db, player, action="open_capsule"),
            "claimed": _claimed_today(db, player, "quest_claim_open"),
            "reward": "50 монет",
        },
        {
            "key": "care",
            "title": "Позаботься о питомце",
            "done": _has_action_today(db, player, prefix="care_"),
            "claimed": _claimed_today(db, player, "quest_claim_care"),
            "reward": "20 монет",
        },
        {
            "key": "expedition",
            "title": "Отправь питомца в экспедицию",
            "done": _has_action_today(db, player, action="expedition_start"),
            "claimed": _claimed_today(db, player, "quest_claim_expedition"),
            "reward": "1 кристалл",
        },
        {
            "key": "catch",
            "title": "Поймай капсулика в группе",
            "done": _has_action_today(db, player, action="group_catch"),
            "claimed": _claimed_today(db, player, "quest_claim_catch"),
            "reward": "30 пыли",
        },
    ]
    return {
        "coins": player.coins,
        "crystals": player.crystals,
        "dust": int(getattr(player, "capsule_dust", 0) or 0),
        "quests": quests,
    }


def claim_quests(db: Session, player: Player) -> tuple[bool, str, dict[str, Any]]:
    payload = quest_payload(db, player)
    rewards = {"coins": 0, "crystals": 0, "dust": 0}
    claimed = []
    for quest in payload["quests"]:
        if not quest["done"] or quest["claimed"]:
            continue
        key = quest["key"]
        if key == "open":
            rewards["coins"] += 50
        elif key == "care":
            rewards["coins"] += 20
        elif key == "expedition":
            rewards["crystals"] += 1
        elif key == "catch":
            rewards["dust"] += 30
        claimed.append(key)
        log(db, player.id, None, f"quest_claim_{key}", "daily quest reward")
    if not claimed:
        return False, "Нет новых наград по заданиям.", payload

    player.coins += rewards["coins"]
    player.crystals += rewards["crystals"]
    player.capsule_dust = int(getattr(player, "capsule_dust", 0) or 0) + rewards["dust"]
    add_season_score(player, len(claimed) * 4)
    db.flush()
    parts = []
    if rewards["coins"]:
        parts.append(f"{rewards['coins']} монет")
    if rewards["crystals"]:
        parts.append(f"{rewards['crystals']} кристалл")
    if rewards["dust"]:
        parts.append(f"{rewards['dust']} пыли")
    return True, "Получено: " + ", ".join(parts), quest_payload(db, player)


def daily_reward_payload(db: Session, player: Player) -> dict[str, Any]:
    claimed = _claimed_today(db, player, "daily_reward")
    streak = max(1, int(player.daily_streak or 1))
    day = ((streak - 1) % 7) + 1
    rewards = {
        1: {"coins": 100, "crystals": 0, "dust": 0, "title": "День 1"},
        2: {"coins": 130, "crystals": 0, "dust": 0, "title": "День 2"},
        3: {"coins": 160, "crystals": 2, "dust": 0, "title": "День 3"},
        4: {"coins": 190, "crystals": 2, "dust": 15, "title": "День 4"},
        5: {"coins": 220, "crystals": 3, "dust": 20, "title": "День 5"},
        6: {"coins": 260, "crystals": 4, "dust": 35, "title": "День 6"},
        7: {"coins": 350, "crystals": 8, "dust": 80, "title": "День 7"},
    }
    return {
        "claimed": claimed,
        "streak": streak,
        "day": day,
        "reward": rewards[day],
    }


def claim_daily_reward(db: Session, player: Player) -> tuple[bool, str, dict[str, Any]]:
    payload = daily_reward_payload(db, player)
    if payload["claimed"]:
        return False, "Ежедневная награда уже забрана.", payload
    reward = payload["reward"]
    player.coins += int(reward["coins"])
    player.crystals += int(reward["crystals"])
    player.capsule_dust = int(getattr(player, "capsule_dust", 0) or 0) + int(reward["dust"])
    add_season_score(player, 5)
    log(db, player.id, None, "daily_reward", f"daily reward day {payload['day']}")
    db.flush()
    parts = [f"{reward['coins']} монет"]
    if reward["crystals"]:
        parts.append(f"{reward['crystals']} кристаллов")
    if reward["dust"]:
        parts.append(f"{reward['dust']} пыли")
    return True, "🎁 Награда получена: " + ", ".join(parts), daily_reward_payload(db, player)



def apply_referral(db: Session, new_player: Player, referrer_id: int | None) -> tuple[bool, str]:
    if is_banned_player(new_player):
        return False, banned_message(new_player)
    if not referrer_id:
        return False, ""
    if new_player.referrer_player_id:
        return False, "Реферал уже был засчитан."
    if new_player.id == referrer_id:
        return False, "Нельзя пригласить самого себя."
    referrer = db.get(Player, referrer_id)
    if not referrer:
        return False, "Пригласивший игрок не найден."

    new_player.referrer_player_id = referrer.id
    new_player.coins += 100
    referrer.referrals_count = int(getattr(referrer, "referrals_count", 0) or 0) + 1
    referrer.coins += 150
    referrer.capsule_dust = int(getattr(referrer, "capsule_dust", 0) or 0) + 25
    add_season_score(referrer, 30)
    add_season_score(new_player, 15)
    log(db, new_player.id, None, "referral_join", f"referrer={referrer.id}")
    log(db, referrer.id, None, "referral_invite", f"new_player={new_player.id}")
    db.flush()
    return True, f"Бонус за приглашение получен. Тебе +100 монет, пригласившему +150 монет и 25 пыли."


def referral_payload(player: Player, bot_username: str | None = None) -> dict[str, Any]:
    username = (bot_username or "CapsulikiBot").lstrip("@")
    return {
        "player_id": player.id,
        "link": f"https://t.me/{username}?start=ref_{player.id}",
        "referrals_count": int(getattr(player, "referrals_count", 0) or 0),
        "rewards": [
            {"need": 1, "title": "1 друг", "reward": "150 монет + 25 пыли"},
            {"need": 3, "title": "3 друга", "reward": "редкая капсула"},
            {"need": 5, "title": "5 друзей", "reward": "эпическая капсула"},
            {"need": 10, "title": "10 друзей", "reward": "легендарная капсула"},
        ],
    }


def season_payload(db: Session, player: Player) -> dict[str, Any]:
    pets_total = int(db.scalar(select(func.count(Pet.id)).where(Pet.owner_player_id == player.id)) or 0)
    collected_species = int(
        db.scalar(select(func.count(func.distinct(Pet.species_key))).where(Pet.owner_player_id == player.id)) or 0
    )
    rank_rows = db.execute(
        select(Player.id)
        .order_by(desc(Player.season_score), desc(Player.capsules_opened), Player.id.asc())
        .limit(200)
    ).scalars().all()
    rank = None
    for idx, player_id in enumerate(rank_rows, 1):
        if player_id == player.id:
            rank = idx
            break
    return {
        "season": CURRENT_SEASON,
        "player": hname(player),
        "score": int(getattr(player, "season_score", 0) or 0),
        "rank": rank,
        "pets_total": pets_total,
        "collected_species": collected_species,
        "collection_total": len(SPECIES),
        "referrals_count": int(getattr(player, "referrals_count", 0) or 0),
    }


def season_top(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Player)
        .order_by(desc(Player.season_score), desc(Player.capsules_opened), Player.id.asc())
        .limit(limit)
    ).all()
    return [
        {
            "name": hname(player),
            "score": int(getattr(player, "season_score", 0) or 0),
            "opened": player.capsules_opened,
            "referrals": int(getattr(player, "referrals_count", 0) or 0),
        }
        for player in rows
    ]


def _species_by_alias(alias: str) -> dict[str, Any] | None:
    raw = (alias or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("pet") and raw[3:].isdigit():
        image_key = raw
        return next((item for item in SPECIES if item.get("image") == image_key), None)
    return SPECIES_BY_KEY.get(raw) or next((item for item in SPECIES if item["name"].lower() == raw), None)


def admin_give_currency(db: Session, telegram_user_id: int, currency: str, amount: int) -> tuple[bool, str]:
    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    if not player:
        return False, "Игрок не найден. Он должен хотя бы раз написать боту."
    amount = int(amount)
    if currency == "coins":
        player.coins = max(0, player.coins + amount)
    elif currency == "crystals":
        player.crystals = max(0, player.crystals + amount)
    elif currency == "dust":
        player.capsule_dust = max(0, int(getattr(player, "capsule_dust", 0) or 0) + amount)
    else:
        return False, "Неизвестная валюта."
    log(db, player.id, None, f"admin_give_{currency}", str(amount))
    db.flush()
    return True, f"Готово. {currency}: {amount:+d} для {hname(player)}."


def admin_give_pet(db: Session, telegram_user_id: int, species_alias: str) -> tuple[bool, str, Pet | None]:
    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    if not player:
        return False, "Игрок не найден. Он должен хотя бы раз написать боту.", None
    species = _species_by_alias(species_alias)
    if not species:
        return False, "Питомец не найден. Используй pet1..pet10 или species_key.", None
    pet = create_pet_from_species(db, player, species)
    add_season_score(player, 50)
    log(db, player.id, None, "admin_give_pet", species["key"])
    db.flush()
    return True, f"Выдан питомец: {pet.emoji} {pet.name} для {hname(player)}.", pet



def stars_shop_payload(player: Player) -> dict[str, Any]:
    return {
        "enabled": True,
        "balance": {
            "coins": player.coins,
            "crystals": player.crystals,
            "dust": int(getattr(player, "capsule_dust", 0) or 0),
            "season_score": int(getattr(player, "season_score", 0) or 0),
        },
        "products": [
            {"key": key, **value}
            for key, value in STAR_PRODUCTS.items()
        ],
    }


def get_star_product(product_key: str) -> dict[str, Any] | None:
    return STAR_PRODUCTS.get(product_key)


def build_star_payload(player: Player, product_key: str) -> str:
    return f"stars:{product_key}:{player.id}:{secrets.token_hex(5)}"


def parse_star_payload(payload: str) -> tuple[str | None, int | None]:
    try:
        prefix, product_key, player_id, _nonce = payload.split(":", 3)
        if prefix != "stars":
            return None, None
        return product_key, int(player_id)
    except Exception:
        return None, None


def apply_star_purchase(
    db: Session,
    telegram_user_id: int,
    payload: str,
    stars_amount: int,
    telegram_payment_charge_id: str | None = None,
    provider_payment_charge_id: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    product_key, player_id = parse_star_payload(payload)
    if not product_key or not player_id:
        return False, "Некорректный payload оплаты.", None

    product = get_star_product(product_key)
    if not product:
        return False, "Товар не найден.", None

    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    if not player:
        return False, "Игрок не найден.", None

    if player.id != player_id:
        return False, "Оплата не принадлежит этому игроку.", None
    if is_banned_player(player):
        return False, banned_message(player), None

    if int(product["stars"]) != int(stars_amount):
        return False, "Сумма оплаты не совпадает с товаром.", None

    if telegram_payment_charge_id:
        existing = db.scalar(
            select(StarPurchase).where(StarPurchase.telegram_payment_charge_id == telegram_payment_charge_id)
        )
        if existing:
            return True, "Эта оплата уже была обработана.", {"already_processed": True, "product": product}

    reward = dict(product["reward"])
    player.coins += int(reward.get("coins", 0))
    player.crystals += int(reward.get("crystals", 0))
    player.capsule_dust = int(getattr(player, "capsule_dust", 0) or 0) + int(reward.get("dust", 0))
    add_season_score(player, int(reward.get("season_score", 0)))

    purchase = StarPurchase(
        player_id=player.id,
        telegram_payment_charge_id=telegram_payment_charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        payload=payload,
        product_key=product_key,
        stars_amount=int(stars_amount),
        status="paid",
        reward_json=json.dumps(reward, ensure_ascii=False),
    )
    db.add(purchase)
    log(db, player.id, None, "stars_purchase", f"{product_key}:{stars_amount}")
    db.flush()

    parts = []
    if reward.get("coins"):
        parts.append(f"{reward['coins']} монет")
    if reward.get("crystals"):
        parts.append(f"{reward['crystals']} кристаллов")
    if reward.get("dust"):
        parts.append(f"{reward['dust']} пыли")
    if reward.get("season_score"):
        parts.append(f"{reward['season_score']} очков сезона")

    return True, f"Спасибо за поддержку! Получено: {', '.join(parts)}.", {"product": product, "reward": reward}


def purchase_history_payload(db: Session, player: Player, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(StarPurchase)
        .where(StarPurchase.player_id == player.id)
        .order_by(desc(StarPurchase.created_at))
        .limit(limit)
    ).all()
    result = []
    for item in rows:
        product = STAR_PRODUCTS.get(item.product_key, {"title": item.product_key})
        result.append({
            "id": item.id,
            "title": product["title"],
            "stars": item.stars_amount,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
            "reward": json.loads(item.reward_json or "{}"),
        })
    return result


def admin_payments_payload(db: Session) -> dict[str, Any]:
    total = int(db.scalar(select(func.count(StarPurchase.id))) or 0)
    stars = int(db.scalar(select(func.coalesce(func.sum(StarPurchase.stars_amount), 0))) or 0)
    recent = db.scalars(select(StarPurchase).order_by(desc(StarPurchase.created_at)).limit(10)).all()
    return {
        "total": total,
        "stars": stars,
        "recent": [
            {
                "id": item.id,
                "player_id": item.player_id,
                "product": item.product_key,
                "stars": item.stars_amount,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in recent
        ],
    }



def _count_actions(db: Session, action: str | None = None, since: datetime | None = None, prefix: str | None = None) -> int:
    q = select(func.count(ActionLog.id))
    if action:
        q = q.where(ActionLog.action == action)
    if prefix:
        q = q.where(ActionLog.action.like(f"{prefix}%"))
    if since:
        q = q.where(ActionLog.created_at >= since)
    return int(db.scalar(q) or 0)


def _count_purchases(db: Session, since: datetime | None = None) -> tuple[int, int]:
    q_count = select(func.count(StarPurchase.id))
    q_stars = select(func.coalesce(func.sum(StarPurchase.stars_amount), 0))
    if since:
        q_count = q_count.where(StarPurchase.created_at >= since)
        q_stars = q_stars.where(StarPurchase.created_at >= since)
    return int(db.scalar(q_count) or 0), int(db.scalar(q_stars) or 0)


def admin_dashboard_payload(db: Session) -> dict[str, Any]:
    now = utcnow()
    day = now - timedelta(days=1)
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)
    pay_day, stars_day = _count_purchases(db, day)
    pay_week, stars_week = _count_purchases(db, week)
    pay_month, stars_month = _count_purchases(db, month)
    return {
        "players": int(db.scalar(select(func.count(Player.id))) or 0),
        "players_day": int(db.scalar(select(func.count(Player.id)).where(Player.created_at >= day)) or 0),
        "banned": int(db.scalar(select(func.count(Player.id)).where(Player.is_banned == 1)) or 0),
        "groups": int(db.scalar(select(func.count(GroupChat.id))) or 0),
        "pets": int(db.scalar(select(func.count(Pet.id))) or 0),
        "opens_day": _count_actions(db, action="open_capsule", since=day),
        "opens_week": _count_actions(db, action="open_capsule", since=week),
        "care_day": int(db.scalar(select(func.count(ActionLog.id)).where(ActionLog.action.like("care_%"), ActionLog.created_at >= day)) or 0),
        "quests_day": int(db.scalar(select(func.count(ActionLog.id)).where(ActionLog.action.like("quest_claim_%"), ActionLog.created_at >= day)) or 0),
        "errors_day": int(db.scalar(select(func.count(ErrorLog.id)).where(ErrorLog.created_at >= day)) or 0),
        "payments_total": int(db.scalar(select(func.count(StarPurchase.id))) or 0),
        "stars_total": int(db.scalar(select(func.coalesce(func.sum(StarPurchase.stars_amount), 0))) or 0),
        "payments_day": pay_day,
        "stars_day": stars_day,
        "payments_week": pay_week,
        "stars_week": stars_week,
        "payments_month": pay_month,
        "stars_month": stars_month,
        "season_score_total": int(db.scalar(select(func.coalesce(func.sum(Player.season_score), 0))) or 0),
        "referrals_total": int(db.scalar(select(func.coalesce(func.sum(Player.referrals_count), 0))) or 0),
    }


def admin_users_payload(db: Session, limit: int = 15) -> list[dict[str, Any]]:
    rows = db.scalars(select(Player).order_by(desc(Player.created_at)).limit(limit)).all()
    return [
        {
            "id": p.id,
            "telegram_user_id": p.telegram_user_id,
            "username": p.username,
            "name": hname(p),
            "level": p.level,
            "coins": p.coins,
            "crystals": p.crystals,
            "dust": int(getattr(p, "capsule_dust", 0) or 0),
            "opened": p.capsules_opened,
            "season_score": int(getattr(p, "season_score", 0) or 0),
            "referrals": int(getattr(p, "referrals_count", 0) or 0),
            "created_at": p.created_at.isoformat(),
        }
        for p in rows
    ]


def admin_find_player(db: Session, query: str) -> Player | None:
    raw = (query or "").strip()
    if not raw:
        return None
    if raw.startswith("@"):
        raw = raw[1:]
    if raw.isdigit():
        value = int(raw)
        return db.scalar(select(Player).where((Player.telegram_user_id == value) | (Player.id == value)).limit(1))
    return db.scalar(select(Player).where(func.lower(Player.username) == raw.lower()).limit(1))


def admin_user_payload(db: Session, query: str) -> dict[str, Any] | None:
    player = admin_find_player(db, query)
    if not player:
        return None
    pets = int(db.scalar(select(func.count(Pet.id)).where(Pet.owner_player_id == player.id)) or 0)
    unique_pets = int(db.scalar(select(func.count(func.distinct(Pet.species_key))).where(Pet.owner_player_id == player.id)) or 0)
    pay_count = int(db.scalar(select(func.count(StarPurchase.id)).where(StarPurchase.player_id == player.id)) or 0)
    pay_stars = int(db.scalar(select(func.coalesce(func.sum(StarPurchase.stars_amount), 0)).where(StarPurchase.player_id == player.id)) or 0)
    referrer = db.get(Player, player.referrer_player_id) if player.referrer_player_id else None
    last_actions = db.scalars(
        select(ActionLog)
        .where(ActionLog.player_id == player.id)
        .order_by(desc(ActionLog.created_at))
        .limit(8)
    ).all()
    return {
        "id": player.id,
        "telegram_user_id": player.telegram_user_id,
        "username": player.username,
        "name": hname(player),
        "level": player.level,
        "xp": player.xp,
        "coins": player.coins,
        "crystals": player.crystals,
        "dust": int(getattr(player, "capsule_dust", 0) or 0),
        "opened": player.capsules_opened,
        "pets": pets,
        "unique_pets": unique_pets,
        "season_score": int(getattr(player, "season_score", 0) or 0),
        "referrals": int(getattr(player, "referrals_count", 0) or 0),
        "referrer": hname(referrer) if referrer else "",
        "payments": pay_count,
        "stars": pay_stars,
        "is_banned": int(getattr(player, "is_banned", 0) or 0),
        "ban_reason": player.ban_reason or "",
        "created_at": player.created_at.isoformat(),
        "updated_at": player.updated_at.isoformat(),
        "actions": [
            {
                "action": item.action,
                "text": item.text,
                "created_at": item.created_at.isoformat(),
            }
            for item in last_actions
        ],
    }


def admin_revenue_payload(db: Session) -> dict[str, Any]:
    now = utcnow()
    ranges = {
        "24h": now - timedelta(days=1),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
    }
    data = {}
    for label, since in ranges.items():
        count, stars = _count_purchases(db, since)
        data[label] = {"count": count, "stars": stars}
    total_count, total_stars = _count_purchases(db, None)
    return {
        "total": {"count": total_count, "stars": total_stars},
        "ranges": data,
    }


def admin_products_payload(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            StarPurchase.product_key,
            func.count(StarPurchase.id),
            func.coalesce(func.sum(StarPurchase.stars_amount), 0),
        )
        .group_by(StarPurchase.product_key)
        .order_by(desc(func.coalesce(func.sum(StarPurchase.stars_amount), 0)))
    ).all()
    result = []
    for product_key, count, stars in rows:
        product = STAR_PRODUCTS.get(product_key, {"title": product_key})
        result.append({"key": product_key, "title": product["title"], "count": int(count), "stars": int(stars)})
    return result


def admin_top_donors_payload(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            Player,
            func.count(StarPurchase.id).label("payments"),
            func.coalesce(func.sum(StarPurchase.stars_amount), 0).label("stars"),
        )
        .join(StarPurchase, StarPurchase.player_id == Player.id)
        .group_by(Player.id)
        .order_by(desc("stars"))
        .limit(limit)
    ).all()
    return [
        {
            "id": player.id,
            "telegram_user_id": player.telegram_user_id,
            "username": player.username,
            "name": hname(player),
            "payments": int(payments),
            "stars": int(stars),
        }
        for player, payments, stars in rows
    ]


def admin_referrals_payload(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Player)
        .where(Player.referrals_count > 0)
        .order_by(desc(Player.referrals_count), desc(Player.season_score))
        .limit(limit)
    ).all()
    return [
        {
            "id": player.id,
            "telegram_user_id": player.telegram_user_id,
            "username": player.username,
            "name": hname(player),
            "referrals": int(getattr(player, "referrals_count", 0) or 0),
            "season_score": int(getattr(player, "season_score", 0) or 0),
        }
        for player in rows
    ]


def admin_economy_payload(db: Session) -> dict[str, Any]:
    players = int(db.scalar(select(func.count(Player.id))) or 0)
    coins = int(db.scalar(select(func.coalesce(func.sum(Player.coins), 0))) or 0)
    crystals = int(db.scalar(select(func.coalesce(func.sum(Player.crystals), 0))) or 0)
    dust = int(db.scalar(select(func.coalesce(func.sum(Player.capsule_dust), 0))) or 0)
    pets = int(db.scalar(select(func.count(Pet.id))) or 0)
    opened = int(db.scalar(select(func.coalesce(func.sum(Player.capsules_opened), 0))) or 0)
    return {
        "players": players,
        "coins": coins,
        "crystals": crystals,
        "dust": dust,
        "pets": pets,
        "opened": opened,
        "avg_coins": round(coins / players, 2) if players else 0,
        "avg_crystals": round(crystals / players, 2) if players else 0,
        "avg_dust": round(dust / players, 2) if players else 0,
    }



def admin_stats(db: Session) -> dict[str, Any]:
    since = utcnow() - timedelta(days=1)
    return {
        "players": int(db.scalar(select(func.count(Player.id))) or 0),
        "groups": int(db.scalar(select(func.count(GroupChat.id))) or 0),
        "pets": int(db.scalar(select(func.count(Pet.id))) or 0),
        "opens_day": int(db.scalar(select(func.count(ActionLog.id)).where(ActionLog.action == "open_capsule", ActionLog.created_at >= since)) or 0),
        "group_events_active": int(db.scalar(select(func.count(GroupEvent.id)).where(GroupEvent.status == EventStatus.ACTIVE.value)) or 0),
        "trades_pending": int(db.scalar(select(func.count(Trade.id)).where(Trade.status == TradeStatus.PENDING.value)) or 0),
        "errors": int(db.scalar(select(func.count(ErrorLog.id)).where(ErrorLog.created_at >= since)) or 0),
        "payments": int(db.scalar(select(func.count(StarPurchase.id))) or 0),
        "stars": int(db.scalar(select(func.coalesce(func.sum(StarPurchase.stars_amount), 0))) or 0),
    }
