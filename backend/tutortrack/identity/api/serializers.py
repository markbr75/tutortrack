from __future__ import annotations

from typing import Any

from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from ..models import Invitation, Membership, User, UserSession


class UserSerializer(BaseModelSerializer):
    email_verified = serializers.SerializerMethodField()
    has_mfa = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "preferred_name", "pronouns", "phone",
            "timezone", "locale", "email_verified", "has_mfa", "date_joined",
        ]  # fmt: skip
        read_only_fields = ["id", "email", "date_joined"]

    def get_email_verified(self, obj: User) -> bool:
        return obj.email_verified_at is not None

    def get_has_mfa(self, obj: User) -> bool:
        return obj.has_mfa

    def validate_timezone(self, value: str) -> str:
        from tutortrack.core.time import is_valid_timezone

        if not is_valid_timezone(value):
            raise serializers.ValidationError("Unknown timezone.")
        return value


class MeOrganisationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()
    mode = serializers.CharField()


class MeMembershipSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    role = serializers.CharField()
    branch_scope = serializers.CharField()


class ImpersonatorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    name = serializers.CharField()
    write = serializers.BooleanField()


class MeSerializer(serializers.Serializer):
    user = UserSerializer()
    organisation = MeOrganisationSerializer(allow_null=True)
    membership = MeMembershipSerializer(allow_null=True)
    permissions = serializers.DictField(
        child=serializers.CharField(), help_text="{codename: scope (all|branch|own)}"
    )
    features = serializers.DictField(child=serializers.BooleanField())
    impersonator = ImpersonatorSerializer(allow_null=True)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    remember = serializers.BooleanField(default=False)


class LoginResultSerializer(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    user = UserSerializer(allow_null=True)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    next = serializers.CharField(required=False, default="/")


class LoginTokenSerializer(serializers.Serializer):
    token = serializers.CharField()
    remember = serializers.BooleanField(default=False)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(trim_whitespace=False, write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(trim_whitespace=False, write_only=True)


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class SessionSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = ["id", "ip", "user_agent", "method", "created_at", "last_seen_at", "is_current"]

    def get_is_current(self, obj: UserSession) -> bool:
        request = self.context.get("request")
        return request is not None and str(obj.pk) == request.session.get("tt_sid")


class TOTPSetupSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()
    qr_svg = serializers.CharField(help_text="SVG markup of the QR code for the URI.")


class TOTPConfirmSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    code = serializers.CharField(max_length=10)


class RecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), help_text="Shown once. Each works one time."
    )


class SSOProviderSerializer(serializers.Serializer):
    key = serializers.CharField()
    start_url = serializers.CharField()


class MemberUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    name = serializers.CharField(source="get_full_name")
    has_mfa = serializers.BooleanField()


class MembershipSerializer(BaseModelSerializer):
    user = MemberUserSerializer(read_only=True)
    branches = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = [
            "id", "user", "role", "status", "branch_scope", "branches", "title", "joined_at",
            "last_active_at",
        ]  # fmt: skip
        read_only_fields = ["id", "user", "joined_at", "last_active_at"]

    def get_branches(self, obj: Membership) -> list[str]:
        from ..selectors import branch_ids_for

        ids = branch_ids_for(obj)
        return sorted(str(i) for i in ids) if ids is not None else []


class MembershipUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Membership.Role.choices, required=False)
    status = serializers.ChoiceField(
        choices=[Membership.Status.ACTIVE, Membership.Status.SUSPENDED], required=False
    )
    title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    branch_scope = serializers.ChoiceField(choices=Membership.BranchScope.choices, required=False)
    branches = serializers.ListField(child=serializers.UUIDField(), required=False)


class InvitationSerializer(BaseModelSerializer):
    class Meta:
        model = Invitation
        fields = [
            "id", "email", "role", "branch_scope", "branch_ids", "title", "status", "expires_at",
            "accepted_at", "sent_count", "last_sent_at", "created_at",
        ]  # fmt: skip
        read_only_fields = [
            "id", "status", "expires_at", "accepted_at", "sent_count", "last_sent_at", "created_at",
        ]  # fmt: skip

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return attrs


class BulkInviteSerializer(serializers.Serializer):
    emails = serializers.ListField(child=serializers.EmailField(), min_length=1, max_length=200)
    role = serializers.ChoiceField(choices=Membership.Role.choices)


class BulkInviteResultSerializer(serializers.Serializer):
    invited = serializers.ListField(child=serializers.EmailField())
    skipped = serializers.DictField(child=serializers.CharField())


class InvitationLookupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.CharField()
    organisation_name = serializers.CharField()
    account_exists = serializers.BooleanField()
    expires_at = serializers.DateTimeField()


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField()
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class RoleSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    is_builtin = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    grants = serializers.ListField(child=serializers.CharField())
    denies = serializers.ListField(child=serializers.CharField())


class PermissionSerializer(serializers.Serializer):
    codename = serializers.CharField()
    category = serializers.CharField()
    description = serializers.CharField()


class ImpersonateSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    write = serializers.BooleanField(default=False)


class LoginEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    created_at = serializers.DateTimeField()
    method = serializers.CharField()
    success = serializers.BooleanField()
    reason = serializers.CharField()
    ip = serializers.IPAddressField(allow_null=True)
    user_agent = serializers.CharField()
