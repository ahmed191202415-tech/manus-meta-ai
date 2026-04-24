from contextvars import ContextVar


_current_meta_app_secret: ContextVar[str | None] = ContextVar("current_meta_app_secret", default=None)


def set_current_meta_app_secret(secret: str | None):
    return _current_meta_app_secret.set((secret or "").strip() or None)


def get_current_meta_app_secret() -> str | None:
    return _current_meta_app_secret.get()
