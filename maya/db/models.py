"""SQLAlchemy 2.0 models for Phase 1 tables (users, companions, messages)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Jerusalem")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    companions: Mapped[list[Companion]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Companion(Base):
    __tablename__ = "companions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="Maya")
    template_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="flirt")
    # Phase 3: personality blob + generated backstory (filled by genesis).
    personality: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    backstory: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="companions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="companion", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="messages_role_check"
        ),
        Index("idx_messages_companion_created", "companion_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # NOTE: DB column is "metadata"; attribute renamed because Base.metadata is reserved.
    extra: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    companion: Mapped[Companion] = relationship(back_populates="messages")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    purpose: Mapped[str | None] = mapped_column(Text)


# ───────────────────────── Phase 3: state models (§P3.1) ─────────────────────────


class EmotionalState(Base):
    __tablename__ = "emotional_state"
    __table_args__ = (
        CheckConstraint("valence BETWEEN -1 AND 1", name="emotional_valence_check"),
        CheckConstraint("arousal BETWEEN 0 AND 1", name="emotional_arousal_check"),
        CheckConstraint("dominance BETWEEN 0 AND 1", name="emotional_dominance_check"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    valence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    arousal: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    dominance: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    feelings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RelationshipState(Base):
    __tablename__ = "relationship_state"
    __table_args__ = (
        UniqueConstraint("companion_id", "user_id", name="relationship_companion_user_uq"),
        CheckConstraint(
            "intimacy_level BETWEEN 0 AND 10", name="relationship_intimacy_check"
        ),
        CheckConstraint("trust_level BETWEEN 0 AND 10", name="relationship_trust_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default="strangers")
    intimacy_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    trust_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    days_known: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_interactions: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RelationshipEvent(Base):
    __tablename__ = "relationship_events"
    __table_args__ = (
        Index(
            "idx_rel_events_companion",
            "companion_id",
            "occurred_at",
            postgresql_ops={"occurred_at": "DESC"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CompanionCommitment(Base):
    __tablename__ = "companion_commitments"
    __table_args__ = (
        Index(
            "idx_commitments_companion_active",
            "companion_id",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    commitment_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    importance: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
