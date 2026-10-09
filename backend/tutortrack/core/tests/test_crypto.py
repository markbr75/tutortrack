from cryptography.fernet import Fernet
from django.db import connection

from tutortrack.core import crypto
from tutortrack.identity.models import MFADevice
from tutortrack.identity.tests.factories import UserFactory


def test_encrypt_round_trip_and_randomised_ciphertext():
    a, b = crypto.encrypt("secret"), crypto.encrypt("secret")
    assert a != b
    assert crypto.decrypt(a) == crypto.decrypt(b) == "secret"


def test_field_is_encrypted_at_rest(db):
    device = MFADevice.objects.create(user=UserFactory(), secret="JBSWY3DPEHPK3PXP")
    with connection.cursor() as cursor:
        cursor.execute("SELECT secret FROM identity_mfadevice WHERE id = %s", [device.pk])
        stored = cursor.fetchone()[0]
    assert "JBSWY3DPEHPK3PXP" not in stored
    assert MFADevice.objects.get(pk=device.pk).secret == "JBSWY3DPEHPK3PXP"


def test_key_rotation(db, settings):
    old_key = settings.FIELD_ENCRYPTION_KEYS[0]
    device = MFADevice.objects.create(user=UserFactory(), secret="ROTATE")
    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [new_key, old_key]
    assert MFADevice.objects.get(pk=device.pk).secret == "ROTATE"  # old key still decrypts
    assert crypto.rotate_field(MFADevice, "secret") == 1
    settings.FIELD_ENCRYPTION_KEYS = [new_key]
    assert MFADevice.objects.get(pk=device.pk).secret == "ROTATE"
