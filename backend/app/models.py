from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .time_utils import utcnow



class Account(Base):
    __tablename__ = "accounts"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        Index("uq_accounts_user_phone", "user_id", "phone", unique=True),
        Index("ix_accounts_status", "status"),
        Index("ix_accounts_tg_user_id", "tg_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    first_name: Mapped[str] = mapped_column(String(64), default="")
    last_name: Mapped[str] = mapped_column(String(64), default="")
    username: Mapped[str] = mapped_column(String(64), default="")
    bio: Mapped[str] = mapped_column(String(140), default="")
    session_file: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    has_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    flood_wait_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["SecurityMessage"]] = relationship(
        back_populates="account", cascade="all,delete-orphan"
    )
    telegram_sessions: Mapped[list["TelegramSession"]] = relationship(
        back_populates="account", cascade="all,delete-orphan"
    )


class TelegramSession(Base):
    __tablename__ = "telegram_sessions"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("account_id", "session_file", name="uq_tg_session_account_file"),
        Index("ix_tg_sessions_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    session_file: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)

    account: Mapped["Account"] = relationship(back_populates="telegram_sessions")


class SecurityMessage(Base):
    __tablename__ = "security_messages"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("account_id", "tg_msg_id", name="uq_security_account_msg"),
        Index("ix_security_received_at", "received_at"),
        Index("ix_security_is_read", "is_read"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    tg_msg_id: Mapped[int] = mapped_column(BigInteger)
    message_text: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32), default="unknown")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="messages")


class GoneAccount(Base):
    __tablename__ = "gone_accounts"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    first_name: Mapped[str] = mapped_column(String(64), default="")
    last_name: Mapped[str] = mapped_column(String(64), default="")
    username: Mapped[str] = mapped_column(String(64), default="")
    old_serial: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(32), default="removed")
    gone_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EncryptedSecret(Base):
    __tablename__ = "encrypted_secrets"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSession(Base):
    __tablename__ = "app_sessions"
    __table_args__ = (Index("ix_app_sessions_expires_at", "expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ip: Mapped[str] = mapped_column(String(128), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_ip_time", "ip", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(128))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccountStatusHistory(Base):
    __tablename__ = "account_status_history"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (Index("ix_status_history_account_time", "account_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BulkJob(Base):
    __tablename__ = "bulk_jobs"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (Index("ix_bulk_jobs_status", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    pending: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runner_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class BulkJobItem(Base):
    __tablename__ = "bulk_job_items"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("job_id", "account_id", name="uq_bulk_job_account"),
        Index("ix_bulk_job_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("bulk_jobs.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MessageDispatchItem(Base):
    __tablename__ = "message_dispatch_items"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("job_id", "normalized_target", name="uq_message_dispatch_job_target"),
        Index("ix_message_dispatch_items_status", "status"),
        Index("ix_message_dispatch_items_job_account", "job_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("bulk_jobs.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target: Mapped[str] = mapped_column(String(255))
    normalized_target: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PhoneCheckItem(Base):
    __tablename__ = "phone_check_items"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("job_id", "dedupe_key", name="uq_phone_check_job_phone"),
        Index("ix_phone_check_items_status_retry", "status", "next_retry_at"),
        Index("ix_phone_check_items_job_account", "job_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("bulk_jobs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    original_phone: Mapped[str] = mapped_column(String(64))
    normalized_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    presence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleanup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PhoneCheckAccount(Base):
    __tablename__ = "phone_check_accounts"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("job_id", "account_id", name="uq_phone_check_job_account"),
        Index("ix_phone_check_accounts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("bulk_jobs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    assigned_total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    not_discoverable: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AccountProxy(Base):
    __tablename__ = "account_proxies"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (Index("ix_account_proxies_enabled", "enabled"),)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    proxy_type: Mapped[str] = mapped_column(String(16), default="socks5")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    rdns: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    fallback_proxy_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_rdns: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    active_slot: Mapped[str] = mapped_column(String(16), default="primary", server_default="primary")
    failover_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_failover_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), default="unknown", server_default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TargetCheck(Base):
    __tablename__ = "target_checks"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target: Mapped[str] = mapped_column(String(255), index=True)
    peer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TargetCheckResult(Base):
    __tablename__ = "target_check_results"
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("target_check_id", "account_id", name="uq_target_check_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_check_id: Mapped[str] = mapped_column(
        ForeignKey("target_checks.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")


TENANT_MODELS = (
    Account, TelegramSession, SecurityMessage, GoneAccount, AppSetting, EncryptedSecret,
    AccountStatusHistory, BulkJob, BulkJobItem, MessageDispatchItem, PhoneCheckItem,
    PhoneCheckAccount, AccountProxy, AuditLog, TargetCheck, TargetCheckResult,
)
TENANT_TABLE_NAMES = {model.__tablename__ for model in TENANT_MODELS}
