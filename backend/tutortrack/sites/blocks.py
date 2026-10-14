"""Website builder blocks (FR-24-4): registry, validation and data for rendering.

A page is a list of ``{"id", "type", "props"}``. Each block type validates its props with a
serializer, says which uploaded files it uses (so they become public assets once the page is
published) and loads any live data it shows (tutors, services, testimonials) when rendered.
Templates live in ``templates/sites/blocks/<type>.html`` and are auto-escaped; links accept
only http(s), mailto, tel and site-relative paths. Register more types (``booking`` with
E08, ``class_catalogue`` with E20) with ``register()``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from rest_framework import serializers

MAX_BLOCKS = 60
_SAFE_HREF = re.compile(
    r"^(https?://[^\s<>\"']+|mailto:[^\s<>\"']+|tel:[+0-9 ()-]+|/[^\s<>\"']*|#[\w-]*)$"
)


def clean_href(value: str) -> str:
    value = (value or "").strip()
    if value and not _SAFE_HREF.match(value):
        raise serializers.ValidationError(
            _("Use a web address (https://...), mailto:, tel: or /page.")
        )
    return value


class HrefField(serializers.CharField):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 500)
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_blank", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> str:
        return clean_href(super().to_internal_value(data))


def _text(max_length: int = 200, **kw: Any) -> serializers.CharField:
    return serializers.CharField(max_length=max_length, required=False, allow_blank=True, **kw)


class HeroProps(serializers.Serializer):
    heading = serializers.CharField(max_length=150)
    subheading = _text(300)
    cta_label = _text(40)
    cta_href = HrefField()
    image = serializers.UUIDField(required=False, allow_null=True)
    image_alt = _text(200)


class TextProps(serializers.Serializer):
    heading = _text(150)
    body = serializers.CharField(max_length=10_000, allow_blank=True)


class ImageProps(serializers.Serializer):
    image = serializers.UUIDField()
    alt = _text(200)  # empty = decorative
    caption = _text(300)


class TutorGridProps(serializers.Serializer):
    heading = _text(150)
    subject = _text(100)
    limit = serializers.IntegerField(min_value=1, max_value=24, default=6)


class SubjectListProps(serializers.Serializer):
    heading = _text(150)


class PricingProps(serializers.Serializer):
    heading = _text(150)
    services = serializers.ListField(child=serializers.UUIDField(), max_length=12, default=list)
    note = _text(300)


class TestimonialsProps(serializers.Serializer):
    heading = _text(150)
    limit = serializers.IntegerField(min_value=1, max_value=12, default=3)


class FaqItem(serializers.Serializer):
    question = serializers.CharField(max_length=200)
    answer = serializers.CharField(max_length=2000)


class FaqProps(serializers.Serializer):
    heading = _text(150)
    items = serializers.ListField(child=FaqItem(), max_length=30)


class FormProps(serializers.Serializer):
    heading = _text(150)
    form = serializers.SlugField(max_length=80)


class CtaProps(serializers.Serializer):
    heading = serializers.CharField(max_length=150)
    body = _text(300)
    cta_label = serializers.CharField(max_length=40)
    cta_href = HrefField(required=True, allow_blank=False)


class MapProps(serializers.Serializer):
    heading = _text(150)
    address = _text(300)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)


@dataclass(frozen=True)
class BlockType:
    key: str
    label: str | Promise
    props: type[serializers.Serializer]
    assets: Callable[[dict[str, Any]], list[str]] = lambda props: []
    load: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None


_registry: dict[str, BlockType] = {}


def register(block: BlockType) -> BlockType:
    _registry[block.key] = block
    return block


def get(key: str) -> BlockType | None:
    return _registry.get(key)


def _field_kind(f: Any) -> str:
    if isinstance(f, HrefField):
        return "href"
    if isinstance(f, serializers.ListField):
        return "items" if isinstance(f.child, serializers.Serializer) else "services"
    if isinstance(f, serializers.UUIDField):
        return "image"
    if isinstance(f, serializers.SlugField):
        return "form"
    if isinstance(f, serializers.IntegerField | serializers.DecimalField):
        return "number"
    if isinstance(f, serializers.CharField) and (f.max_length or 0) > 300:
        return "textarea"
    return "text"


def describe() -> list[dict[str, Any]]:
    """Block types and their fields, for the editor's forms."""
    out = []
    for b in _registry.values():
        fields = [
            {
                "name": name,
                "kind": _field_kind(f),
                "is_required": bool(f.required),
                "max_length": getattr(f, "max_length", None),
            }
            for name, f in b.props().fields.items()
        ]
        out.append({"key": b.key, "title": str(b.label), "fields": fields})
    return out


# --- data loaders (run when rendering) -----------------------------------------------------------


def _tutors(props: dict[str, Any], org: Any) -> dict[str, Any]:
    from . import selectors

    rows = selectors.directory(subject=props.get("subject", ""))[: int(props.get("limit", 6))]
    return {"tutors": [selectors.public_tutor_card(p) for p in rows]}


def _subjects(props: dict[str, Any], org: Any) -> dict[str, Any]:
    from . import selectors

    return {"subjects": selectors.public_subjects()}


def _pricing(props: dict[str, Any], org: Any) -> dict[str, Any]:
    from . import selectors

    return {"services": selectors.public_services(props.get("services") or [], prices=True)}


def _testimonials(props: dict[str, Any], org: Any) -> dict[str, Any]:
    from . import selectors

    return {"testimonials": selectors.public_testimonials(int(props.get("limit", 3)))}


def _map(props: dict[str, Any], org: Any) -> dict[str, Any]:
    lat, lng = float(props["lat"]), float(props["lng"])
    d = 0.01
    bbox = f"{lng - d:.5f}%2C{lat - d:.5f}%2C{lng + d:.5f}%2C{lat + d:.5f}"
    return {
        "map_src": (
            "https://www.openstreetmap.org/export/embed.html"
            f"?bbox={bbox}&layer=mapnik&marker={lat:.5f}%2C{lng:.5f}"
        )
    }


def _one(key: str) -> Callable[[dict[str, Any]], list[str]]:
    return lambda props: [str(props[key])] if props.get(key) else []


class BlogListProps(serializers.Serializer):
    heading = _text()
    limit = serializers.IntegerField(min_value=1, max_value=12, default=3)


def _blog(props: dict[str, Any], org: Any) -> dict[str, Any]:
    from . import selectors

    site = selectors.site()
    if site is None:
        return {"posts": []}
    rows = selectors.live_posts(site)[: int(props.get("limit", 3))]
    return {"posts": [selectors.post_card(p, org) for p in rows]}


register(BlockType("hero", _l("Hero"), HeroProps, assets=_one("image")))
register(BlockType("text", _l("Text"), TextProps))
register(BlockType("image", _l("Image"), ImageProps, assets=_one("image")))
register(BlockType("tutor_grid", _l("Tutor grid"), TutorGridProps, load=_tutors))
register(BlockType("subject_list", _l("Subject list"), SubjectListProps, load=_subjects))
register(BlockType("pricing_table", _l("Pricing table"), PricingProps, load=_pricing))
register(BlockType("testimonials", _l("Testimonials"), TestimonialsProps, load=_testimonials))
register(BlockType("faq", _l("FAQ"), FaqProps))
register(BlockType("form", _l("Enquiry form"), FormProps))
register(BlockType("cta", _l("Call to action"), CtaProps))
register(BlockType("map", _l("Map"), MapProps, load=_map))
register(BlockType("blog_list", _l("Latest blog posts"), BlogListProps, load=_blog))  # G6


# --- validation ----------------------------------------------------------------------------------


def validate(blocks: Any) -> list[dict[str, Any]]:
    """Clean a page's blocks; raises ``serializers.ValidationError`` keyed by block index."""
    if not isinstance(blocks, list):
        raise serializers.ValidationError({"blocks": [_("Blocks must be a list.")]})
    if len(blocks) > MAX_BLOCKS:
        raise serializers.ValidationError(
            {"blocks": [_("A page can have up to %(n)s blocks.") % {"n": MAX_BLOCKS}]}
        )
    cleaned: list[dict[str, Any]] = []
    errors: dict[str, Any] = {}
    for index, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            errors[str(index)] = [_("Each block must be an object.")]
            continue
        block_type = get(str(raw.get("type", "")))
        if block_type is None:
            errors[str(index)] = {"type": [_("Unknown block type.")]}
            continue
        props = block_type.props(data=raw.get("props") or {})
        if not props.is_valid():
            errors[str(index)] = {"props": props.errors}
            continue
        block_id = re.sub(r"[^\w-]", "", str(raw.get("id") or f"b{index}"))[:40] or f"b{index}"
        cleaned.append(
            {"id": block_id, "type": block_type.key, "props": _json_safe(props.validated_data)}
        )
    if errors:
        raise serializers.ValidationError({"blocks": errors})
    return cleaned


def _json_safe(value: Any) -> Any:
    from decimal import Decimal
    from uuid import UUID

    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID | Decimal):
        return str(value)
    return value


def asset_ids(blocks: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for block in blocks:
        block_type = get(block.get("type", ""))
        if block_type is not None:
            found.extend(block_type.assets(block.get("props") or {}))
    return sorted(set(found))


def prepare(blocks: list[dict[str, Any]], organisation: Any) -> list[dict[str, Any]]:
    """Blocks with their live data, ready for the templates."""
    out = []
    for block in blocks:
        block_type = get(block.get("type", ""))
        if block_type is None:
            continue
        props = dict(block.get("props") or {})
        data = block_type.load(props, organisation) if block_type.load else {}
        if block.get("type") == "text":
            data["paragraphs"] = [p for p in str(props.get("body", "")).split("\n\n") if p.strip()]
        out.append(
            {
                **block,
                "props": props,
                "data": data,
                "template": f"sites/blocks/{block_type.key}.html",
            }
        )
    return out
