import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError

from tutortrack.identity.models import User

pytestmark = pytest.mark.django_db


def test_create_user_normalises_email_and_hashes_password():
    user = User.objects.create_user("  Jane.Doe@Example.COM ", "s3cret-pass-phrase")
    assert user.email == "jane.doe@example.com"
    assert user.check_password("s3cret-pass-phrase")
    assert not user.is_staff
    assert not user.is_platform_staff


def test_create_superuser_is_platform_staff():
    admin = User.objects.create_superuser("ops@tutortrack.app", "pw-123456789")
    assert admin.is_superuser
    assert admin.is_staff
    assert admin.is_platform_staff


def test_email_is_required():
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("", "pw")


def test_emails_are_unique_case_insensitively():
    User.objects.create_user("sam@example.com", "pw-123456789")
    with pytest.raises(IntegrityError):
        User.objects.create_user("SAM@example.com", "pw-123456789")


def test_login_is_case_insensitive():
    User.objects.create_user("priya@example.com", "pw-123456789")
    assert authenticate(username="Priya@Example.com", password="pw-123456789") is not None


def test_names():
    user = User(email="tom@example.com", first_name="Tom", last_name="Tutor")
    assert user.get_full_name() == "Tom Tutor"
    assert user.get_short_name() == "Tom"
    assert str(user) == "tom@example.com"
    assert User(email="x@example.com").get_full_name() == "x@example.com"
