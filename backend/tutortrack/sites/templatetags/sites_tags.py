from django import template

register = template.Library()


@register.simple_tag
def asset(file_id: object) -> str:
    """Site-relative URL of a public asset (the page's published images)."""
    return f"/api/v1/public/assets/{file_id}" if file_id else ""
