# Realtime notifications (Server-Sent Events)

The bell in the admin app subscribes to `GET /api/v1/notifications/stream` (gap batch G4,
FR-13-8, ADR 0038). This runbook says what the stream needs in production. The deploy is
not changed yet: today the web service runs gunicorn with sync WSGI workers, and the bell
falls back to its 30-second poll.

## How it works

1. A service creates an in-app notification (or marks some read).
2. After the transaction commits, `comms.realtime` publishes a small JSON message (ids,
   title, link; no bodies or addresses) on the Redis channel
   `comms:inapp:<organisation id>:<user id>`.
3. Each open stream subscribes to its own user's channel in the organisation of the
   request, and sends `ready`, `notification` and `read` events, plus a `: keep-alive`
   comment every 20 seconds.
4. A stream ends after 5 minutes (`COMMS["SSE_MAX_SECONDS"]`); the browser reconnects after
   the `retry:` delay (5 seconds). If the stream fails or reports `unavailable`, the bell
   polls `/notifications/unread-count` every 30 seconds and tries the stream again a minute
   later.

## What production needs

- **An ASGI server for the web service.** Under WSGI every open stream holds a worker thread
  for up to 5 minutes, so a few dozen open admin tabs would use all the workers. Under ASGI
  the view returns an async generator (`redis.asyncio`), and an open stream holds no thread.
  `config/asgi.py` is ready. To switch (a later change, with load testing):
  1. Add `uvicorn[standard]` to `backend/pyproject.toml` (it is not a dependency today).
  2. Run the web container with
     `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker --workers 4 --bind 0.0.0.0:8000`.
  3. Keep `CONN_MAX_AGE` at 0 under ASGI, or use a connection pooler (PgBouncer/RDS Proxy):
     Django opens a database connection per async-to-sync thread.
- **The load balancer and CloudFront must not buffer or time out the stream.** Set the ALB
  idle timeout above the keep-alive interval (60 seconds or more; the default 60 is enough
  with 20-second keep-alives). The response sets `Cache-Control: no-cache, no-transform` and
  `X-Accel-Buffering: no`; add a CloudFront behaviour for `/api/v1/notifications/stream`
  with caching off and compression off.
- **Redis** (already used for Celery and locks). Pub/sub messages are not stored: a
  notification published while a tab is reconnecting is not lost, because the `ready` event
  carries the current unread count and the bell refetches.

## Checks

- `curl -N -H 'Accept: text/event-stream' -b <session cookie> https://<org>.tutortrack.app/api/v1/notifications/stream`
  shows `event: ready` straight away and `: keep-alive` every 20 seconds.
- Assign yourself a task in another tab: an `event: notification` line arrives within a
  second.
- `redis-cli PUBSUB NUMSUB comms:inapp:<org>:<user>` shows the open streams for a user.

## If it goes wrong

- **Workers exhausted after enabling it on WSGI:** roll back the web service (see
  `rollback.md`); the bell keeps working by polling.
- **Streams drop every minute:** a proxy idle timeout is shorter than the keep-alive; raise
  it, or lower `COMMS["SSE_HEARTBEAT_SECONDS"]`.
- **No events but polling works:** check that the web service and the Celery workers use the
  same `REDIS_URL` (notifications created by background tasks publish from the worker).
