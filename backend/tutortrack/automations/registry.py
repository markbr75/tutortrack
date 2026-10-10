"""What automations can react to and do (E14-T01): subjects, event triggers and actions.

Apps' records are exposed as *subjects*: a loader, a whitelisted context (the only fields
conditions and message variables can see), who can be messaged about it, which fields an
automation may set, and date fields for date triggers. ``builtins.py`` registers the
platform's subjects and actions; other apps can register more the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Context = dict[str, Any]


@dataclass(frozen=True)
class FieldDef:
    path: str  # dot path in the context, e.g. "lesson.service.name"
    label: str
    type: str = "text"  # text | number | date | datetime | bool | list | choice
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Subject:
    key: str  # the event subject type, e.g. "lesson"
    label: str
    model: str  # "app_label.Model"
    target: str = ""  # CRM target type (tags, tasks), e.g. "scheduling.lesson"
    fields: tuple[FieldDef, ...] = ()
    context: Callable[[Any], Context] = lambda obj: {}
    recipients: dict[str, Callable[[Any], list[Any]]] = field(default_factory=dict)
    owner: Callable[[Any], Any] | None = None  # the user responsible (task assignee)
    setters: dict[str, Callable[[Any, Any], Any]] = field(default_factory=dict)
    date_fields: tuple[str, ...] = ()  # model fields for date triggers

    def model_class(self) -> Any:
        from django.apps import apps

        return apps.get_model(self.model)

    def load(self, pk: Any) -> Any:
        return self.model_class().objects.filter(pk=pk).first()

    def field_paths(self) -> set[str]:
        return {f.path for f in self.fields}


@dataclass(frozen=True)
class Trigger:
    event: str
    label: str
    subject: str


@dataclass(frozen=True)
class ActionField:
    name: str
    label: str
    type: str = "text"  # text | textarea | number | choice | multi | bool | template
    required: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    run: Callable[[Any, dict[str, Any]], dict[str, Any]]
    describe: Callable[[Any, dict[str, Any]], str]
    fields: tuple[ActionField, ...] = ()
    subjects: tuple[str, ...] = ()  # empty = any subject
    permission: str = ""  # the automation's author must hold it (finance actions)


_subjects: dict[str, Subject] = {}
_triggers: dict[str, Trigger] = {}
_actions: dict[str, Action] = {}


def register_subject(subject: Subject) -> Subject:
    _subjects[subject.key] = subject
    return subject


def register_trigger(event: str, label: str, subject: str) -> Trigger:
    trigger = Trigger(event, label, subject)
    _triggers[event] = trigger
    return trigger


def register_action(action: Action) -> Action:
    _actions[action.key] = action
    return action


def subject(key: str) -> Subject | None:
    return _subjects.get(key)


def subjects() -> list[Subject]:
    return list(_subjects.values())


def trigger(event: str) -> Trigger | None:
    return _triggers.get(event)


def triggers() -> list[Trigger]:
    return sorted(_triggers.values(), key=lambda t: t.event)


def action(key: str) -> Action | None:
    return _actions.get(key)


def actions() -> list[Action]:
    return list(_actions.values())
