from __future__ import annotations

import json
import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import ActionLog, ErrorLog, EventStatus, Expedition, GroupChat, GroupEvent, Pet, Player, Rarity, Trade, TradeStatus, utcnow


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
]

SPECIES_BY_KEY: dict[str, dict[str, Any]] = {item["key"]: item for item in SPECIES}

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
    if capsule_type not in CAPSULE_TYPES:
        return False, "Такой капсулы нет.", None

    now = utcnow()
    last = aware(player.last_open_at)
    if capsule_type == "daily" and last and not force and now < last + timedelta(hours=20):
        left = int(((last + timedelta(hours=20)) - now).total_seconds() // 3600) + 1
        return False, f"Капсула ещё заряжается. Осталось примерно {left} ч.", None

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
    log(db, player.id, None, "open_capsule", f"{hname(player)} получил {pet.emoji} {pet.name}")
    db.flush()
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
        f"Навык: <b>{pet.skill}</b>"
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


def active_group_event(db: Session, chat_id: int, event_type: str | None = None) -> GroupEvent | None:
    q = select(GroupEvent).where(GroupEvent.chat_id == chat_id, GroupEvent.status == EventStatus.ACTIVE.value)
    if event_type:
        q = q.where(GroupEvent.event_type == event_type)
    return db.scalar(q.order_by(desc(GroupEvent.created_at)))


def spawn_catch_event(db: Session, chat_id: int, chat_title: str) -> GroupEvent:
    rarity = random.choice(["rare", "epic", "legendary"])
    species = choose_species(rarity)
    data = {"species": species, "rarity": rarity, "caught_by": None}
    event = GroupEvent(chat_id=chat_id, chat_title=chat_title or "Чат", event_type="catch", data_json=json.dumps(data, ensure_ascii=False), finishes_at=utcnow() + timedelta(minutes=10))
    db.add(event)
    db.flush()
    return event


def catch_group_pet(db: Session, chat_id: int, player: Player, event_id: int) -> tuple[bool, str, Pet | None]:
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
    }
