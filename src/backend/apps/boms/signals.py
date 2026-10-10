from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .image_files import delete_business_file_if_unreferenced
from .models import BomLineImageDraft


@receiver(post_delete, sender=BomLineImageDraft)
def cleanup_deleted_bom_line_image_draft(sender, instance, **kwargs):
    file_id = instance.business_file_id
    transaction.on_commit(lambda: delete_business_file_if_unreferenced(file_id))
