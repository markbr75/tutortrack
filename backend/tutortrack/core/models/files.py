from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import TenantModel


class StoredFile(TenantModel):
    """A file in object storage. The browser uploads it directly via a presigned URL; it is
    then scanned for malware before it can be downloaded."""

    class Status(models.TextChoices):
        PENDING_UPLOAD = "pending_upload"
        UPLOADED = "uploaded"
        REJECTED = "rejected"

    class ScanStatus(models.TextChoices):
        PENDING = "pending"
        CLEAN = "clean"
        INFECTED = "infected"
        ERROR = "error"
        SKIPPED = "skipped"  # scanning disabled (local dev only)

    class Visibility(models.TextChoices):
        PRIVATE = "private"  # uploader and staff with file permissions
        INTERNAL = "internal"  # all staff in the organisation
        SHARED = "shared"  # anyone with access to the owning record

    owner_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    owner_object_id = models.CharField(max_length=64, blank=True, default="")
    owner = GenericForeignKey("owner_content_type", "owner_object_id")

    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127)
    size_bytes = models.PositiveBigIntegerField()
    checksum_sha256 = models.CharField(max_length=64, blank=True, default="")
    storage_key = models.CharField(max_length=512, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_UPLOAD)
    scan_status = models.CharField(
        max_length=20, choices=ScanStatus.choices, default=ScanStatus.PENDING
    )
    scanned_at = models.DateTimeField(null=True, blank=True)
    visibility = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["owner_content_type", "owner_object_id"])]

    def __str__(self) -> str:
        return self.filename

    @property
    def is_downloadable(self) -> bool:
        return self.status == self.Status.UPLOADED and self.scan_status in {
            self.ScanStatus.CLEAN,
            self.ScanStatus.SKIPPED,
        }
