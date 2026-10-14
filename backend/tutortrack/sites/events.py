"""Domain events published by the website, widgets and branding app (E24).

Custom-domain events live in ``tenancy.events`` (tenancy owns ``OrganisationDomain``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class BrandKitUpdated(DomainEvent):
    event_type: ClassVar[str] = "brand_kit.updated"
    subject_type: ClassVar[str] = "brand_kit"

    branch: str | None
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class WidgetSaved(DomainEvent):
    event_type: ClassVar[str] = "widget.saved"
    subject_type: ClassVar[str] = "widget"

    key: str
    kind: str
    created: bool


@dataclass(frozen=True, kw_only=True)
class PublicProfileSubmitted(DomainEvent):
    """A tutor's public profile changes wait for approval (FR-24-5)."""

    event_type: ClassVar[str] = "public_profile.submitted"
    subject_type: ClassVar[str] = "public_profile"

    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class PublicProfileApproved(DomainEvent):
    event_type: ClassVar[str] = "public_profile.approved"
    subject_type: ClassVar[str] = "public_profile"

    tutor_id: str
    slug: str


@dataclass(frozen=True, kw_only=True)
class PublicProfileRejected(DomainEvent):
    event_type: ClassVar[str] = "public_profile.rejected"
    subject_type: ClassVar[str] = "public_profile"

    tutor_id: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class PublicProfileHidden(DomainEvent):
    event_type: ClassVar[str] = "public_profile.hidden"
    subject_type: ClassVar[str] = "public_profile"

    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class BlogPostPublished(DomainEvent):
    """A blog or news post went live on the website (G6)."""

    event_type: ClassVar[str] = "blog_post.published"
    subject_type: ClassVar[str] = "blog_post"

    slug: str


@dataclass(frozen=True, kw_only=True)
class SitePagePublished(DomainEvent):
    event_type: ClassVar[str] = "site_page.published"
    subject_type: ClassVar[str] = "site_page"

    path: str
    number: int


@dataclass(frozen=True, kw_only=True)
class SitePublished(DomainEvent):
    event_type: ClassVar[str] = "site.published"
    subject_type: ClassVar[str] = "site"

    published: bool
