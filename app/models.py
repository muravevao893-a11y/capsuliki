from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Rarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"


class EventStatus(StrEnum):
    ACTIVE = "active"
    FINISHED = "finished"


class TradeStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_name: Mapped[str] = mapped_column(String(120), default="Игрок", nullable=False)

    coins: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    crystals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capsule_dust: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capsules_opened: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    favorite_pet_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    referrer_player_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    referrals_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    season_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    is_banned: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Pet(Base):
    __tablename__ = "pets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)

    species_key: Mapped[str] = mapped_column(String(80), nullable=False)
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    rarity: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    element: Mapped[str] = mapped_column(String(40), nullable=False)
    character: Mapped[str] = mapped_column(String(80), nullable=False)
    skill: Mapped[str] = mapped_column(String(160), nullable=False)

    nickname: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    power: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    hunger: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    mood: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    clean: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, default=80, nullable=False)

    locked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    obtained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Expedition(Base):
    __tablename__ = "expeditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), nullable=False, index=True)
    location_key: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finishes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class GroupEvent(Base):
    __tablename__ = "group_events"
    __table_args__ = (Index("ix_group_events_chat_status", "chat_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_title: Mapped[str] = mapped_column(String(255), default="Чат", nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=EventStatus.ACTIVE.value, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finishes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_target_status", "target_player_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposer_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    target_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    offer_pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), nullable=False)
    want_pet_id: Mapped[int | None] = mapped_column(ForeignKey("pets.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=TradeStatus.PENDING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GroupChat(Base):
    __tablename__ = "group_chats"
    __table_args__ = (
        Index("ix_group_chats_status_last_event", "status", "last_event_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="Чат", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    players_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ErrorLog(Base):
    __tablename__ = "error_logs"
    __table_args__ = (
        Index("ix_error_logs_created", "created_at"),
        Index("ix_error_logs_chat_created", "chat_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), default="bot", nullable=False)
    error_type: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    update_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)




class StarPurchase(Base):
    __tablename__ = "star_purchases"
    __table_args__ = (
        Index("ix_star_purchases_player_created", "player_id", "created_at"),
        Index("ix_star_purchases_payload", "payload"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[str] = mapped_column(String(120), nullable=False)
    product_key: Mapped[str] = mapped_column(String(80), nullable=False)
    stars_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="paid", nullable=False)
    reward_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)




class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
