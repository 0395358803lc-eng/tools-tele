from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token

_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_system_scope: ContextVar[bool] = ContextVar("tenant_system_scope", default=False)


def current_tenant_id() -> str | None:
    return _tenant_id.get()


def in_system_scope() -> bool:
    return bool(_system_scope.get())


def set_tenant_id(user_id: str | None) -> Token:
    return _tenant_id.set(str(user_id) if user_id else None)


def reset_tenant_id(token: Token) -> None:
    _tenant_id.reset(token)


def require_tenant_id() -> str:
    value = current_tenant_id()
    if not value:
        raise RuntimeError("Missing tenant context")
    return value

@contextmanager
def tenant_scope(user_id: str):
    token = set_tenant_id(user_id)
    system_token = _system_scope.set(False)
    try:
        yield str(user_id)
    finally:
        _system_scope.reset(system_token)
        reset_tenant_id(token)


@contextmanager
def system_scope():
    token = _system_scope.set(True)
    tenant_token = _tenant_id.set(None)
    try:
        yield
    finally:
        _tenant_id.reset(tenant_token)
        _system_scope.reset(token)
