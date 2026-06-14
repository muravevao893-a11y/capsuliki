from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.game import (
    CAPSULE_TYPES,
    album_payload,
    shop_payload,
    EXPEDITIONS,
    accept_trade,
    admin_stats,
    care_pet,
    catch_group_pet,
    collection_payload,
    expedition_payload,
    favorite_pet,
    finish_expedition,
    get_or_create_player,
    hit_boss,
    leaderboard,
    open_capsule,
    pet_payload,
    propose_trade,
    set_favorite,
    spawn_boss_event,
    spawn_catch_event,
    start_expedition,
)
from app.models import GroupEvent, Pet, Player
from app.pet_media import find_pet_image

logger = logging.getLogger(__name__)
router = Router(name="capsuliki-router")
BRAND = "Капсулики"


def h(value: Any) -> str:
    return html.escape(str(value), quote=False)


def is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


def is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def is_admin_user(user_id: int | None) -> bool:
    return bool(user_id and user_id in set(get_settings().admin_ids))


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть капсулу", callback_data="cap:open")],
        [InlineKeyboardButton(text="📖 Альбом", callback_data="cap:album:0"), InlineKeyboardButton(text="🛒 Магазин", callback_data="cap:shop")],
        [InlineKeyboardButton(text="👤 Моя коллекция", callback_data="cap:my"), InlineKeyboardButton(text="🐾 Любимчик", callback_data="cap:pet")],
        [InlineKeyboardButton(text="🎒 Экспедиции", callback_data="cap:expeditions"), InlineKeyboardButton(text="🏆 Топ", callback_data="cap:top")],
    ])



def capsule_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ежедневная", callback_data="cap:open:daily")],
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="cap:open:common"), InlineKeyboardButton(text="🔵 Редкая", callback_data="cap:open:rare")],
        [InlineKeyboardButton(text="🟣 Эпическая", callback_data="cap:open:epic"), InlineKeyboardButton(text="🟡 Легендарная", callback_data="cap:open:legendary")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="cap:shop"), InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def album_keyboard(page: int, total: int, pet_id: int | None = None) -> InlineKeyboardMarkup:
    prev_page = max(0, page - 1)
    next_page = min(max(0, total - 1), page + 1)
    rows: list[list[InlineKeyboardButton]] = []
    if total > 1:
        rows.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cap:album:{prev_page}"),
            InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data=f"cap:album:{page}"),
            InlineKeyboardButton(text="➡️ Далее", callback_data=f"cap:album:{next_page}"),
        ])
    if pet_id:
        rows.append([
            InlineKeyboardButton(text="⭐ Любимчик", callback_data=f"cap:setfav:{pet_id}"),
            InlineKeyboardButton(text="🎒 В экспедицию", callback_data="cap:expeditions"),
        ])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Открыть обычную", callback_data="cap:open:common")],
        [InlineKeyboardButton(text="🔵 Открыть редкую", callback_data="cap:open:rare")],
        [InlineKeyboardButton(text="🟣 Открыть эпическую", callback_data="cap:open:epic")],
        [InlineKeyboardButton(text="🟡 Открыть легендарную", callback_data="cap:open:legendary")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def pet_keyboard(pet_id: int | None = None) -> InlineKeyboardMarkup:
    pid = pet_id or 0
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍖 Покормить", callback_data=f"cap:care:feed:{pid}"), InlineKeyboardButton(text="🎮 Поиграть", callback_data=f"cap:care:play:{pid}")],
        [InlineKeyboardButton(text="🧼 Помыть", callback_data=f"cap:care:wash:{pid}"), InlineKeyboardButton(text="🏋️ Тренировать", callback_data=f"cap:care:train:{pid}")],
        [InlineKeyboardButton(text="💤 Уложить", callback_data=f"cap:care:sleep:{pid}")],
        [InlineKeyboardButton(text="🎒 Экспедиции", callback_data="cap:expeditions"), InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def expedition_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, spec in EXPEDITIONS.items():
        rows.append([InlineKeyboardButton(text=f"{spec['name']} · {spec['minutes']} мин", callback_data=f"cap:exp:{key}")])
    rows.append([InlineKeyboardButton(text="✅ Забрать награду", callback_data="cap:exp_finish")])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def catch_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✨ Поймать", callback_data=f"cap:catch:{event_id}")]])


def boss_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Ударить босса", callback_data=f"cap:boss_hit:{event_id}")]])


def render_help() -> str:
    return (
        "🎁 <b>Капсулики</b>\n\n"
        "Открывай капсулы, собирай питомцев, ухаживай за любимчиком, отправляй его в экспедиции и лови редких капсуликов в группах.\n\n"
        "<b>Команды:</b>\n"
        "/open — открыть ежедневную капсулу\n"
        "/my — коллекция\n"
        "/pet — любимчик\n"
        "/expedition — экспедиции\n"
        "/top — топ коллекционеров\n"
        "/trade @user PET_ID — предложить обмен\n"
        "/accepttrade ID — принять обмен"
    )


def render_collection(payload: dict[str, Any]) -> str:
    p = payload["player"]
    lines = [
        "👤 <b>Коллекционер</b>",
        "",
        f"Игрок: <b>{h(p['name'])}</b>",
        f"Уровень: <b>{p['level']}</b> · XP: <b>{p['xp']}</b>",
        f"Монеты: <b>{p['coins']}</b> · Кристаллы: <b>{p['crystals']}</b> · Пыль: <b>{p.get('dust', 0)}</b>",
        f"Капсул открыто: <b>{p['opened']}</b> · серия: <b>{p['streak']}</b>",
        f"Питомцев: <b>{payload['total']}</b>",
        "",
    ]
    fav = payload.get("favorite")
    if fav:
        lines.append(f"Любимчик: <b>{h(fav['title'])}</b> · {fav['rarity_name']}")
    if payload.get("recent"):
        lines.append("\nПоследние:")
        for pet in payload["recent"]:
            lines.append(f"• <code>{pet['id']}</code> {pet['title']} · {pet['rarity_name']} · сила {pet['power']}")
    return "\n".join(lines)


def render_open_card(pet: dict[str, Any] | None) -> str:
    if not pet:
        return "🎁 Капсула ещё не открыта."
    return (
        f"🎁 <b>Капсула открыта!</b>\n\n"
        f"Ты получил: <b>{h(pet['title'])}</b>\n"
        f"Редкость: <b>{pet['rarity_name']}</b>\n"
        f"Стихия: <b>{h(pet['element'])}</b>\n"
        f"Характер: <b>{h(pet['character'])}</b>\n"
        f"Навык: <b>{h(pet['skill'])}</b>"
    )


def render_catch_card(winner_name: str, pet: dict[str, Any] | None) -> str:
    if not pet:
        return f"✨ <b>{h(winner_name)}</b> поймал питомца!"
    return (
        f"✨ <b>{h(winner_name)}</b> поймал {h(pet['title'])}!\n\n"
        f"Редкость: <b>{pet['rarity_name']}</b>\n"
        f"Стихия: <b>{h(pet['element'])}</b>\n"
        f"Навык: <b>{h(pet['skill'])}</b>"
    )


async def answer_with_pet_media(message: Message, text: str, pet: dict[str, Any] | None, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    image_path = find_pet_image((pet or {}).get("image_key") if pet else None)
    if image_path:
        await message.answer_photo(FSInputFile(image_path), caption=text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


def render_pet(pet: dict[str, Any] | None) -> str:
    if not pet:
        return "🐾 Питомца пока нет. Открой капсулу: /open"
    return (
        f"🐾 <b>{h(pet['title'])}</b>\n\n"
        f"Редкость: <b>{pet['rarity_name']}</b>\n"
        f"Уровень: <b>{pet['level']}</b> · XP: <b>{pet['xp']}</b>\n"
        f"Сила: <b>{pet['power']}</b>\n"
        f"Стихия: <b>{h(pet['element'])}</b>\n"
        f"Характер: <b>{h(pet['character'])}</b>\n"
        f"Навык: <b>{h(pet['skill'])}</b>\n\n"
        f"🍖 Сытость: <b>{pet['hunger']}</b>\n"
        f"🎮 Настроение: <b>{pet['mood']}</b>\n"
        f"🧼 Чистота: <b>{pet['clean']}</b>\n"
        f"💤 Энергия: <b>{pet['energy']}</b>"
    )


def render_expeditions(payload: dict[str, Any]) -> str:
    lines = ["🎒 <b>Экспедиции</b>", "", "Отправь любимчика за монетами, кристаллами и редкими находками.", ""]
    for loc in payload["locations"]:
        lines.append(f"• <b>{loc['name']}</b> — {loc['minutes']} мин · сила от {loc['min_power']}")
    return "\n".join(lines)


def render_top(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🏆 Топ пока пуст."
    lines = ["🏆 <b>Топ коллекционеров</b>", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. <b>{h(item['name'])}</b> · питомцев {item['pets']} · ур. {item['level']} · 💎 {item['crystals']}")
    return "\n".join(lines)



def render_capsules() -> str:
    lines = ["🎁 <b>Капсулы</b>", ""]
    for key, spec in CAPSULE_TYPES.items():
        cost = "бесплатно"
        if spec.get("cost"):
            parts = []
            if spec["cost"].get("coins"):
                parts.append(f"{spec['cost']['coins']} монет")
            if spec["cost"].get("crystals"):
                parts.append(f"{spec['cost']['crystals']} кристаллов")
            if spec["cost"].get("dust"):
                parts.append(f"{spec['cost']['dust']} пыли")
            cost = ", ".join(parts)
        lines.append(f"• <b>{spec['name']}</b> — {h(cost)}")
        lines.append(f"  {h(spec['description'])}")
    lines.append("\nКоманда: <code>/open rare</code>, <code>/open epic</code> и так далее.")
    return "\n".join(lines)


def render_shop(payload: dict[str, Any]) -> str:
    lines = [
        "🛒 <b>Магазин капсул</b>",
        "",
        f"Монеты: <b>{payload['coins']}</b>",
        f"Кристаллы: <b>{payload['crystals']}</b>",
        f"Пыль капсул: <b>{payload['dust']}</b>",
        "",
    ]
    for item in payload["capsules"]:
        lines.append(f"• <b>{item['name']}</b> — {h(item['cost'])}")
        lines.append(f"  {h(item['description'])}")
    return "\n".join(lines)


def render_album(payload: dict[str, Any]) -> str:
    if not payload.get("pet"):
        return "📖 <b>Альбом пуст</b>\n\nОткрой первую капсулу: /open"
    pet = payload["pet"]
    return (
        f"📖 <b>Альбом коллекции</b>\n"
        f"{payload['page'] + 1}/{payload['total']}\n\n"
        f"{h(pet['title'])}\n"
        f"Редкость: <b>{pet['rarity_name']}</b>\n"
        f"Уровень: <b>{pet['level']}</b> · Сила: <b>{pet['power']}</b>\n"
        f"Стихия: <b>{h(pet['element'])}</b>\n"
        f"Характер: <b>{h(pet['character'])}</b>\n"
        f"Навык: <b>{h(pet['skill'])}</b>"
    )



def render_stats(payload: dict[str, Any]) -> str:
    return (
        "🛠 <b>Статистика</b>\n\n"
        f"Игроков: <b>{payload['players']}</b>\n"
        f"Питомцев: <b>{payload['pets']}</b>\n"
        f"Открытий за 24ч: <b>{payload['opens_day']}</b>\n"
        f"Активных групповых событий: <b>{payload['group_events_active']}</b>\n"
        f"Обменов в ожидании: <b>{payload['trades_pending']}</b>"
    )


async def get_player_from_message(message: Message) -> Player | None:
    if not message.from_user or message.from_user.is_bot:
        return None
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        db.expunge(player)
        return player


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if is_private(message):
        await message.answer(render_help(), reply_markup=main_keyboard())
    else:
        await message.answer(
            "🎁 <b>Капсулики в чате!</b>\n\n"
            "Открывай капсулы в личке или прямо здесь. Иногда в группу будут залетать редкие капсулики и боссы.",
            reply_markup=main_keyboard(),
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(render_help(), reply_markup=main_keyboard())


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("🏠 <b>Меню Капсуликов</b>", reply_markup=main_keyboard())


@router.message(Command("capsules"))
async def cmd_capsules(message: Message) -> None:
    await message.answer(render_capsules(), reply_markup=capsule_keyboard())


@router.message(Command("shop"))
async def cmd_shop(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = shop_payload(player)
    await message.answer(render_shop(payload), reply_markup=shop_keyboard())


@router.message(Command("album"))
async def cmd_album(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    try:
        page = max(0, int((command.args or "1").strip()) - 1)
    except ValueError:
        page = 0
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = album_payload(db, player, page)
    pet = payload.get("pet")
    await answer_with_pet_media(message, render_album(payload), pet, reply_markup=album_keyboard(payload["page"], payload["total"], pet["id"] if pet else None))


@router.message(Command("open"))
async def cmd_open(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    capsule_type = (command.args or "daily").strip().lower()
    if capsule_type in {"обычная", "normal"}:
        capsule_type = "common"
    if capsule_type in {"редкая"}:
        capsule_type = "rare"
    if capsule_type in {"эпическая"}:
        capsule_type = "epic"
    if capsule_type in {"легендарная"}:
        capsule_type = "legendary"
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text, pet = open_capsule(db, player, capsule_type=capsule_type)
        payload = pet_payload(pet) if pet else None
    if ok and payload:
        await answer_with_pet_media(message, text, payload, reply_markup=pet_keyboard(payload["id"]))
        return
    await message.answer(text, reply_markup=capsule_keyboard())



@router.message(Command("my"))
async def cmd_my(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = collection_payload(db, player)
    await message.answer(render_collection(payload), reply_markup=main_keyboard())


@router.message(Command("pet"))
async def cmd_pet(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        pet = favorite_pet(db, player)
        payload = pet_payload(pet)
    if payload:
        await answer_with_pet_media(message, render_pet(payload), payload, reply_markup=pet_keyboard(payload["id"]))
        return
    await message.answer(render_pet(payload), reply_markup=pet_keyboard())


@router.message(Command("setfav"))
async def cmd_setfav(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    try:
        pet_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("Нужен ID питомца: <code>/setfav 12</code>")
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text = set_favorite(db, player, pet_id)
    await message.answer(("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())


@router.message(Command("expedition"))
async def cmd_expedition(message: Message) -> None:
    await message.answer(render_expeditions(expedition_payload()), reply_markup=expedition_keyboard())


@router.message(Command("finish"))
async def cmd_finish(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text = finish_expedition(db, player)
    await message.answer(text, reply_markup=main_keyboard())


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    with session_scope() as db:
        items = leaderboard(db)
    await message.answer(render_top(items), reply_markup=main_keyboard())


@router.message(Command("trade"))
async def cmd_trade(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    if len(parts) < 2:
        await message.answer("Обмен: <code>/trade @user PET_ID</code>")
        return
    username = parts[0].lstrip("@").lower()
    try:
        pet_id = int(parts[1])
    except ValueError:
        await message.answer("ID питомца должен быть числом.")
        return
    with session_scope() as db:
        proposer, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        # Simple MVP lookup. User must have opened the bot at least once.
        players = db.scalars(select(Player)).all()
        target = next((p for p in players if (p.username or "").lower() == username), None)
        if not target:
            await message.answer("Игрок не найден. Он должен хотя бы раз написать боту.")
            return
        ok, text, _trade = propose_trade(db, proposer, target, pet_id)
    await message.answer(("✅ " if ok else "⛔ ") + h(text))


@router.message(Command("accepttrade"))
async def cmd_accept_trade(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    try:
        trade_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("Нужен ID обмена: <code>/accepttrade 3</code>")
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text = accept_trade(db, player, trade_id)
    await message.answer(("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())


@router.message(Command("spawn"))
async def cmd_spawn(message: Message) -> None:
    if not is_group(message):
        await message.answer("События спавнятся в группах.")
        return
    if not is_admin_user(message.from_user.id if message.from_user else None):
        await message.answer("Только админ проекта.")
        return
    with session_scope() as db:
        event = spawn_catch_event(db, message.chat.id, message.chat.title or "Чат")
        data = __import__("json").loads(event.data_json)
        species = data["species"]
    await message.answer(
        f"✨ <b>В чат залетел редкий капсулик!</b>\n\n"
        f"{species['emoji']} <b>{h(species['name'])}</b>\n"
        f"Кто успеет — попробует поймать.",
        reply_markup=catch_keyboard(event.id),
    )


@router.message(Command("boss"))
async def cmd_boss(message: Message) -> None:
    if not is_group(message):
        await message.answer("Босс появляется в группах.")
        return
    if not is_admin_user(message.from_user.id if message.from_user else None):
        await message.answer("Только админ проекта.")
        return
    with session_scope() as db:
        event = spawn_boss_event(db, message.chat.id, message.chat.title or "Чат")
        data = __import__("json").loads(event.data_json)
        boss = data["boss"]
    await message.answer(
        f"🐲 <b>Босс недели появился!</b>\n\n{boss['emoji']} <b>{h(boss['name'])}</b>\nHP: <b>{boss['hp']}</b>",
        reply_markup=boss_keyboard(event.id),
    )


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_stats(db)
    await message.answer(render_stats(payload))


@router.callback_query(F.data == "cap:menu")
async def cb_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("🏠 <b>Меню Капсуликов</b>", reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:open")
async def cb_open(callback: CallbackQuery) -> None:
    await callback.answer("Открываем…")
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text, pet = open_capsule(db, player, capsule_type="daily")
            payload = pet_payload(pet) if pet else None
        if ok and payload:
            await answer_with_pet_media(callback.message, text, payload, reply_markup=pet_keyboard(payload["id"]))
            return
        await callback.message.answer(text, reply_markup=main_keyboard())


@router.callback_query(F.data.startswith("cap:open:"))
async def cb_open_typed(callback: CallbackQuery) -> None:
    await callback.answer("Открываем…")
    if callback.from_user and isinstance(callback.message, Message) and callback.data:
        capsule_type = callback.data.split(":")[-1]
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text, pet = open_capsule(db, player, capsule_type=capsule_type)
            payload = pet_payload(pet) if pet else None
        if ok and payload:
            await answer_with_pet_media(callback.message, text, payload, reply_markup=pet_keyboard(payload["id"]))
            return
        await callback.message.answer(text, reply_markup=capsule_keyboard())


@router.callback_query(F.data == "cap:shop")
async def cb_shop(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = shop_payload(player)
        await callback.message.answer(render_shop(payload), reply_markup=shop_keyboard())


@router.callback_query(F.data.startswith("cap:album:"))
async def cb_album(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message) and callback.data:
        try:
            page = int(callback.data.split(":")[-1])
        except ValueError:
            page = 0
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = album_payload(db, player, page)
        pet = payload.get("pet")
        await answer_with_pet_media(callback.message, render_album(payload), pet, reply_markup=album_keyboard(payload["page"], payload["total"], pet["id"] if pet else None))


@router.callback_query(F.data.startswith("cap:setfav:"))
async def cb_set_fav(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message) and callback.data:
        try:
            pet_id = int(callback.data.split(":")[-1])
        except ValueError:
            return
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text = set_favorite(db, player, pet_id)
        await callback.message.answer(("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())



@router.callback_query(F.data == "cap:my")
async def cb_my(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = collection_payload(db, player)
        await callback.message.answer(render_collection(payload), reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:pet")
async def cb_pet(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            pet = favorite_pet(db, player)
            payload = pet_payload(pet)
        if payload:
            await answer_with_pet_media(callback.message, render_pet(payload), payload, reply_markup=pet_keyboard(payload["id"]))
            return
        await callback.message.answer(render_pet(payload), reply_markup=pet_keyboard())


@router.callback_query(F.data.startswith("cap:care:"))
async def cb_care(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        return
    _, _, action, raw_pet_id = callback.data.split(":")
    pet_id = int(raw_pet_id) if raw_pet_id and raw_pet_id != "0" else None
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text, payload = care_pet(db, player, action, pet_id)
    await callback.message.answer(("✅ " if ok else "⛔ ") + h(text) + ("\n\n" + render_pet(payload) if payload else ""), reply_markup=pet_keyboard(payload["id"] if payload else None))


@router.callback_query(F.data == "cap:expeditions")
async def cb_expeditions(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(render_expeditions(expedition_payload()), reply_markup=expedition_keyboard())


@router.callback_query(F.data.startswith("cap:exp:"))
async def cb_start_exp(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        return
    key = callback.data.split(":")[-1]
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text, _ = start_expedition(db, player, key)
    await callback.message.answer(("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:exp_finish")
async def cb_exp_finish(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text = finish_expedition(db, player)
    await callback.message.answer(text, reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:top")
async def cb_top(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        with session_scope() as db:
            items = leaderboard(db)
        await callback.message.answer(render_top(items), reply_markup=main_keyboard())


@router.callback_query(F.data.startswith("cap:catch:"))
async def cb_catch(callback: CallbackQuery) -> None:
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        await callback.answer("Не получилось.", show_alert=True)
        return
    event_id = int(callback.data.split(":")[-1])
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text, pet = catch_group_pet(db, callback.message.chat.id, player, event_id)
        payload = pet_payload(pet) if pet else None
    await callback.answer("Готово")
    if ok and payload:
        await answer_with_pet_media(callback.message, render_catch_card(player.first_name or "Игрок", payload), payload)
        return
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("cap:boss_hit:"))
async def cb_boss_hit(callback: CallbackQuery) -> None:
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        await callback.answer("Не получилось.", show_alert=True)
        return
    event_id = int(callback.data.split(":")[-1])
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text, data = hit_boss(db, callback.message.chat.id, player, event_id)
    await callback.answer()
    hp_line = ""
    if data and data.get("hp", 0) > 0:
        hp_line = f"\nHP босса: <b>{data['hp']}</b>/<b>{data['max_hp']}</b>"
    await callback.message.answer(text + hp_line, reply_markup=boss_keyboard(event_id) if data and data.get("hp", 0) > 0 else None)


async def group_event_loop(bot: Bot) -> None:
    settings = get_settings()
    while True:
        try:
            await asyncio.sleep(max(60, settings.group_event_interval_minutes * 60))
            # MVP does not know all group chats until messages happen; events are manual/admin in v0.1.
            # Loop is reserved for v0.2 when chat registry is added.
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("group event loop failed")


async def run_bot_polling() -> None:
    settings = get_settings()
    if not settings.has_bot_token:
        logger.warning("BOT_TOKEN is empty. Polling disabled.")
        return
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    task: asyncio.Task | None = None
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        if settings.enable_group_events:
            task = asyncio.create_task(group_event_loop(bot))
        await dp.start_polling(bot)
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await bot.session.close()
