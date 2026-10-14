"""Realtime in-app notifications over Server-Sent Events (G4, FR-13-1/8).

When a notification is created (or read), ``announce`` publishes a small JSON message on
the user's Redis channel ``comms:inapp:<organisation>:<user>`` once the transaction
commits. ``GET /api/v1/notifications/stream`` subscribes to that one channel and passes
the messages on as SSE events, so the bell updates without waiting for its 30-second poll.

* The channel name carries the organisation and the user, both taken from the
  authenticated request: a stream only ever sees its own user's notifications in the
  organisation of the request (tenant isolation).
* Messages carry ids, titles and links only, never message bodies, addresses or tokens.
* Under ASGI the stream is an async generator (``redis.asyncio``), so an open stream
  holds no worker thread. Under WSGI (``runserver``, the current gunicorn deploy) it is a
  plain generator that holds one thread while open; each stream ends after
  ``COMMS["SSE_MAX_SECONDS"]`` and the browser reconnects (``retry:``). Production needs
  ASGI for many open streams (see ``docs/runbooks/realtime-notifications.md``).
* Redis is best effort: if publishing fails nothing is lost (the notification is in the
  database) and the frontend falls back to polling when the stream is unavailable.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import structlog
from django.conf import settings
from django.db import transaction

logger = structlog.get_logger(__name__)

RETRY_MS = 5000


def channel_name(organisation_id: Any, user_id: Any) -> str:
    return f"comms:inapp:{organisation_id}:{user_id}"


def _setting(name: str, default: int) -> int:
    return int((getattr(settings, "COMMS", {}) or {}).get(name, default))


def max_seconds() -> int:
    return _setting("SSE_MAX_SECONDS", 300)


def heartbeat_seconds() -> int:
    return _setting("SSE_HEARTBEAT_SECONDS", 20)


def _redis() -> Any:
    from tutortrack.core import redis as core_redis

    return core_redis.get_redis()


def announce(organisation_id: Any, user_id: Any, kind: str, data: dict[str, Any]) -> None:
    """Publish ``kind`` to the user's open streams after the transaction commits."""
    channel = channel_name(organisation_id, user_id)
    payload = json.dumps({"event": kind, "data": data}, default=str)

    def send() -> None:
        try:
            _redis().publish(channel, payload)
        except Exception as exc:  # Redis down: the bell's polling picks it up
            logger.warning("comms.realtime_publish_failed", error=type(exc).__name__)

    transaction.on_commit(send)


def notification_created(row: Any) -> None:
    announce(
        row.organisation_id,
        row.user_id,
        "notification",
        {"id": str(row.pk), "type_key": row.type_key, "title": row.title, "link": row.link},
    )


def notifications_read(organisation_id: Any, user_id: Any, count: int) -> None:
    if count:
        announce(organisation_id, user_id, "read", {"count": count})


# --- the stream ---------------------------------------------------------------------------------


def frame(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


def _decode(raw: Any) -> str | None:
    """A published message as an SSE frame (None if it isn't one of ours)."""
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(message, dict) or message.get("event") not in {"notification", "read"}:
        return None
    return frame(str(message["event"]), message.get("data") or {})


def opening(unread: int) -> str:
    return f"retry: {RETRY_MS}\n\n" + frame("ready", {"unread": unread})


def sync_stream(
    channel: str, *, unread: int, seconds: int | None = None, beat: int | None = None
) -> Iterator[str]:
    """WSGI: subscribe, forward messages and send keep-alive comments until ``seconds``."""
    seconds = max_seconds() if seconds is None else seconds
    beat = heartbeat_seconds() if beat is None else beat
    yield opening(unread)
    try:
        pubsub = _redis().pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)
    except Exception as exc:
        logger.warning("comms.realtime_unavailable", error=type(exc).__name__)
        yield frame("unavailable", {})
        return
    deadline = time.monotonic() + seconds
    last = time.monotonic()
    try:
        while time.monotonic() < deadline:
            message = pubsub.get_message(timeout=min(1.0, max(deadline - time.monotonic(), 0)))
            if message and message.get("type") == "message":
                out = _decode(message.get("data"))
                if out:
                    yield out
                    last = time.monotonic()
            elif time.monotonic() - last >= beat:
                yield ": keep-alive\n\n"
                last = time.monotonic()
    except Exception as exc:
        logger.warning("comms.realtime_stream_failed", error=type(exc).__name__)
        yield frame("unavailable", {})
    finally:
        with contextlib.suppress(Exception):  # closing a broken connection
            pubsub.close()


def async_client() -> Any:
    import redis.asyncio as aioredis

    return aioredis.Redis.from_url(settings.REDIS_URL)


async def async_stream(
    channel: str, *, unread: int, seconds: int | None = None, beat: int | None = None
) -> AsyncIterator[str]:
    """ASGI: the same stream without holding a thread."""
    seconds = max_seconds() if seconds is None else seconds
    beat = heartbeat_seconds() if beat is None else beat
    yield opening(unread)
    client = async_client()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(channel)
        deadline = time.monotonic() + seconds
        last = time.monotonic()
        while time.monotonic() < deadline:
            wait = min(1.0, max(deadline - time.monotonic(), 0))
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=wait)
            if message and message.get("type") == "message":
                out = _decode(message.get("data"))
                if out:
                    yield out
                    last = time.monotonic()
            elif time.monotonic() - last >= beat:
                yield ": keep-alive\n\n"
                last = time.monotonic()
    except Exception as exc:
        logger.warning("comms.realtime_stream_failed", error=type(exc).__name__)
        yield frame("unavailable", {})
    finally:
        with contextlib.suppress(Exception):  # closing a broken connection
            await pubsub.aclose()
            await client.aclose()
