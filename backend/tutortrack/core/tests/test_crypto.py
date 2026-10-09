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


def test_empty_values_round_trip_and_tax_numbers_are_encrypted(db):
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.tests.factories import OrganisationFactory

    blank = OrganisationFactory(slug="blank-co")
    assert Organisation.objects.get(pk=blank.pk).tax_number == ""
    taxed = OrganisationFactory(slug="taxed-co", tax_number="UTR 12345 67890")
    with connection.cursor() as cursor:
        cursor.execute("SELECT tax_number FROM tenancy_organisation WHERE id = %s", [taxed.pk])
        assert "12345" not in cursor.fetchone()[0]
    assert Organisation.objects.get(pk=taxed.pk).tax_number == "UTR 12345 67890"


def test_kms_wrapped_keys_are_unwrapped_once(settings):
    import base64

    import boto3
    from moto import mock_aws

    from tutortrack.core import kms

    with mock_aws():
        client = boto3.client("kms", region_name="eu-west-2")
        key_id = client.create_key()["KeyMetadata"]["KeyId"]
        _, wrapped = kms.generate_data_key(key_id)
        settings.FIELD_ENCRYPTION_KMS_KEY_ID = key_id
        settings.FIELD_ENCRYPTION_KEYS = [wrapped]
        kms.clear_cache()
        token = crypto.encrypt("secret")
        assert crypto.decrypt(token) == "secret"
        # The wrapped form in configuration is not the key itself.
        assert base64.b64decode(wrapped) != kms.unwrap(wrapped)
    kms.clear_cache()


def test_rotation_command_reports_every_encrypted_field(db, settings):
    from io import StringIO

    from django.core.management import call_command

    MFADevice.objects.create(user=UserFactory(), secret="ROTATE-ME")
    settings.FIELD_ENCRYPTION_KEYS = [
        Fernet.generate_key().decode(),
        *settings.FIELD_ENCRYPTION_KEYS,
    ]
    out = StringIO()
    call_command("rotate_encryption_keys", "--database", "default", stdout=out)
    assert "identity.MFADevice.secret: 1" in out.getvalue()
    assert "tenancy.Organisation.tax_number" in out.getvalue()
