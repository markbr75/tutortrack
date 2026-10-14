"""Voice notes for lesson reports (FR-31-1). Claude does not transcribe audio, so a
speech-to-text provider sits behind the ``Transcriber`` interface (``AI["TRANSCRIBER"]``).
None ships yet (ADR 0029): with the fake LLM provider (development, tests) the
``FakeTranscriber`` is used; otherwise voice notes are refused with a clear message."""

from __future__ import annotations

from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/aac",
}


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, *, content_type: str, language: str) -> str: ...


class FakeTranscriber:
    """Deterministic: UTF-8 "audio" is returned as its text (tests upload text bytes);
    anything else becomes a fixed sentence."""

    def transcribe(self, audio: bytes, *, content_type: str, language: str) -> str:
        try:
            text = audio.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = ""
        return text or "We practised the lesson topics and set homework."


def get_transcriber() -> Transcriber | None:
    from .providers import provider_name

    path = str(settings.AI.get("TRANSCRIBER") or "")
    if path:
        transcriber: Transcriber = import_string(path)()
        return transcriber
    if provider_name() == "fake":
        return FakeTranscriber()
    return None


def transcribe(upload: Any, *, language: str = "en-GB") -> str:
    transcriber = get_transcriber()
    if transcriber is None:
        raise BusinessRuleViolation(
            _("Voice notes aren't available yet. Type your notes instead."),
            extra={"errors": {"audio": [_("Voice notes aren't available yet.")]}},
        )
    content_type = (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
    if content_type not in AUDIO_TYPES:
        raise BusinessRuleViolation(
            _("Upload an audio recording."),
            extra={"errors": {"audio": [_("Unsupported audio format.")]}},
        )
    limit = int(settings.AI.get("MAX_AUDIO_MB") or 20) * 1024 * 1024
    if getattr(upload, "size", 0) > limit:
        raise BusinessRuleViolation(
            _("The recording is too long."), extra={"errors": {"audio": [_("Too large.")]}}
        )
    return transcriber.transcribe(upload.read(), content_type=content_type, language=language)
