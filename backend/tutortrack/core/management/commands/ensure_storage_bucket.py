from typing import Any

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand

from tutortrack.core.storage.client import bucket, s3_client


class Command(BaseCommand):
    help = "Create the object-storage bucket if it does not exist (local/dev environments)."

    def handle(self, *args: Any, **options: Any) -> None:
        client = s3_client()
        name = bucket()
        try:
            client.head_bucket(Bucket=name)
            self.stdout.write(f"Bucket {name} exists.")
        except ClientError:
            region = settings.AWS_S3_REGION_NAME
            kwargs: dict[str, Any] = {"Bucket": name}
            if region and region != "us-east-1":  # us-east-1 rejects an explicit constraint
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
            client.create_bucket(**kwargs)
            self.stdout.write(self.style.SUCCESS(f"Created bucket {name}."))
