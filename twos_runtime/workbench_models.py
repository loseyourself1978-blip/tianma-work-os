"""20.2 workbench storage. Additive tables; legacy records are never reparented."""
from sqlalchemy import ForeignKey, Integer, String, Text, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base


class EmailIdentity(Base):
    __tablename__ = 'wb_email_identities'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    verified_at: Mapped[str] = mapped_column(String(40))


class EmailChallenge(Base):
    __tablename__ = 'wb_email_challenges'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    flow_hash: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(160), default='')
    password_salt: Mapped[str] = mapped_column(String(80), default='')
    code_hash: Mapped[str] = mapped_column(String(64))
    issued: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(24), default='PENDING')
    reset_hash: Mapped[str] = mapped_column(String(64), default='')


class AuthThrottle(Base):
    __tablename__ = 'wb_auth_throttles'
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    window: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)


class Chat(Base):
    __tablename__ = 'wb_chats'
    __table_args__ = (UniqueConstraint('owner_id', 'request_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('r2_project_spaces.project_id'), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text, default='')
    draft: Mapped[str] = mapped_column(Text, default='')
    draft_version: Mapped[int] = mapped_column(Integer, default=0)
    draft_attachments: Mapped[str] = mapped_column(Text, default='[]')
    created_at: Mapped[str] = mapped_column(String(40))


class ChatMessage(Base):
    __tablename__ = 'wb_chat_messages'
    __table_args__ = (UniqueConstraint('chat_id', 'request_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey('wb_chats.id'), index=True)
    request_id: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24))
    binding: Mapped[str] = mapped_column(String(64), default='')
    context_json: Mapped[str] = mapped_column(Text, default='{}')
    evidence_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[str] = mapped_column(String(40))


class ChatAttachment(Base):
    __tablename__ = 'wb_chat_attachments'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey('wb_chats.id'), index=True)
    name: Mapped[str] = mapped_column(String(240))
    mime: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    extracted: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(40))


class ChatHandoff(Base):
    __tablename__ = 'wb_chat_handoffs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey('wb_chats.id'), index=True)
    work_id: Mapped[str] = mapped_column(ForeignKey('r2_work_items.id'), unique=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class Delivery(Base):
    """A user-visible specification and its continuous Codex delivery."""
    __tablename__ = 'wb_deliveries'
    __table_args__ = (UniqueConstraint('chat_id', 'source_message_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey('wb_chats.id'), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True)
    source_message_id: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(32), default='PROPOSED')
    specification_json: Mapped[str] = mapped_column(Text)
    configuration_json: Mapped[str] = mapped_column(Text, default='{}')
    context_json: Mapped[str] = mapped_column(Text, default='{}')
    approval_json: Mapped[str] = mapped_column(Text, default='{}')
    thread_id: Mapped[str] = mapped_column(String(100), default='')
    turn_id: Mapped[str] = mapped_column(String(100), default='')
    phase: Mapped[str] = mapped_column(String(24), default='execution')
    output: Mapped[str] = mapped_column(Text, default='')
    review: Mapped[str] = mapped_column(Text, default='')
    error_code: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class DeliveryEvent(Base):
    __tablename__ = 'wb_delivery_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey('wb_deliveries.id'), index=True)
    kind: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
