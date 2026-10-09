import socket
import struct
import threading
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from tutortrack.core.models import FeatureFlag
from tutortrack.core.storage.clamav import scan_stream
from tutortrack.identity.models import User
from tutortrack.tenancy.models import Organisation


@pytest.mark.django_db
def test_seed_demo_is_idempotent(settings):
    settings.DEBUG = True
    for _ in range(2):
        call_command("seed_demo", stdout=StringIO())
    assert User.objects.filter(email="admin@tutortrack.localhost", is_superuser=True).count() == 1
    assert Organisation.objects.get(slug="brightminds").name == "Bright Minds Tutoring"
    assert FeatureFlag.objects.filter(key="courses").exists()
    from tutortrack.core.context import tenant_context
    from tutortrack.crm.models import Task
    from tutortrack.people.models import Client, TutorProfile

    with tenant_context(Organisation.objects.get(slug="brightminds")):
        assert Client.objects.count() == 3
        assert TutorProfile.objects.count() == 2
        assert Task.objects.count() == 1


@pytest.mark.django_db
def test_seed_demo_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo", stdout=StringIO())


def test_ensure_storage_bucket_creates_once(s3, settings):
    s3.delete_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
    out = StringIO()
    call_command("ensure_storage_bucket", stdout=out)
    call_command("ensure_storage_bucket", stdout=out)
    assert "Created bucket" in out.getvalue()
    assert "exists" in out.getvalue()


def _fake_clamd(reply: bytes) -> tuple[int, list[bytes]]:
    """Minimal clamd stand-in: reads one INSTREAM and replies."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received: list[bytes] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            assert conn.recv(10) == b"zINSTREAM\0"
            while True:
                (size,) = struct.unpack("!L", conn.recv(4))
                if size == 0:
                    break
                data = b""
                while len(data) < size:
                    data += conn.recv(size - len(data))
                received.append(data)
            conn.sendall(reply + b"\0")
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1], received


def test_scan_stream_speaks_instream_protocol():
    port, received = _fake_clamd(b"stream: OK")
    result = scan_stream([b"hello ", b"world"], host="127.0.0.1", port=port, timeout=5)
    assert result.clean
    assert b"".join(received) == b"hello world"

    port, _ = _fake_clamd(b"stream: Eicar-Test-Signature FOUND")
    result = scan_stream([b"X5O!P%"], host="127.0.0.1", port=port, timeout=5)
    assert not result.clean
    assert result.signature == "Eicar-Test-Signature"
