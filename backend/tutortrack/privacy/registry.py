"""The privacy provider registry (E29 FR-29-4/5, ADR 0028).

Every app that holds personal data registers a ``Provider`` in its own ``<app>/privacy.py``
(autodiscovered by the privacy app). Providers only touch their own app's models, so the
privacy app never writes to another app's tables:

* ``expand(person)`` adds related subjects (a client's students, a contact's login...)
  and the names, emails and phone numbers used to find and scrub free text;
* ``export(person)`` returns ``Section``s for the DSAR export, ``files(person)`` the
  documents to include;
* ``erase(person, ctx)`` anonymises (or deletes) the app's records about the person and
  returns what it did; financial records are anonymised, never deleted;
* ``revoke(person)`` ends logins and tokens;
* ``retention`` categories (``RetentionCategory``) find or purge data past its period.

A data subject is a ``(subject_type, id)`` pair: ``people.client``, ``people.contact``,
``people.student``, ``people.tutor``, ``identity.user``, ``recruitment.application``,
``growth.affiliate``...
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Subject types the engine labels with a token ("Erased Student #12").
KIND_LABELS: dict[str, str] = {
    "people.student": "Student",
    "people.contact": "Contact",
    "people.client": "Client",
    "people.tutor": "Tutor",
    "identity.user": "User",
    "recruitment.application": "Applicant",
    "growth.affiliate": "Affiliate",
}


@dataclass
class Person:
    """A resolved data subject: the root record plus everything about the same person (or,
    for a household, its members). ``context`` holds related records that are *not*
    erased with the person but whose legal holds still apply (e.g. a student's client)."""

    subject_type: str
    subject_id: str
    ids: dict[str, set[str]] = field(default_factory=dict)
    context: dict[str, set[str]] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    label: str = ""

    def of(self, subject_type: str) -> list[str]:
        return sorted(self.ids.get(subject_type, set()))

    def add(self, subject_type: str, *ids: Any) -> bool:
        bucket = self.ids.setdefault(subject_type, set())
        before = len(bucket)
        bucket.update(str(i) for i in ids if i)
        return len(bucket) != before

    def add_context(self, subject_type: str, *ids: Any) -> None:
        self.context.setdefault(subject_type, set()).update(str(i) for i in ids if i)

    def add_terms(
        self, *, names: Iterable[str] = (), emails: Iterable[str] = (), phones: Iterable[str] = ()
    ) -> None:
        self.names.update(n.strip() for n in names if n and len(n.strip()) > 1)
        self.emails.update(e.strip().lower() for e in emails if e and "@" in e)
        self.phones.update(p.strip() for p in phones if p and len(p.strip()) >= 6)

    def all_refs(self) -> list[tuple[str, str]]:
        return sorted((t, i) for t, ids in self.ids.items() for i in ids)

    def snapshot(self) -> dict[str, list[str]]:
        return {t: sorted(ids) for t, ids in sorted(self.ids.items()) if ids}

    def terms(self) -> dict[str, list[str]]:
        return {
            "names": sorted(self.names),
            "emails": sorted(self.emails),
            "phones": sorted(self.phones),
        }

    @classmethod
    def restore(
        cls, subject_type: str, subject_id: str, ids: dict[str, list[str]], terms: dict[str, Any]
    ) -> Person:
        person = cls(subject_type, subject_id, ids={t: set(v) for t, v in ids.items()})
        person.add_terms(
            names=terms.get("names", ()),
            emails=terms.get("emails", ()),
            phones=terms.get("phones", ()),
        )
        return person


@dataclass(frozen=True)
class Section:
    """One part of a DSAR export: ``records`` are JSON-safe dicts, each with an ``id``."""

    key: str
    title: str
    records: list[dict[str, Any]]


@dataclass
class ErasureContext:
    """What a provider needs to erase consistently: the token labels per subject, a
    scrubber for free text and the financial retention cut-off."""

    labels: dict[str, str]
    financial_cutoff: datetime  # financial records dated on/after this are still retained
    include_financial: bool = False  # the retention period has passed: anonymise them too
    _pattern: re.Pattern[str] | None = None
    _replacement: str = ""

    def label(self, subject_type: str, subject_id: Any, default: str = "") -> str:
        return self.labels.get(f"{subject_type}:{subject_id}", default)

    def prepare_scrub(self, person: Person, replacement: str) -> None:
        terms = sorted({*person.names, *person.emails, *person.phones}, key=lambda t: (-len(t), t))
        self._replacement = replacement
        # Whole words only, so a first name never clips another word ("Al" in "Algebra").
        alternatives = "|".join(re.escape(t) for t in terms)
        self._pattern = (
            re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE) if terms else None
        )

    def scrub(self, text: str | None) -> str:
        """Replace the person's names, emails and phone numbers in free text."""
        if not text or self._pattern is None:
            return text or ""
        return self._pattern.sub(self._replacement, text)

    def scrub_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, list):
            return [self.scrub_json(v) for v in value]
        if isinstance(value, dict):
            return {k: self.scrub_json(v) for k, v in value.items()}
        return value


@dataclass
class ErasureOutcome:
    anonymised: int = 0
    deleted: int = 0
    retained: int = 0
    file_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "anonymised": self.anonymised,
            "deleted": self.deleted,
            "retained": self.retained,
            "files": len(self.file_ids),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class RetentionCategory:
    """A category of data with a retention period. Either ``find`` returns people to erase
    with the erasure engine, or ``purge`` deletes/anonymises records itself (``dry_run``
    only counts). Both receive the cut-off (records older than it are due) and a batch
    limit, and must skip anything under a legal hold (``privacy.selectors.held_ids``)."""

    key: str
    label: Any  # str or lazy translation
    default_days: int
    find: Callable[[datetime, int], list[tuple[str, str]]] | None = None
    purge: Callable[[datetime, bool, int], int] | None = None
    order: int = 100


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    expand: Callable[[Person], None] | None = None
    export: Callable[[Person], list[Section]] | None = None
    files: Callable[[Person], list[Any]] | None = None
    erase: Callable[[Person, ErasureContext], ErasureOutcome] | None = None
    revoke: Callable[[Person], int] | None = None
    order: int = 100  # erase order: people last (other apps scrub using names first)


_providers: dict[str, Provider] = {}
_retention: dict[str, RetentionCategory] = {}


def register(provider: Provider) -> Provider:
    _providers[provider.key] = provider
    return provider


def register_retention(category: RetentionCategory) -> RetentionCategory:
    _retention[category.key] = category
    return category


def providers() -> list[Provider]:
    return sorted(_providers.values(), key=lambda p: (p.order, p.key))


def provider(key: str) -> Provider:
    return _providers[key]


def retention_categories() -> list[RetentionCategory]:
    return sorted(_retention.values(), key=lambda c: (c.order, c.key))


def retention_category(key: str) -> RetentionCategory | None:
    return _retention.get(key)


def resolve(subject_type: str, subject_id: str, *, max_rounds: int = 5) -> Person:
    """Expand a subject into everything about that person, until no provider adds more."""
    person = Person(subject_type, str(subject_id))
    person.add(subject_type, subject_id)
    for _round in range(max_rounds):
        before = person.snapshot()
        for p in providers():
            if p.expand is not None:
                p.expand(person)
        if person.snapshot() == before:
            break
    return person
