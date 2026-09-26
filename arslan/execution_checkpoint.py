"""Optional durable admission hook, bound by the trusted task runtime.

Providers share this boundary without importing server persistence. The callback
receives a reason code only, never credentials, request headers or prompt text.
"""
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar

_hook: ContextVar[Callable[[str], Awaitable[None]] | None] = ContextVar("execution_checkpoint", default=None)


@contextmanager
def bind(callback: Callable[[str], Awaitable[None]]):
    token = _hook.set(callback)
    try:
        yield
    finally:
        _hook.reset(token)


async def save(reason: str):
    callback = _hook.get()
    if callback is not None:
        await callback(reason)


def clear_in(context):
    context.run(_hook.set, None)
