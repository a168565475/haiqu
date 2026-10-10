from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.files.models import BusinessFile


def safe_storage_path(storage_key):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    storage_path = (media_root / storage_key).resolve()
    try:
        storage_path.relative_to(media_root)
    except ValueError:
        return None
    return storage_path if storage_path != media_root else None


def _unlink_safely(storage_path):
    if storage_path is None:
        return
    try:
        storage_path.unlink(missing_ok=True)
    except OSError:
        # 数据库记录已经安全删除；落盘异常交由运维清理，不让已提交请求变成假失败。
        pass


def _has_references(business_file):
    for relation in business_file._meta.related_objects:
        field_name = relation.field.name
        if relation.related_model._base_manager.filter(**{field_name: business_file.pk}).exists():
            return True
    return False


def delete_business_file_if_unreferenced(file_id):
    storage_path = None
    with transaction.atomic():
        business_file = BusinessFile.objects.select_for_update().filter(pk=file_id).first()
        if business_file is None or _has_references(business_file):
            return
        storage_path = safe_storage_path(business_file.storage_key)
        try:
            business_file.delete()
        except ProtectedError:
            return
    _unlink_safely(storage_path)


def discard_uploaded_files(business_files):
    for business_file in business_files:
        storage_path = safe_storage_path(business_file.storage_key)
        try:
            BusinessFile.objects.filter(pk=business_file.pk).delete()
        except ProtectedError:
            continue
        _unlink_safely(storage_path)


def purge_expired_bom_line_image_drafts(*, bom_id=None, owner_user_id=None, limit=500):
    from .models import BomLineImageDraft

    with transaction.atomic():
        queryset = BomLineImageDraft.objects.select_for_update().filter(expires_at__lte=timezone.now())
        if bom_id is not None:
            queryset = queryset.filter(bom_id=bom_id)
        if owner_user_id is not None:
            queryset = queryset.filter(owner_user_id=owner_user_id)
        draft_ids = list(queryset.order_by("expires_at", "id").values_list("id", flat=True)[:limit])
        if not draft_ids:
            return 0
        deleted_count, _ = BomLineImageDraft.objects.filter(pk__in=draft_ids).delete()
        return deleted_count
