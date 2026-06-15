from __future__ import annotations

import asyncio
import html
import logging
import traceback
from datetime import timedelta
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.redis_store import acquire_redis_lock, close_redis, redis_configured, redis_ping, redis_rate_limited
from app.game import (
    CAPSULE_TYPES,
    album_payload,
    shop_payload,
    EXPEDITIONS,
    accept_trade,
    active_group_event,
    admin_errors_payload,
    button_rate_limited,
    group_chats_for_events,
    group_registry_payload,
    log_error,
    mark_group_event_sent,
    profile_payload,
    register_group_chat,
    admin_give_currency,
    admin_give_pet,
    apply_referral,
    referral_payload,
    season_payload,
    season_top,
    admin_config_payload,
    set_config_value,
    get_config_bool,
    get_config_int,
    admin_health_payload,
    backup_payload,
    ban_player,
    banned_players_payload,
    clear_errors,
    last_actions_payload,
    unban_player,
    admin_dashboard_payload,
    admin_users_payload,
    admin_user_payload,
    admin_revenue_payload,
    admin_products_payload,
    admin_top_donors_payload,
    admin_referrals_payload,
    admin_economy_payload,
    admin_payments_payload,
    apply_star_purchase,
    build_star_payload,
    get_star_product,
    purchase_history_payload,
    stars_shop_payload,
    admin_stats,
    claim_daily_reward,
    claim_quests,
    daily_reward_payload,
    quest_payload,
    care_pet,
    catch_group_pet,
    collection_payload,
    expedition_payload,
    favorite_pet,
    finish_expedition,
    expire_old_group_events,
    get_or_create_player,
    hit_boss,
    leaderboard,
    last_group_event_at,
    open_capsule,
    pet_info_payload,
    pet_owner_name,
    player_limits_payload,
    player_pets_payload,
    pet_payload,
    propose_trade,
    set_favorite,
    spawn_boss_event,
    spawn_catch_event,
    start_expedition,
)
from app.models import GroupEvent, Pet, Player, utcnow
from app.pet_media import find_pet_image
from app.cards import build_pet_card

logger = logging.getLogger(__name__)
router = Router(name="capsuliki-router")
BRAND = "Капсулики"

LAST_BOT_MESSAGES: dict[int, int] = {}


async def _delete_previous_bot_message(bot: Bot, chat_id: int) -> None:
    previous_id = LAST_BOT_MESSAGES.get(chat_id)
    if not previous_id:
        return
    try:
        await bot.delete_message(chat_id, previous_id)
    except Exception:
        pass


async def _delete_user_command(message: Message) -> None:
    if not message.text or not message.text.startswith("/"):
        return
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.from_user and message.from_user.is_bot:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def clean_answer(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_web_page_preview: bool | None = None,
) -> Message:
    await _delete_previous_bot_message(message.bot, message.chat.id)
    await _delete_user_command(message)
    sent = await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
    LAST_BOT_MESSAGES[message.chat.id] = sent.message_id
    return sent


async def clean_photo(
    message: Message,
    photo: FSInputFile,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    await _delete_previous_bot_message(message.bot, message.chat.id)
    await _delete_user_command(message)
    sent = await message.answer_photo(photo, caption=caption, reply_markup=reply_markup)
    LAST_BOT_MESSAGES[message.chat.id] = sent.message_id
    return sent


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="запуск"),
        BotCommand(command="menu", description="меню"),
        BotCommand(command="open", description="открыть капсулу"),
        BotCommand(command="capsules", description="типы капсул"),
        BotCommand(command="shop", description="магазин"),
        BotCommand(command="album", description="альбом питомцев"),
        BotCommand(command="profile", description="профиль"),
        BotCommand(command="quests", description="задания дня"),
        BotCommand(command="daily", description="ежедневная награда"),
        BotCommand(command="ref", description="пригласить друзей"),
        BotCommand(command="payments", description="мои оплаты"),
        BotCommand(command="admin_set_config", description="изменить конфиг"),
        BotCommand(command="admin_config", description="конфиг админки"),
        BotCommand(command="rules", description="правила"),
        BotCommand(command="admin_force_open", description="тестовое открытие"),
        BotCommand(command="limits", description="мои лимиты"),
        BotCommand(command="stars", description="донат-магазин"),
        BotCommand(command="donate", description="поддержать проект"),
        BotCommand(command="season_top", description="топ сезона"),
        BotCommand(command="season", description="сезон"),
        BotCommand(command="my", description="коллекция"),
        BotCommand(command="pet", description="любимчик"),
        BotCommand(command="pets", description="мои питомцы"),
        BotCommand(command="petinfo", description="инфо о питомце"),
        BotCommand(command="expedition", description="экспедиции"),
        BotCommand(command="finish", description="забрать награду"),
        BotCommand(command="top", description="топ игроков"),
        BotCommand(command="trade", description="обмен"),
        BotCommand(command="accepttrade", description="принять обмен"),
    ]
    await bot.set_my_commands(commands)



class CallbackThrottleMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery) and event.from_user and isinstance(event.message, Message):
            try:
                redis_result = redis_rate_limited(
                    f"cap:throttle:callback:{event.message.chat.id}:{event.from_user.id}",
                    seconds=2,
                )
                if redis_result is not None:
                    limited, left = redis_result
                else:
                    with session_scope() as db:
                        player, _ = get_or_create_player(db, event.from_user.id, event.from_user.username, event.from_user.first_name)
                        limited, left = button_rate_limited(db, event.message.chat.id, player, "callback", seconds=2)
                if limited:
                    await event.answer(f"⏳ {left} сек.", show_alert=False)
                    return None
            except Exception:
                logger.debug("callback throttle failed", exc_info=True)
        return await handler(event, data)



class SafetyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        settings = get_settings()
        message = None
        user = None
        if isinstance(event, Message):
            message = event
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            if isinstance(event.message, Message):
                message = event.message

        if user and not user.is_bot:
            try:
                with session_scope() as db:
                    maintenance = settings.maintenance_mode or get_config_bool(db, "maintenance_mode", False)
                    if maintenance and not is_admin_user(user.id):
                        if isinstance(event, CallbackQuery):
                            await event.answer("Бот на обновлении. Скоро вернёмся.", show_alert=True)
                            return None
                        if message:
                            await clean_answer(message, "🛠 Бот на обновлении. Скоро вернёмся.")
                            return None
                    player, _ = get_or_create_player(db, user.id, user.username, user.first_name)
                    if int(getattr(player, "is_banned", 0) or 0) == 1 and not is_admin_user(user.id):
                        reason = player.ban_reason or "без причины"
                        if isinstance(event, CallbackQuery):
                            await event.answer(f"Аккаунт заблокирован: {reason}", show_alert=True)
                            return None
                        if message:
                            await clean_answer(message, f"⛔ Аккаунт заблокирован.\nПричина: {h(reason)}")
                            return None
            except Exception:
                logger.debug("safety middleware failed", exc_info=True)

        return await handler(event, data)



def _short_trace(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]


def store_runtime_error(source: str, exc: BaseException, chat_id: int | None = None, user_id: int | None = None, update_json: str | None = None) -> None:
    try:
        with session_scope() as db:
            log_error(db, source, exc, traceback_text=_short_trace(exc), chat_id=chat_id, user_id=user_id, update_json=update_json)
    except Exception:
        logger.exception("Could not store runtime error")


def h(value: Any) -> str:
    return html.escape(str(value), quote=False)


def is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}



async def notify_admins(bot: Bot, text: str) -> None:
    settings = get_settings()
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.debug("Could not notify admin %s", admin_id, exc_info=True)



def is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def is_admin_user(user_id: int | None) -> bool:
    return bool(user_id and user_id in set(get_settings().admin_ids))


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть", callback_data="cap:open")],
        [InlineKeyboardButton(text="📖 Альбом", callback_data="cap:album:0")],
        [InlineKeyboardButton(text="⋯ Ещё", callback_data="cap:more")],
    ])


def more_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="cap:profile")],
        [InlineKeyboardButton(text="🎯 Задания", callback_data="cap:quests")],
        [InlineKeyboardButton(text="🎁 Награда", callback_data="cap:daily")],
        [InlineKeyboardButton(text="🌙 Сезон", callback_data="cap:season")],
        [InlineKeyboardButton(text="🔗 Пригласить", callback_data="cap:ref")],
        [InlineKeyboardButton(text="⭐ Донат", callback_data="cap:donate")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="cap:shop")],
        [InlineKeyboardButton(text="🎒 Экспедиции", callback_data="cap:expeditions")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="cap:top")],
    ])



def capsule_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ежедневная", callback_data="cap:open:daily")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="cap:shop")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
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
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="cap:open:common")],
        [InlineKeyboardButton(text="🔵 Редкая", callback_data="cap:open:rare")],
        [InlineKeyboardButton(text="🟣 Эпическая", callback_data="cap:open:epic")],
        [InlineKeyboardButton(text="🟡 Легендарная", callback_data="cap:open:legendary")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def pet_keyboard(pet_id: int | None = None) -> InlineKeyboardMarkup:
    pid = pet_id or 0
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍖 Уход", callback_data=f"cap:care_menu:{pid}")],
        [InlineKeyboardButton(text="🎒 Экспедиция", callback_data="cap:expeditions")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def care_keyboard(pet_id: int | None = None) -> InlineKeyboardMarkup:
    pid = pet_id or 0
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍖 Покормить", callback_data=f"cap:care:feed:{pid}")],
        [InlineKeyboardButton(text="🎮 Поиграть", callback_data=f"cap:care:play:{pid}")],
        [InlineKeyboardButton(text="🏋️ Тренировать", callback_data=f"cap:care:train:{pid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cap:pet")],
    ])


def expedition_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌲 Лес", callback_data="cap:exp:forest")],
        [InlineKeyboardButton(text="🏖 Пляж", callback_data="cap:exp:beach")],
        [InlineKeyboardButton(text="🌋 Вулкан", callback_data="cap:exp:volcano")],
        [InlineKeyboardButton(text="✅ Забрать награду", callback_data="cap:exp_finish")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


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


async def answer_with_pet_media(
    message: Message,
    text: str,
    pet: dict[str, Any] | None,
    reply_markup: InlineKeyboardMarkup | None = None,
    card_title: str | None = None,
) -> None:
    image_path = find_pet_image((pet or {}).get("image_key") if pet else None)
    if pet:
        try:
            card_path = build_pet_card(
                pet,
                image_path=image_path,
                owner_name=message.from_user.username if message.from_user and message.from_user.username else None,
                title=card_title or pet.get("drop_title") or "Капсула открыта!",
                chance=pet.get("drop_chance"),
            )
            await clean_photo(message, FSInputFile(card_path), caption=text, reply_markup=reply_markup)
            return
        except Exception as exc:
            store_runtime_error("card_build", exc, chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None)
    if image_path:
        await clean_photo(message, FSInputFile(image_path), caption=text, reply_markup=reply_markup)
        return
    await clean_answer(message, text, reply_markup=reply_markup)


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




def render_profile(payload: dict[str, Any]) -> str:
    favorite = payload.get("favorite")
    rarest = payload.get("rarest")
    lines = [
        "👤 <b>Профиль коллекционера</b>",
        "",
        f"Игрок: <b>{h(payload['name'])}</b>",
        f"Уровень: <b>{payload['level']}</b> · XP: <b>{payload['xp']}</b>",
        f"Питомцев: <b>{payload['pets_total']}</b>/<b>{payload['collection_total']}</b>",
        f"Капсул открыто: <b>{payload['capsules_opened']}</b>",
        f"Монеты: <b>{payload['coins']}</b> · Кристаллы: <b>{payload['crystals']}</b> · Пыль: <b>{payload['dust']}</b>",
    ]
    if favorite:
        lines.append(f"Любимчик: <b>{h(favorite['title'])}</b> · {favorite['rarity_name']}")
    if rarest:
        lines.append(f"Редчайший: <b>{h(rarest['title'])}</b> · {rarest['rarity_name']}")
    return "\n".join(lines)



def render_player_pets(payload: dict[str, Any]) -> str:
    if not payload.get("items"):
        return "🐾 <b>Питомцев пока нет</b>\n\nОткрой капсулу: /open"
    lines = [
        "🐾 <b>Мои питомцы</b>",
        "",
        f"Владелец: <b>{h(payload['owner'])}</b>",
        f"Всего: <b>{payload['total']}</b>",
        "",
    ]
    for pet in payload["items"][:30]:
        lines.append(f"• <code>{pet['id']}</code> {h(pet['title'])} · {pet['rarity_name']} · сила {pet['power']}")
    lines.append("\nИнфо: <code>/petinfo ID</code>")
    return "\n".join(lines)


def render_pet_info(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "🐾 Питомец не найден."
    owner = payload.get("owner") or {}
    return (
        f"🐾 <b>{h(payload['title'])}</b>\n\n"
        f"ID: <code>{payload['id']}</code>\n"
        f"Владелец: <b>{h(owner.get('name', 'неизвестно'))}</b>\n"
        f"Редкость: <b>{payload['rarity_name']}</b>\n"
        f"Уровень: <b>{payload['level']}</b> · XP: <b>{payload['xp']}</b>\n"
        f"Сила: <b>{payload['power']}</b>\n"
        f"Стихия: <b>{h(payload['element'])}</b>\n"
        f"Характер: <b>{h(payload['character'])}</b>\n"
        f"Навык: <b>{h(payload['skill'])}</b>"
    )


def render_admin_errors(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🧯 <b>Ошибки</b>\n\nЧисто."
    lines = ["🧯 <b>Последние ошибки</b>", ""]
    for item in items:
        msg = str(item.get("message", ""))[:110]
        lines.append(f"#{item['id']} · <b>{h(item['type'])}</b> · chat <code>{h(item.get('chat_id'))}</code>")
        lines.append(f"└ {h(msg)}")
    return "\n".join(lines)


def render_admin_groups(items: list[dict[str, Any]]) -> str:
    if not items:
        return "👥 <b>Группы</b>\n\nБот пока не видел группы."
    lines = ["👥 <b>Группы бота</b>", ""]
    for item in items:
        lines.append(
            f"• <b>{h(item['title'])}</b> · игроков {item['players_seen']} · сообщений {item['messages_seen']}"
        )
    return "\n".join(lines)



def render_quests(payload: dict[str, Any]) -> str:
    lines = ["🎯 <b>Задания на сегодня</b>", ""]
    for quest in payload["quests"]:
        if quest["claimed"]:
            mark = "✅"
        elif quest["done"]:
            mark = "🎁"
        else:
            mark = "▫️"
        lines.append(f"{mark} {h(quest['title'])} — <b>{h(quest['reward'])}</b>")
    lines.append("")
    lines.append("🎁 — можно забрать награду")
    return "\n".join(lines)


def quests_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Забрать награды", callback_data="cap:quests_claim")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def render_daily(payload: dict[str, Any]) -> str:
    reward = payload["reward"]
    status = "уже забрана" if payload["claimed"] else "можно забрать"
    parts = [f"{reward['coins']} монет"]
    if reward["crystals"]:
        parts.append(f"{reward['crystals']} кристаллов")
    if reward["dust"]:
        parts.append(f"{reward['dust']} пыли")
    return (
        "🎁 <b>Ежедневная награда</b>\n\n"
        f"Серия: <b>{payload['streak']}</b>\n"
        f"{reward['title']}: <b>{', '.join(parts)}</b>\n"
        f"Статус: <b>{status}</b>"
    )


def daily_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Забрать", callback_data="cap:daily_claim")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])





def render_limits(payload: dict[str, Any]) -> str:
    def line(title: str, item: dict[str, Any]) -> str:
        limit = item.get("limit", 0)
        used = item.get("used", 0)
        if int(limit) <= 0:
            return f"• {title}: <b>{used}</b>/∞"
        return f"• {title}: <b>{used}</b>/<b>{limit}</b>"

    lines = [
        "⏳ <b>Лимиты на сегодня</b>",
        "",
        line("Ежедневная капсула", payload["free_open"]),
        line("Платные капсулы", payload["paid_open"]),
        line("Уход", payload["care"]),
        line("Экспедиции", payload["expedition"]),
        line("Ловля в группе", payload["group_catch"]),
    ]
    if payload.get("next_daily_open_at"):
        lines.append("")
        lines.append("Ежедневная капсула обновляется примерно через 20 часов после открытия.")
    return "\n".join(lines)


def render_referral(payload: dict[str, Any]) -> str:
    lines = [
        "🔗 <b>Приглашение друзей</b>",
        "",
        f"Твоя ссылка:",
        f"<code>{h(payload['link'])}</code>",
        "",
        f"Приглашено: <b>{payload['referrals_count']}</b>",
        "",
        "Награды:",
    ]
    for item in payload["rewards"]:
        done = "✅" if payload["referrals_count"] >= item["need"] else "▫️"
        lines.append(f"{done} {h(item['title'])} — {h(item['reward'])}")
    return "\n".join(lines)


def render_season(payload: dict[str, Any]) -> str:
    season = payload["season"]
    rank = payload["rank"] or "—"
    return (
        f"{season['name']}\n\n"
        f"{h(season['description'])}\n"
        f"Длительность: <b>{season['days']} дней</b>\n\n"
        f"Игрок: <b>{h(payload['player'])}</b>\n"
        f"Очки сезона: <b>{payload['score']}</b>\n"
        f"Место: <b>{rank}</b>\n"
        f"Коллекция: <b>{payload['collected_species']}</b>/<b>{payload['collection_total']}</b>\n"
        f"Питомцев всего: <b>{payload['pets_total']}</b>\n"
        f"Приглашений: <b>{payload['referrals_count']}</b>"
    )


def render_season_top(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🏆 <b>Топ сезона</b>\n\nПока пусто."
    lines = ["🏆 <b>Топ сезона</b>", ""]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. <b>{h(item['name'])}</b> — {item['score']} очков · капсул {item['opened']} · реф {item['referrals']}"
        )
    return "\n".join(lines)


def season_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ сезона", callback_data="cap:season_top")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def ref_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])




def render_stars_shop(payload: dict[str, Any]) -> str:
    lines = [
        "⭐ <b>Донат-магазин</b>",
        "",
        "Поддержка проекта через Telegram Stars.",
        "",
        f"Баланс: 💎 <b>{payload['balance']['crystals']}</b> · пыль <b>{payload['balance']['dust']}</b>",
        "",
    ]
    for item in payload["products"]:
        reward = item["reward"]
        parts = []
        if reward.get("coins"):
            parts.append(f"{reward['coins']} монет")
        if reward.get("crystals"):
            parts.append(f"{reward['crystals']} кристаллов")
        if reward.get("dust"):
            parts.append(f"{reward['dust']} пыли")
        if reward.get("season_score"):
            parts.append(f"{reward['season_score']} очков сезона")
        lines.append(f"• <b>{h(item['title'])}</b> — <b>{item['stars']}⭐</b>")
        lines.append(f"  {h(', '.join(parts))}")
    return "\n".join(lines)


def stars_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 15", callback_data="cap:buy:support_15")],
        [InlineKeyboardButton(text="⭐ 35", callback_data="cap:buy:rare_pack_35")],
        [InlineKeyboardButton(text="⭐ 75", callback_data="cap:buy:epic_pack_75")],
        [InlineKeyboardButton(text="⭐ 149", callback_data="cap:buy:legend_pack_149")],
        [InlineKeyboardButton(text="📜 История", callback_data="cap:payments")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="cap:menu")],
    ])


def render_payment_history(items: list[dict[str, Any]]) -> str:
    if not items:
        return "📜 <b>История оплат</b>\n\nПокупок пока нет."
    lines = ["📜 <b>История оплат</b>", ""]
    for item in items:
        lines.append(f"#{item['id']} · {h(item['title'])} · <b>{item['stars']}⭐</b> · {h(item['status'])}")
    return "\n".join(lines)



def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Обзор", callback_data="admin:dashboard")],
        [InlineKeyboardButton(text="⭐ Доход", callback_data="admin:revenue")],
        [InlineKeyboardButton(text="🧾 Товары", callback_data="admin:products")],
        [InlineKeyboardButton(text="👑 Донатеры", callback_data="admin:donors")],
        [InlineKeyboardButton(text="🔗 Рефы", callback_data="admin:refs")],
        [InlineKeyboardButton(text="💰 Экономика", callback_data="admin:economy")],
        [InlineKeyboardButton(text="👥 Игроки", callback_data="admin:users")],
        [InlineKeyboardButton(text="🩺 Health", callback_data="admin:health")],
        [InlineKeyboardButton(text="⚙️ Config", callback_data="admin:config")],
        [InlineKeyboardButton(text="⛔ Баны", callback_data="admin:banned")],
    ])



def render_banned_players(items: list[dict[str, Any]]) -> str:
    if not items:
        return "⛔ <b>Баны</b>\n\nСписок пуст."
    lines = ["⛔ <b>Забаненные игроки</b>", ""]
    for item in items:
        username = f"@{item['username']}" if item.get("username") else item["name"]
        lines.append(f"• <code>{item['telegram_user_id']}</code> · <b>{h(username)}</b> · {h(item['reason'])}")
    return "\n".join(lines)



def render_admin_config(items: list[dict[str, Any]]) -> str:
    lines = ["⚙️ <b>Runtime config</b>", ""]
    for item in items:
        lines.append(f"• <code>{h(item['key'])}</code> = <b>{h(item['value'])}</b> · default {h(item['default'])}")
    lines.append("\nИзменить: <code>/admin_set_config KEY VALUE</code>")
    return "\n".join(lines)


def render_admin_health(payload: dict[str, Any]) -> str:
    redis_state = "disabled" if not redis_configured() else ("ok" if redis_ping() else "error")
    return (
        "🩺 <b>Health</b>\n\n"
        f"Database: <b>{h(payload['database'])}</b> · {h(payload.get('database_info', {}).get('kind', 'unknown'))}\n"
        f"DB driver: <code>{h(payload.get('database_info', {}).get('driver', 'unknown'))}</code>\n"
        f"Redis: <b>{redis_state}</b>\n"
        f"Maintenance: <b>{payload['maintenance']}</b>\n"
        f"Stars enabled: <b>{payload['stars_enabled']}</b>\n"
        f"Players: <b>{payload['players']}</b>\n"
        f"Banned: <b>{payload['banned']}</b>\n"
        f"Errors: <b>{payload['errors']}</b>\n"
        f"Active events: <b>{payload['active_events']}</b>"
    )


def render_last_actions(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🧾 <b>Последние действия</b>\n\nПусто."
    lines = ["🧾 <b>Последние действия</b>", ""]
    for item in items:
        lines.append(f"#{item['id']} · player {item.get('player_id')} · <b>{h(item['action'])}</b>")
        if item.get("text"):
            lines.append(f"└ {h(str(item['text'])[:90])}")
    return "\n".join(lines)


def render_admin_dashboard(payload: dict[str, Any]) -> str:
    return (
        "🛠 <b>Админка Капсуликов</b>\n\n"
        f"Игроков: <b>{payload['players']}</b> · новых за 24ч: <b>{payload['players_day']}</b>\n"
        f"Забанено: <b>{payload.get('banned', 0)}</b>\n"
        f"Групп: <b>{payload['groups']}</b>\n"
        f"Питомцев: <b>{payload['pets']}</b>\n\n"
        f"Капсул за 24ч: <b>{payload['opens_day']}</b>\n"
        f"Капсул за 7д: <b>{payload['opens_week']}</b>\n"
        f"Уход за 24ч: <b>{payload['care_day']}</b>\n"
        f"Квесты за 24ч: <b>{payload['quests_day']}</b>\n\n"
        f"Оплат всего: <b>{payload['payments_total']}</b> · <b>{payload['stars_total']}⭐</b>\n"
        f"24ч: <b>{payload['payments_day']}</b> оплат · <b>{payload['stars_day']}⭐</b>\n"
        f"7д: <b>{payload['payments_week']}</b> оплат · <b>{payload['stars_week']}⭐</b>\n"
        f"30д: <b>{payload['payments_month']}</b> оплат · <b>{payload['stars_month']}⭐</b>\n\n"
        f"Рефералов всего: <b>{payload['referrals_total']}</b>\n"
        f"Ошибок за 24ч: <b>{payload['errors_day']}</b>"
    )


def render_admin_users(items: list[dict[str, Any]]) -> str:
    if not items:
        return "👥 <b>Игроки</b>\n\nПока пусто."
    lines = ["👥 <b>Последние игроки</b>", ""]
    for item in items:
        username = f"@{item['username']}" if item.get("username") else item["name"]
        lines.append(
            f"<code>{item['telegram_user_id']}</code> · <b>{h(username)}</b> · ур.{item['level']} · "
            f"капсул {item['opened']} · {item['season_score']} очк."
        )
    lines.append("\nДетально: <code>/admin_user USER_ID</code>")
    return "\n".join(lines)


def render_admin_user(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "👤 Игрок не найден."
    username = f"@{payload['username']}" if payload.get("username") else "—"
    lines = [
        "👤 <b>Игрок</b>",
        "",
        f"Имя: <b>{h(payload['name'])}</b>",
        f"Username: <b>{h(username)}</b>",
        f"TG ID: <code>{payload['telegram_user_id']}</code>",
        f"Internal ID: <code>{payload['id']}</code>",
        "",
        f"Уровень: <b>{payload['level']}</b> · XP <b>{payload['xp']}</b>",
        f"Монеты: <b>{payload['coins']}</b>",
        f"Кристаллы: <b>{payload['crystals']}</b>",
        f"Пыль: <b>{payload['dust']}</b>",
        "",
        f"Капсул открыто: <b>{payload['opened']}</b>",
        f"Питомцев: <b>{payload['pets']}</b> · уникальных <b>{payload['unique_pets']}</b>",
        f"Очки сезона: <b>{payload['season_score']}</b>",
        f"Рефералы: <b>{payload['referrals']}</b>",
        f"Пригласил: <b>{h(payload['referrer'] or '—')}</b>",
        "",
        f"Оплат: <b>{payload['payments']}</b> · <b>{payload['stars']}⭐</b>",
        f"Бан: <b>{'да' if payload.get('is_banned') else 'нет'}</b> {h(payload.get('ban_reason', ''))}",
    ]
    if payload["actions"]:
        lines.append("\nПоследние действия:")
        for item in payload["actions"]:
            lines.append(f"• {h(item['action'])} · {h(str(item.get('text') or '')[:70])}")
    return "\n".join(lines)


def render_admin_revenue(payload: dict[str, Any]) -> str:
    lines = [
        "⭐ <b>Доход Stars</b>",
        "",
        f"Всего: <b>{payload['total']['count']}</b> оплат · <b>{payload['total']['stars']}⭐</b>",
        "",
    ]
    for label, item in payload["ranges"].items():
        lines.append(f"{label}: <b>{item['count']}</b> оплат · <b>{item['stars']}⭐</b>")
    return "\n".join(lines)


def render_admin_products(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🧾 <b>Товары</b>\n\nПокупок пока нет."
    lines = ["🧾 <b>Популярность товаров</b>", ""]
    for item in items:
        lines.append(f"• <b>{h(item['title'])}</b> — {item['count']} покупок · <b>{item['stars']}⭐</b>")
    return "\n".join(lines)


def render_admin_donors(items: list[dict[str, Any]]) -> str:
    if not items:
        return "👑 <b>Топ донатеров</b>\n\nПока пусто."
    lines = ["👑 <b>Топ донатеров</b>", ""]
    for i, item in enumerate(items, 1):
        username = f"@{item['username']}" if item.get("username") else item["name"]
        lines.append(f"{i}. <b>{h(username)}</b> · {item['payments']} оплат · <b>{item['stars']}⭐</b>")
    return "\n".join(lines)


def render_admin_refs(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🔗 <b>Рефералы</b>\n\nПока никто никого не привёл."
    lines = ["🔗 <b>Топ по рефералам</b>", ""]
    for i, item in enumerate(items, 1):
        username = f"@{item['username']}" if item.get("username") else item["name"]
        lines.append(f"{i}. <b>{h(username)}</b> · {item['referrals']} реф · {item['season_score']} очк.")
    return "\n".join(lines)


def render_admin_economy(payload: dict[str, Any]) -> str:
    return (
        "💰 <b>Экономика</b>\n\n"
        f"Игроков: <b>{payload['players']}</b>\n"
        f"Капсул открыто всего: <b>{payload['opened']}</b>\n"
        f"Питомцев всего: <b>{payload['pets']}</b>\n\n"
        f"Монет в экономике: <b>{payload['coins']}</b>\n"
        f"Кристаллов в экономике: <b>{payload['crystals']}</b>\n"
        f"Пыли в экономике: <b>{payload['dust']}</b>\n\n"
        f"Среднее на игрока:\n"
        f"монеты <b>{payload['avg_coins']}</b> · кристаллы <b>{payload['avg_crystals']}</b> · пыль <b>{payload['avg_dust']}</b>"
    )



def render_admin_payments(payload: dict[str, Any]) -> str:
    lines = [
        "⭐ <b>Платежи</b>",
        "",
        f"Всего оплат: <b>{payload['total']}</b>",
        f"Всего Stars: <b>{payload['stars']}⭐</b>",
        "",
    ]
    for item in payload["recent"]:
        lines.append(f"#{item['id']} · player {item['player_id']} · {h(item['product'])} · {item['stars']}⭐")
    return "\n".join(lines)


def render_stats(payload: dict[str, Any]) -> str:
    return (
        "🛠 <b>Статистика</b>\n\n"
        f"Игроков: <b>{payload['players']}</b>\n"
        f"Групп: <b>{payload.get('groups', 0)}</b>\n"
        f"Питомцев: <b>{payload['pets']}</b>\n"
        f"Открытий за 24ч: <b>{payload['opens_day']}</b>\n"
        f"Активных групповых событий: <b>{payload['group_events_active']}</b>\n"
        f"Обменов в ожидании: <b>{payload['trades_pending']}</b>\n"
        f"Ошибок за 24ч: <b>{payload.get('errors', 0)}</b>\n"
        f"Оплат: <b>{payload.get('payments', 0)}</b> · Stars собрано: <b>{payload.get('stars', 0)}</b>"
    )


async def get_player_from_message(message: Message) -> Player | None:
    if not message.from_user or message.from_user.is_bot:
        return None
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        db.expunge(player)
        return player


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    ref_text = ""
    ref_id = None
    raw_args = (command.args or "").strip() if command else ""
    if raw_args.startswith("ref_"):
        try:
            ref_id = int(raw_args.replace("ref_", "", 1))
        except ValueError:
            ref_id = None

    if is_private(message):
        if message.from_user and not message.from_user.is_bot:
            with session_scope() as db:
                player, created = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
                if created and ref_id:
                    ok, ref_text = apply_referral(db, player, ref_id)
                    if ok:
                        ref_text = "\n\n" + ref_text
        await clean_answer(message, render_help() + h(ref_text), reply_markup=main_keyboard())
    else:
        with session_scope() as db:
            player = None
            if message.from_user and not message.from_user.is_bot:
                player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
            register_group_chat(db, message.chat.id, message.chat.title or "Чат", player)
        await clean_answer(message, 
            "🎁 <b>Капсулики в чате!</b>\n\n"
            "Открывай капсулы в личке или прямо здесь. Иногда в группу будут залетать редкие капсулики и боссы.",
            reply_markup=main_keyboard(),
        )


@router.message(Command("help"))

async def cmd_help(message: Message) -> None:
    await clean_answer(message, render_help(), reply_markup=main_keyboard())

@router.message(Command("rules"))
async def cmd_rules(message: Message) -> None:
    await clean_answer(message, render_rules(), reply_markup=main_keyboard())

@router.message(Command("limits"))
async def cmd_limits(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = player_limits_payload(db, player)
    await clean_answer(message, render_limits(payload), reply_markup=main_keyboard())




@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await clean_answer(message, "🏠 <b>Меню Капсуликов</b>", reply_markup=main_keyboard())


@router.message(Command("capsules"))
async def cmd_capsules(message: Message) -> None:
    await clean_answer(message, render_capsules(), reply_markup=capsule_keyboard())


@router.message(Command("shop"))
async def cmd_shop(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = shop_payload(player)
    await clean_answer(message, render_shop(payload), reply_markup=shop_keyboard())


@router.message(Command("quests"))
async def cmd_quests(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = quest_payload(db, player)
    await clean_answer(message, render_quests(payload), reply_markup=quests_keyboard())


@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = daily_reward_payload(db, player)
    await clean_answer(message, render_daily(payload), reply_markup=daily_keyboard())


@router.message(Command("ref"))
async def cmd_ref(message: Message) -> None:
    if not message.from_user:
        return
    bot_user = await message.bot.get_me()
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = referral_payload(player, bot_user.username)
    await clean_answer(message, render_referral(payload), reply_markup=ref_keyboard())


@router.message(Command("season"))
async def cmd_season(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = season_payload(db, player)
    await clean_answer(message, render_season(payload), reply_markup=season_keyboard())


@router.message(Command("season_top"))
async def cmd_season_top(message: Message) -> None:
    with session_scope() as db:
        items = season_top(db)
    await clean_answer(message, render_season_top(items), reply_markup=season_keyboard())


@router.message(Command("donate", "stars"))
async def cmd_donate(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = stars_shop_payload(player)
    await clean_answer(message, render_stars_shop(payload), reply_markup=stars_keyboard())


@router.message(Command("payments"))
async def cmd_payments(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        items = purchase_history_payload(db, player)
    await clean_answer(message, render_payment_history(items), reply_markup=stars_keyboard())


@router.message(Command("admin_payments"))
async def cmd_admin_payments(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_payments_payload(db)
    await clean_answer(message, render_admin_payments(payload))


@router.message(Command("admin"))
async def cmd_admin_dashboard(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_dashboard_payload(db)
    await clean_answer(message, render_admin_dashboard(payload), reply_markup=admin_keyboard())


@router.message(Command("admin_users"))
async def cmd_admin_users(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = admin_users_payload(db)
    await clean_answer(message, render_admin_users(items), reply_markup=admin_keyboard())


@router.message(Command("admin_user"))
async def cmd_admin_user(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    query = (command.args or "").strip()
    if not query:
        await clean_answer(message, "Формат: <code>/admin_user USER_ID</code>")
        return
    with session_scope() as db:
        payload = admin_user_payload(db, query)
    await clean_answer(message, render_admin_user(payload), reply_markup=admin_keyboard())


@router.message(Command("admin_revenue"))
async def cmd_admin_revenue(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_revenue_payload(db)
    await clean_answer(message, render_admin_revenue(payload), reply_markup=admin_keyboard())


@router.message(Command("admin_products"))
async def cmd_admin_products(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = admin_products_payload(db)
    await clean_answer(message, render_admin_products(items), reply_markup=admin_keyboard())


@router.message(Command("admin_top_donors"))
async def cmd_admin_top_donors(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = admin_top_donors_payload(db)
    await clean_answer(message, render_admin_donors(items), reply_markup=admin_keyboard())


@router.message(Command("admin_referrals"))
async def cmd_admin_referrals(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = admin_referrals_payload(db)
    await clean_answer(message, render_admin_refs(items), reply_markup=admin_keyboard())


@router.message(Command("admin_economy"))
async def cmd_admin_economy(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_economy_payload(db)
    await clean_answer(message, render_admin_economy(payload), reply_markup=admin_keyboard())


@router.message(Command("admin_ban"))
async def cmd_admin_ban(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split(maxsplit=1)
    if not parts:
        await clean_answer(message, "Формат: <code>/admin_ban USER_ID причина</code>")
        return
    reason = parts[1] if len(parts) > 1 else "без причины"
    with session_scope() as db:
        ok, text = ban_player(db, int(parts[0]), reason)
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=admin_keyboard())


@router.message(Command("admin_unban"))
async def cmd_admin_unban(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    raw = (command.args or "").strip()
    if not raw:
        await clean_answer(message, "Формат: <code>/admin_unban USER_ID</code>")
        return
    with session_scope() as db:
        ok, text = unban_player(db, int(raw))
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=admin_keyboard())


@router.message(Command("admin_banned"))
async def cmd_admin_banned(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = banned_players_payload(db)
    await clean_answer(message, render_banned_players(items), reply_markup=admin_keyboard())


@router.message(Command("admin_health"))
async def cmd_admin_health(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_health_payload(db)
    await clean_answer(message, render_admin_health(payload), reply_markup=admin_keyboard())


@router.message(Command("admin_config"))
async def cmd_admin_config(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = admin_config_payload(db)
    await clean_answer(message, render_admin_config(items), reply_markup=admin_keyboard())


@router.message(Command("admin_set_config"))
async def cmd_admin_set_config(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2:
        await clean_answer(message, "Формат: <code>/admin_set_config KEY VALUE</code>", reply_markup=admin_keyboard())
        return
    with session_scope() as db:
        ok, text = set_config_value(db, parts[0], parts[1])
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=admin_keyboard())



@router.message(Command("admin_last_actions"))
async def cmd_admin_last_actions(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = last_actions_payload(db)
    await clean_answer(message, render_last_actions(items), reply_markup=admin_keyboard())


@router.message(Command("admin_clear_errors"))
async def cmd_admin_clear_errors(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        count = clear_errors(db)
    await clean_answer(message, f"🧹 Очищено ошибок: <b>{count}</b>", reply_markup=admin_keyboard())


@router.message(Command("admin_backup"))
async def cmd_admin_backup(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = backup_payload(db)
    from pathlib import Path
    import json as _json
    import tempfile
    path = Path(tempfile.gettempdir()) / f"capsuliki_backup_{int(__import__('time').time())}.json"
    path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    await _delete_previous_bot_message(message.bot, message.chat.id)
    sent = await message.answer_document(FSInputFile(path), caption="🧩 Бэкап Капсуликов")
    LAST_BOT_MESSAGES[message.chat.id] = sent.message_id







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
    await clean_answer(message, text, reply_markup=capsule_keyboard())



@router.message(Command("my"))
async def cmd_my(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = collection_payload(db, player)
    await clean_answer(message, render_collection(payload), reply_markup=main_keyboard())


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
    await clean_answer(message, render_pet(payload), reply_markup=pet_keyboard())


@router.message(Command("setfav"))
async def cmd_setfav(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    try:
        pet_id = int((command.args or "").strip())
    except ValueError:
        await clean_answer(message, "Нужен ID питомца: <code>/setfav 12</code>")
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text = set_favorite(db, player, pet_id)
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())


@router.message(Command("expedition"))
async def cmd_expedition(message: Message) -> None:
    await clean_answer(message, render_expeditions(expedition_payload()), reply_markup=expedition_keyboard())


@router.message(Command("finish"))
async def cmd_finish(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text = finish_expedition(db, player)
    await clean_answer(message, text, reply_markup=main_keyboard())


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    with session_scope() as db:
        items = leaderboard(db)
    await clean_answer(message, render_top(items), reply_markup=main_keyboard())


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = profile_payload(db, player)
    await clean_answer(message, render_profile(payload), reply_markup=main_keyboard())


@router.message(Command("pets"))
async def cmd_pets(message: Message) -> None:
    if not message.from_user:
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = player_pets_payload(db, player)
    await clean_answer(message, render_player_pets(payload), reply_markup=main_keyboard())


@router.message(Command("petinfo"))
async def cmd_pet_info(message: Message, command: CommandObject) -> None:
    try:
        pet_id = int((command.args or "").strip())
    except ValueError:
        await clean_answer(message, "Нужен ID питомца: <code>/petinfo 12</code>", reply_markup=main_keyboard())
        return
    with session_scope() as db:
        payload = pet_info_payload(db, pet_id)
    await answer_with_pet_media(message, render_pet_info(payload), payload, reply_markup=main_keyboard())



@router.message(Command("admin_errors"))
async def cmd_admin_errors(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = admin_errors_payload(db)
    await clean_answer(message, render_admin_errors(items))


@router.message(Command("admin_groups"))
async def cmd_admin_groups(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        items = group_registry_payload(db)
    await clean_answer(message, render_admin_groups(items))


@router.message(Command("admin_give_coins"))
async def cmd_admin_give_coins(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split()
    if len(parts) != 2:
        await clean_answer(message, "Формат: <code>/admin_give_coins USER_ID 1000</code>")
        return
    with session_scope() as db:
        ok, text = admin_give_currency(db, int(parts[0]), "coins", int(parts[1]))
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text))


@router.message(Command("admin_give_crystals"))
async def cmd_admin_give_crystals(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split()
    if len(parts) != 2:
        await clean_answer(message, "Формат: <code>/admin_give_crystals USER_ID 50</code>")
        return
    with session_scope() as db:
        ok, text = admin_give_currency(db, int(parts[0]), "crystals", int(parts[1]))
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text))


@router.message(Command("admin_give_dust"))
async def cmd_admin_give_dust(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split()
    if len(parts) != 2:
        await clean_answer(message, "Формат: <code>/admin_give_dust USER_ID 200</code>")
        return
    with session_scope() as db:
        ok, text = admin_give_currency(db, int(parts[0]), "dust", int(parts[1]))
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text))


@router.message(Command("admin_give_pet"))
async def cmd_admin_give_pet(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split()
    if len(parts) != 2:
        await clean_answer(message, "Формат: <code>/admin_give_pet USER_ID pet6</code>")
        return
    with session_scope() as db:
        ok, text, pet = admin_give_pet(db, int(parts[0]), parts[1])
        payload = pet_payload(pet) if pet else None
    if ok and payload:
        await answer_with_pet_media(message, h(text), payload, reply_markup=main_keyboard(), card_title="Админ-выдача")
        return
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text))


@router.message(Command("admin_force_open"))
async def cmd_admin_force_open(message: Message, command: CommandObject) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    parts = (command.args or "").split()
    if not parts:
        await clean_answer(message, "Формат: <code>/admin_force_open USER_ID [daily|rare|epic|legendary]</code>")
        return
    user_id = int(parts[0])
    capsule_type = parts[1].lower() if len(parts) > 1 else "daily"
    with session_scope() as db:
        from sqlalchemy import select as _select
        player = db.scalar(_select(Player).where(Player.telegram_user_id == user_id))
        if not player:
            await clean_answer(message, "Игрок не найден.")
            return
        ok, text, pet = open_capsule(db, player, force=True, capsule_type=capsule_type)
        payload = pet_payload(pet) if pet else None
    if ok and payload:
        await answer_with_pet_media(message, text, payload, reply_markup=main_keyboard(), card_title="Админ-тест")
        return
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text))




@router.message(Command("trade"))
async def cmd_trade(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    if len(parts) < 2:
        await clean_answer(message, "Обмен: <code>/trade @user PET_ID</code>")
        return
    username = parts[0].lstrip("@").lower()
    try:
        pet_id = int(parts[1])
    except ValueError:
        await clean_answer(message, "ID питомца должен быть числом.")
        return
    with session_scope() as db:
        proposer, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        # Simple MVP lookup. User must have opened the bot at least once.
        players = db.scalars(select(Player)).all()
        target = next((p for p in players if (p.username or "").lower() == username), None)
        if not target:
            await clean_answer(message, "Игрок не найден. Он должен хотя бы раз написать боту.")
            return
        ok, text, _trade = propose_trade(db, proposer, target, pet_id)
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text))


@router.message(Command("accepttrade"))
async def cmd_accept_trade(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    try:
        trade_id = int((command.args or "").strip())
    except ValueError:
        await clean_answer(message, "Нужен ID обмена: <code>/accepttrade 3</code>")
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text = accept_trade(db, player, trade_id)
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())


@router.message(Command("spawn"))
async def cmd_spawn(message: Message) -> None:
    if not is_group(message):
        await clean_answer(message, "События спавнятся в группах.")
        return
    if not is_admin_user(message.from_user.id if message.from_user else None):
        await clean_answer(message, "Только админ проекта.")
        return

    lock = acquire_redis_lock(f"cap:event:spawn:{message.chat.id}:catch", ttl_seconds=30)
    if lock and not lock.acquired:
        await clean_answer(message, "⏳ Событие уже создаётся. Не тыкай как дятел по энтеру 😄")
        return
    try:
        with session_scope() as db:
            group = register_group_chat(db, message.chat.id, message.chat.title or "Чат")
            event = active_group_event(db, message.chat.id, "catch")
            if event is None:
                event = spawn_catch_event(db, message.chat.id, message.chat.title or "Чат")
                mark_group_event_sent(group)
            data = __import__("json").loads(event.data_json or "{}")
            species = data.get("species") or {"emoji": "✨", "name": "Капсулик"}
        await clean_answer(
            message,
            f"✨ <b>В чат залетел редкий капсулик!</b>\n\n"
            f"{species['emoji']} <b>{h(species['name'])}</b>\n"
            f"Кто успеет — попробует поймать.",
            reply_markup=catch_keyboard(event.id),
        )
    finally:
        if lock:
            lock.release()


@router.message(Command("boss"))
async def cmd_boss(message: Message) -> None:
    if not is_group(message):
        await clean_answer(message, "Босс появляется в группах.")
        return
    if not is_admin_user(message.from_user.id if message.from_user else None):
        await clean_answer(message, "Только админ проекта.")
        return

    lock = acquire_redis_lock(f"cap:event:spawn:{message.chat.id}:boss", ttl_seconds=30)
    if lock and not lock.acquired:
        await clean_answer(message, "⏳ Босс уже призывается. Магия занята, подожди секунду 😄")
        return
    try:
        with session_scope() as db:
            group = register_group_chat(db, message.chat.id, message.chat.title or "Чат")
            event = active_group_event(db, message.chat.id, "boss")
            if event is None:
                event = spawn_boss_event(db, message.chat.id, message.chat.title or "Чат")
                mark_group_event_sent(group)
            data = __import__("json").loads(event.data_json or "{}")
            boss = data.get("boss") or {"emoji": "🐲", "name": "Босс", "hp": data.get("hp", 1)}
        await clean_answer(
            message,
            f"🐲 <b>Босс появился!</b>\n\n{boss['emoji']} <b>{h(boss['name'])}</b>\nHP: <b>{data.get('hp', boss.get('hp', 1))}</b>",
            reply_markup=boss_keyboard(event.id),
        )
    finally:
        if lock:
            lock.release()


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    if not is_admin_user(message.from_user.id if message.from_user else None):
        return
    with session_scope() as db:
        payload = admin_stats(db)
    await clean_answer(message, render_stats(payload))


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def track_group_activity(message: Message) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    try:
        with session_scope() as db:
            player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
            register_group_chat(db, message.chat.id, message.chat.title or "Чат", player)
    except Exception as exc:
        store_runtime_error("group_tracker", exc, chat_id=message.chat.id, user_id=message.from_user.id)



@router.callback_query(F.data == "cap:menu")
async def cb_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await clean_answer(callback.message, "🏠 <b>Меню Капсуликов</b>", reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:more")
async def cb_more(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await clean_answer(callback.message, "⋯ <b>Ещё</b>", reply_markup=more_keyboard())


@router.callback_query(F.data == "cap:quests")
async def cb_quests(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = quest_payload(db, player)
        await clean_answer(callback.message, render_quests(payload), reply_markup=quests_keyboard())


@router.callback_query(F.data == "cap:quests_claim")
async def cb_quests_claim(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text, payload = claim_quests(db, player)
        await clean_answer(callback.message, ("✅ " if ok else "⛔ ") + h(text) + "\n\n" + render_quests(payload), reply_markup=quests_keyboard())


@router.callback_query(F.data == "cap:daily")
async def cb_daily(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = daily_reward_payload(db, player)
        await clean_answer(callback.message, render_daily(payload), reply_markup=daily_keyboard())


@router.callback_query(F.data == "cap:daily_claim")
async def cb_daily_claim(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text, payload = claim_daily_reward(db, player)
        await clean_answer(callback.message, ("✅ " if ok else "⛔ ") + h(text) + "\n\n" + render_daily(payload), reply_markup=daily_keyboard())


@router.callback_query(F.data == "cap:ref")
async def cb_ref(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        bot_user = await callback.message.bot.get_me()
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = referral_payload(player, bot_user.username)
        await clean_answer(callback.message, render_referral(payload), reply_markup=ref_keyboard())


@router.callback_query(F.data == "cap:season")
async def cb_season(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = season_payload(db, player)
        await clean_answer(callback.message, render_season(payload), reply_markup=season_keyboard())


@router.callback_query(F.data == "cap:season_top")
async def cb_season_top(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        with session_scope() as db:
            items = season_top(db)
        await clean_answer(callback.message, render_season_top(items), reply_markup=season_keyboard())


@router.callback_query(F.data == "cap:donate")
async def cb_donate(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = stars_shop_payload(player)
        await clean_answer(callback.message, render_stars_shop(payload), reply_markup=stars_keyboard())


@router.callback_query(F.data.startswith("cap:buy:"))
async def cb_buy_stars(callback: CallbackQuery) -> None:
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        await callback.answer("Не получилось.", show_alert=True)
        return
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("Покупку лучше открыть в личке бота.", show_alert=True)
        bot_user = await callback.message.bot.get_me()
        await clean_answer(callback.message, f"⭐ Донат открывается в личке: @{h(bot_user.username or 'CapsulikiBot')}")
        return
    settings = get_settings()
    if not settings.stars_enabled:
        await callback.answer("Донат пока выключен.", show_alert=True)
        return

    product_key = callback.data.split(":")[-1]
    product = get_star_product(product_key)
    if not product:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        payload = build_star_payload(player, product_key)

    await callback.answer()
    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=product["title"],
        description=product["description"],
        payload=payload,
        provider_token="",
        currency=settings.stars_currency,
        prices=[LabeledPrice(label=product["title"], amount=int(product["stars"]))],
    )


@router.callback_query(F.data == "cap:payments")
async def cb_payments(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            items = purchase_history_payload(db, player)
        await clean_answer(callback.message, render_payment_history(items), reply_markup=stars_keyboard())





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
        await clean_answer(callback.message, text, reply_markup=main_keyboard())


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
        await clean_answer(callback.message, text, reply_markup=capsule_keyboard())


@router.callback_query(F.data == "cap:shop")
async def cb_shop(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = shop_payload(player)
        await clean_answer(callback.message, render_shop(payload), reply_markup=shop_keyboard())


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
        if not ok and "нет" in text.lower():
            await callback.answer(text, show_alert=True)
            return
        await clean_answer(callback.message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())



@router.callback_query(F.data == "cap:profile")
async def cb_profile(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = profile_payload(db, player)
        await clean_answer(callback.message, render_profile(payload), reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:my")
async def cb_my(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user and isinstance(callback.message, Message):
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            payload = collection_payload(db, player)
        await clean_answer(callback.message, render_collection(payload), reply_markup=main_keyboard())


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
        await clean_answer(callback.message, render_pet(payload), reply_markup=pet_keyboard())


@router.callback_query(F.data.startswith("cap:care_menu:"))
async def cb_care_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    try:
        pet_id = int(callback.data.split(":")[-1])
    except ValueError:
        pet_id = 0
    await clean_answer(callback.message, "🍖 <b>Уход за питомцем</b>", reply_markup=care_keyboard(pet_id))


@router.callback_query(F.data.startswith("cap:care:"))
async def cb_care(callback: CallbackQuery) -> None:
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        await callback.answer("Не получилось.", show_alert=True)
        return
    _, _, action, raw_pet_id = callback.data.split(":")
    pet_id = int(raw_pet_id) if raw_pet_id and raw_pet_id != "0" else None
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text, payload = care_pet(db, player, action, pet_id)
    if not ok and "не твой" in text.lower():
        await callback.answer(text, show_alert=True)
        return
    await callback.answer()
    await clean_answer(callback.message, ("✅ " if ok else "⛔ ") + h(text) + ("\n\n" + render_pet(payload) if payload else ""), reply_markup=pet_keyboard(payload["id"] if payload else None))


@router.callback_query(F.data == "cap:expeditions")
async def cb_expeditions(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await clean_answer(callback.message, render_expeditions(expedition_payload()), reply_markup=expedition_keyboard())


@router.callback_query(F.data.startswith("cap:exp:"))
async def cb_start_exp(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        return
    key = callback.data.split(":")[-1]
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text, _ = start_expedition(db, player, key)
    await clean_answer(callback.message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:exp_finish")
async def cb_exp_finish(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
        ok, text = finish_expedition(db, player)
    await clean_answer(callback.message, text, reply_markup=main_keyboard())


@router.callback_query(F.data == "cap:top")
async def cb_top(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        with session_scope() as db:
            items = leaderboard(db)
        await clean_answer(callback.message, render_top(items), reply_markup=main_keyboard())


@router.callback_query(F.data.startswith("cap:catch:"))
async def cb_catch(callback: CallbackQuery) -> None:
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        await callback.answer("Не получилось.", show_alert=True)
        return
    event_id = int(callback.data.split(":")[-1])
    lock = acquire_redis_lock(f"cap:event:action:{event_id}", ttl_seconds=8)
    if lock and not lock.acquired:
        await callback.answer("Событие уже обрабатывается, жми без турбо-режима 😄", show_alert=False)
        return
    try:
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text, pet = catch_group_pet(db, callback.message.chat.id, player, event_id)
            payload = pet_payload(pet) if pet else None
        await callback.answer("Готово")
        if ok and payload:
            await answer_with_pet_media(callback.message, render_catch_card(player.first_name or "Игрок", payload), payload)
            return
        await clean_answer(callback.message, text)
    finally:
        if lock:
            lock.release()


@router.callback_query(F.data.startswith("cap:boss_hit:"))
async def cb_boss_hit(callback: CallbackQuery) -> None:
    if not callback.from_user or not isinstance(callback.message, Message) or not callback.data:
        await callback.answer("Не получилось.", show_alert=True)
        return
    event_id = int(callback.data.split(":")[-1])
    lock = acquire_redis_lock(f"cap:event:action:{event_id}", ttl_seconds=8)
    if lock and not lock.acquired:
        await callback.answer("Удар уже считается. Босс в шоке, сервер тоже 😄", show_alert=False)
        return
    try:
        with session_scope() as db:
            player, _ = get_or_create_player(db, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
            ok, text, data = hit_boss(db, callback.message.chat.id, player, event_id)
        await callback.answer()
        hp_line = ""
        if data and data.get("hp", 0) > 0:
            hp_line = f"\nHP босса: <b>{data['hp']}</b>/<b>{data['max_hp']}</b>"
        await clean_answer(callback.message, text + hp_line, reply_markup=boss_keyboard(event_id) if data and data.get("hp", 0) > 0 else None)
    finally:
        if lock:
            lock.release()


@router.errors()
async def on_router_error(event: ErrorEvent) -> bool:
    exc = event.exception
    chat_id = None
    user_id = None
    update_json = None
    try:
        update = event.update
        update_json = update.model_dump_json(exclude_none=True) if hasattr(update, "model_dump_json") else str(update)
        message = getattr(update, "message", None)
        callback = getattr(update, "callback_query", None)
        if callback and getattr(callback, "from_user", None):
            user_id = callback.from_user.id
            if getattr(callback, "message", None):
                message = callback.message
        if message and getattr(message, "chat", None):
            chat_id = message.chat.id
        if message and getattr(message, "from_user", None):
            user_id = message.from_user.id
    except Exception:
        pass
    store_runtime_error("router", exc, chat_id=chat_id, user_id=user_id, update_json=update_json)
    if get_settings().admin_notify_errors:
        try:
            await notify_admins(
                event.bot,
                f"⚠️ <b>Ошибка бота</b>\nТип: <code>{h(exc.__class__.__name__)}</code>\nChat: <code>{chat_id}</code>\nUser: <code>{user_id}</code>",
            )
        except Exception:
            logger.debug("error admin notify failed", exc_info=True)
    logger.exception("Router error stored", exc_info=exc)
    return True


async def group_event_loop(bot: Bot) -> None:
    settings = get_settings()
    await asyncio.sleep(5)
    while True:
        poll_seconds = max(20, int(settings.group_event_poll_seconds))
        try:
            loop_lock = acquire_redis_lock("cap:events:loop", ttl_seconds=max(60, poll_seconds * 2))
            if loop_lock and not loop_lock.acquired:
                await asyncio.sleep(poll_seconds)
                continue

            jobs: list[tuple[str, int, str, int]] = []
            try:
                with session_scope() as db:
                    runtime_interval = get_config_int(db, "group_event_interval_minutes", settings.group_event_interval_minutes)
                    batch_size = max(1, get_config_int(db, "group_event_batch_size", settings.group_event_batch_size))
                    max_events_per_group = max(1, min(2, get_config_int(db, "group_events_per_group", settings.group_events_per_group)))
                    boss_cooldown_hours = max(1, get_config_int(db, "group_boss_interval_hours", settings.group_boss_interval_hours))
                    expire_old_group_events(db)

                    groups = group_chats_for_events(db, limit=batch_size, min_minutes=runtime_interval)
                    for group in groups:
                        if group.messages_seen < 3 or group.players_seen < 1:
                            continue

                        group_lock = acquire_redis_lock(
                            f"cap:events:group:{group.chat_id}",
                            ttl_seconds=max(30, int(settings.group_event_lock_seconds)),
                        )
                        if group_lock and not group_lock.acquired:
                            continue
                        try:
                            active_catch = active_group_event(db, group.chat_id, "catch")
                            active_boss = active_group_event(db, group.chat_id, "boss")
                            active_count = int(active_catch is not None) + int(active_boss is not None)
                            free_slots = max(0, max_events_per_group - active_count)
                            if free_slots <= 0:
                                continue

                            candidates: list[str] = []
                            if active_catch is None:
                                candidates.append("catch")
                            if active_boss is None:
                                last_boss_at = last_group_event_at(db, group.chat_id, "boss")
                                if last_boss_at is None or last_boss_at <= utcnow() - timedelta(hours=boss_cooldown_hours):
                                    candidates.append("boss")
                            if not candidates:
                                continue

                            if max_events_per_group == 1 and len(candidates) > 1:
                                candidates = ["catch" if __import__("random").random() < 0.72 else "boss"]
                            else:
                                candidates = candidates[:free_slots]

                            created = 0
                            for kind in candidates:
                                if kind == "catch":
                                    event = spawn_catch_event(db, group.chat_id, group.title)
                                    data = __import__("json").loads(event.data_json or "{}")
                                    species = data.get("species") or {"emoji": "✨", "name": "Капсулик"}
                                    text = (
                                        f"✨ <b>В чат залетел редкий капсулик!</b>\n\n"
                                        f"{species['emoji']} <b>{h(species['name'])}</b>\n"
                                        f"Кто успеет — попробует поймать."
                                    )
                                    jobs.append(("catch", group.chat_id, text, event.id))
                                    created += 1
                                elif kind == "boss":
                                    event = spawn_boss_event(db, group.chat_id, group.title)
                                    data = __import__("json").loads(event.data_json or "{}")
                                    boss = data.get("boss") or {"emoji": "🐲", "name": "Босс", "hp": data.get("hp", 1)}
                                    text = f"🐲 <b>Босс появился!</b>\n\n{boss['emoji']} <b>{h(boss['name'])}</b>\nHP: <b>{data.get('hp', boss.get('hp', 1))}</b>"
                                    jobs.append(("boss", group.chat_id, text, event.id))
                                    created += 1
                            if created:
                                mark_group_event_sent(group)
                        finally:
                            if group_lock:
                                group_lock.release()
            finally:
                if loop_lock:
                    loop_lock.release()

            for kind, chat_id, text, event_id in jobs:
                try:
                    if kind == "catch":
                        await bot.send_message(chat_id, text, reply_markup=catch_keyboard(event_id))
                    else:
                        await bot.send_message(chat_id, text, reply_markup=boss_keyboard(event_id))
                except Exception as exc:
                    store_runtime_error("group_event_send", exc, chat_id=chat_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            store_runtime_error("group_event_loop", exc)
            logger.exception("group event loop failed")
        await asyncio.sleep(poll_seconds)



@router.callback_query(F.data.startswith("admin:"))
async def cb_admin_dashboard(callback: CallbackQuery) -> None:
    if not is_admin_user(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    key = callback.data.split(":", 1)[1]
    with session_scope() as db:
        if key == "dashboard":
            await clean_answer(callback.message, render_admin_dashboard(admin_dashboard_payload(db)), reply_markup=admin_keyboard())
        elif key == "revenue":
            await clean_answer(callback.message, render_admin_revenue(admin_revenue_payload(db)), reply_markup=admin_keyboard())
        elif key == "products":
            await clean_answer(callback.message, render_admin_products(admin_products_payload(db)), reply_markup=admin_keyboard())
        elif key == "donors":
            await clean_answer(callback.message, render_admin_donors(admin_top_donors_payload(db)), reply_markup=admin_keyboard())
        elif key == "refs":
            await clean_answer(callback.message, render_admin_refs(admin_referrals_payload(db)), reply_markup=admin_keyboard())
        elif key == "economy":
            await clean_answer(callback.message, render_admin_economy(admin_economy_payload(db)), reply_markup=admin_keyboard())
        elif key == "users":
            await clean_answer(callback.message, render_admin_users(admin_users_payload(db)), reply_markup=admin_keyboard())
        elif key == "health":
            await clean_answer(callback.message, render_admin_health(admin_health_payload(db)), reply_markup=admin_keyboard())
        elif key == "config":
            await clean_answer(callback.message, render_admin_config(admin_config_payload(db)), reply_markup=admin_keyboard())
        elif key == "banned":
            await clean_answer(callback.message, render_banned_players(banned_players_payload(db)), reply_markup=admin_keyboard())
        else:
            await clean_answer(callback.message, "Неизвестный раздел админки.", reply_markup=admin_keyboard())



@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    product_key, player_id = __import__("app.game", fromlist=["parse_star_payload"]).parse_star_payload(pre_checkout.invoice_payload)
    product = get_star_product(product_key or "")
    if not product:
        await pre_checkout.answer(ok=False, error_message="Товар не найден.")
        return
    if int(pre_checkout.total_amount) != int(product["stars"]):
        await pre_checkout.answer(ok=False, error_message="Сумма не совпадает.")
        return
    with session_scope() as db:
        player, _ = get_or_create_player(db, pre_checkout.from_user.id, pre_checkout.from_user.username, pre_checkout.from_user.first_name)
        if player.id != player_id:
            await pre_checkout.answer(ok=False, error_message="Оплата не принадлежит этому аккаунту.")
            return
        if int(getattr(player, "is_banned", 0) or 0) == 1:
            await pre_checkout.answer(ok=False, error_message="Аккаунт заблокирован.")
            return
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    if not message.from_user or not message.successful_payment:
        return
    payment = message.successful_payment
    with session_scope() as db:
        player, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
        ok, text, payload = apply_star_purchase(
            db,
            telegram_user_id=message.from_user.id,
            payload=payment.invoice_payload,
            stars_amount=int(payment.total_amount),
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
        )
    await clean_answer(message, ("✅ " if ok else "⛔ ") + h(text), reply_markup=main_keyboard())
    if ok and get_settings().admin_notify_payments:
        try:
            amount = int(payment.total_amount)
            await notify_admins(
                message.bot,
                f"⭐ <b>Новая оплата</b>\nИгрок: <code>{message.from_user.id}</code>\nСумма: <b>{amount}⭐</b>\n{text}",
            )
        except Exception:
            logger.debug("payment admin notify failed", exc_info=True)



async def run_bot_polling() -> None:
    settings = get_settings()
    if not settings.has_bot_token:
        logger.warning("BOT_TOKEN is empty. Polling disabled.")
        return
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(SafetyMiddleware())
    dp.callback_query.middleware(SafetyMiddleware())
    dp.callback_query.middleware(CallbackThrottleMiddleware())
    dp.include_router(router)
    task: asyncio.Task | None = None
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await setup_bot_commands(bot)
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
        close_redis()
        await bot.session.close()
