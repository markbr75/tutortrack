from config.celery import QUEUES, app


def test_every_routed_queue_is_declared():
    # A worker without -Q consumes the declared queues; an undeclared route would never run.
    routed = {route["queue"] for route in app.conf.task_routes.values()}
    assert routed | {app.conf.task_default_queue} <= set(QUEUES)
    assert [q.name for q in app.conf.task_queues] == list(QUEUES)
    # Distinct bindings, or a task sent to one queue would be delivered to all of them.
    queues = app.amqp.queues.values()  # as Celery resolves them, defaults filled in
    assert len({(q.exchange.name, q.routing_key) for q in queues}) == len(QUEUES)


def test_a_routed_task_is_published_to_its_own_queue_only():
    from tutortrack.core.events.tasks import dispatch_outbox

    route = app.amqp.router.route({}, dispatch_outbox.name)
    assert route["queue"].name == "outbox"
    assert (route["queue"].exchange.name, route["queue"].routing_key) == ("outbox", "outbox")
