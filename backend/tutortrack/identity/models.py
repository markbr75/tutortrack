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
        return self.first_name or self.email


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
