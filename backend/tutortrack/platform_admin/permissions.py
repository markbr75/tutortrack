"""Who may use the platform console (E30 FR-30-1): platform staff, signed in with 2FA,
from an allowed network."""

from __future__ import annotations

import ipaddress

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from tutortrack.core.middleware import client_ip


def ip_allowed(ip: str | None) -> bool:
    networks = [n for n in settings.PLATFORM_IP_ALLOWLIST if n]
    if not networks:
        return True
    if not ip:
        return False
    address = ipaddress.ip_address(ip)
    return any(address in ipaddress.ip_network(n, strict=False) for n in networks)


class IsPlatformStaff(BasePermission):
    message = "The platform console is for TutorTrack staff with two-factor authentication."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not (user and user.is_authenticated and getattr(user, "is_platform_staff", False)):
            return False
        if getattr(request, "impersonator", None) is not None:
            return False  # stop viewing as a customer first
        if settings.PLATFORM_REQUIRE_MFA:
            session = getattr(request, "user_session", None)
            if session is None or not session.mfa_verified:
                return False
        return ip_allowed(client_ip(request))
