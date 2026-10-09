"""Global user identity and organisation memberships.

E01 shipped the custom user model; E02 adds ``email_verified_at`` and a minimal
``Membership`` (one built-in role key and a branch scope) because tenancy needs it for the
owner at signup, the ``X-Organisation`` header check, branch scoping and the org switcher.
E03 extends Membership with RBAC roles, invitations, MFA and SSO.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone as dj_timezone

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.ids import new_id
from tutortrack.core.models import TenantModel


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError("Users must have an email address")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def get_by_natural_key(self, username: str | None) -> User:
        return self.get(email=(username or "").strip().lower())

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_platform_staff", True)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    # Always stored lower-case (see save()), so a plain unique index is case-insensitive.
    email = models.EmailField(max_length=254, unique=True)
    first_name = models.CharField(max_length=100, blank=True, default="")
    last_name = models.CharField(max_length=100, blank=True, default="")
    timezone = models.CharField(max_length=64, default="Europe/London")
    locale = models.CharField(max_length=10, default="en-GB")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Can log in to Django admin.")
    is_platform_staff = models.BooleanField(
        default=False, help_text="TutorTrack operator with access to the platform console."
    )
    date_joined = models.DateTimeField(default=dj_timezone.now)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    preferred_name = models.CharField(max_length=100, blank=True, default="")
    pronouns = models.CharField(max_length=40, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="", help_text="E.164")
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    def __str__(self) -> str:
        return self.email

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def get_short_name(self) -> str:
        return self.preferred_name or self.first_name or self.email

    @property
    def has_mfa(self) -> bool:
        return self.mfa_devices.filter(confirmed_at__isnull=False).exists()


class Membership(TenantModel):
    """A user's place in an organisation (glossary: Membership).

    Visible to the app role for the organisation in context **and** to the member themself
    across organisations (RLS ``user_column``), which is what the org switcher needs.
    """

    class Status(models.TextChoices):
        INVITED = "invited"
        ACTIVE = "active"
        SUSPENDED = "suspended"
        REMOVED = "removed"

    class Role(models.TextChoices):
        """Built-in roles (E03 FR-03-5). E03 replaces this with Role/RolePermission rows."""

        OWNER = "owner"
        ADMIN = "admin"
        BRANCH_MANAGER = "branch_manager"
        COORDINATOR = "coordinator"
        FINANCE = "finance"
        TUTOR = "tutor"
        CLIENT = "client"
        STUDENT = "student"
        AFFILIATE = "affiliate"

    class BranchScope(models.TextChoices):
        ALL = "all"
        SELECTED = "selected"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    role = models.CharField(max_length=20, choices=Role.choices)
    branch_scope = models.CharField(
        max_length=10, choices=BranchScope.choices, default=BranchScope.ALL
    )
    branches = models.ManyToManyField(
        "tenancy.Branch", through="MembershipBranch", related_name="+", blank=True
    )
    title = models.CharField(max_length=100, blank=True, default="")
    joined_at = models.DateTimeField(null=True, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "user"], name="membership_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.organisation_id} ({self.role})"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    @property
    def is_owner_or_admin(self) -> bool:
        return self.role in {self.Role.OWNER, self.Role.ADMIN}


class MembershipBranch(TenantModel):
    """Branches a ``selected``-scope membership may see (FR-02-2 branch scoping)."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    branch = models.ForeignKey("tenancy.Branch", on_delete=models.CASCADE, related_name="+")

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "branch"], name="membership_branch_unique"
            ),
        ]


# --- invitations (FR-03-4) ------------------------------------------------------------------------


class Invitation(TenantModel):
    """An invitation to join the organisation. The token is only ever stored hashed."""

    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        REVOKED = "revoked"

    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Membership.Role.choices)
    branch_scope = models.CharField(
        max_length=10, choices=Membership.BranchScope.choices, default=Membership.BranchScope.ALL
    )
    branch_ids = models.JSONField(default=list, blank=True)
    title = models.CharField(max_length=100, blank=True, default="")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    invited_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    # The record that prompted the invitation (a Contact or Student, E05).
    target_type = models.CharField(max_length=100, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")

    audit_sensitive_fields = frozenset({"token_hash"})

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "email"],
                condition=models.Q(status="pending"),
                name="invitation_one_pending_per_email",
            )
        ]

    def __str__(self) -> str:
        return f"Invitation {self.email} ({self.role})"


# --- authentication records (global, not tenant data) -------------------------------------------


class UserSession(models.Model):
    """A signed-in browser session (FR-03-3): listed and revocable by the user."""

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auth_sessions")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    method = models.CharField(max_length=20, blank=True, default="")
    remember = models.BooleanField(default=False)
    mfa_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=dj_timezone.now)
    last_seen_at = models.DateTimeField(default=dj_timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return f"Session {self.id} for {self.user_id}"


class LoginEvent(models.Model):
    """Every sign-in attempt (FR-03-2 lockout, new-device alerts, security review)."""

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE, related_name="login_events"
    )
    email = models.EmailField(db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    device_hash = models.CharField(max_length=64, blank=True, default="")
    method = models.CharField(max_length=20)
    success = models.BooleanField()
    reason = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(default=dj_timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "-created_at"], name="login_event_email_idx")]

    def __str__(self) -> str:
        return f"{self.method} {'ok' if self.success else 'failed'} {self.email}"


class LoginToken(models.Model):
    """Single-use, short-lived sign-in token (magic link). Stored hashed."""

    class Purpose(models.TextChoices):
        MAGIC_LINK = "magic_link"

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=dj_timezone.now)

    def __str__(self) -> str:
        return f"{self.purpose} for {self.user_id}"


class MFADevice(models.Model):
    """A second factor. Phase 1: TOTP authenticator apps (WebAuthn is Phase 2)."""

    class Kind(models.TextChoices):
        TOTP = "totp"

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfa_devices")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TOTP)
    name = models.CharField(max_length=100, default="Authenticator app")
    secret = EncryptedField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_step = models.BigIntegerField(null=True, blank=True)  # blocks code replay
    created_at = models.DateTimeField(default=dj_timezone.now)

    audit_sensitive_fields = frozenset({"secret"})

    def __str__(self) -> str:
        return f"{self.kind} for {self.user_id}"


class RecoveryCode(models.Model):
    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=dj_timezone.now)

    def __str__(self) -> str:
        return f"Recovery code for {self.user_id}"


class SocialAccount(models.Model):
    """A linked SSO identity (Google, Microsoft)."""

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="social_accounts")
    provider = models.CharField(max_length=20)
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(default=dj_timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "subject"], name="social_account_unique")
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.user_id}"
