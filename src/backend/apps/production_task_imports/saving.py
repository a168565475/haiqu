import hashlib
import json
import os
from pathlib import Path
import zipfile

from django.conf import settings
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from django.utils.datastructures import MultiValueDict
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.files.models import BusinessFile
from apps.production_tasks.api.serializers import ProductionTaskWriteSerializer
from apps.production_tasks.services import (CONTRACT_NUMBER_TOKEN_MAX_AGE_SECONDS, CONTRACT_NUMBER_TOKEN_SALT,
                                            create_production_task)
from .review import validate_review
from .readiness import require_schema
from .services import audit, owned
from .storage import ImportFailure, directory, source_path


class CreatedMedia(list):
    def __init__(self, record):
        super().__init__()
        self.path = directory(record.pk) / 'pending-media.json'
        if self.path.exists():
            raise Conflict('上次保存的文件尚待核对，请稍后重试。')

    def prepare(self, file_id, storage_key, digest):
        # 正式文件移动前追加一条归属记录，进程退出/事务回滚后仍能核对。
        with self.path.open('a', encoding='utf-8') as target:
            target.write(json.dumps({'id': str(file_id), 'key': storage_key, 'sha256': digest}) + '\n')
            target.flush()
            os.fsync(target.fileno())
        os.chmod(self.path, 0o600)

    def append(self, item):
        super().append(item)
        if item.scan_status != 'CLEAN':
            raise ImportFailure('SCAN_UNAVAILABLE')


def reconcile_media(record):
    journal = directory(record.pk) / 'pending-media.json'
    if not journal.exists():
        return
    if journal.is_symlink() or journal.stat().st_nlink != 1 or journal.stat().st_size > 128 * 1024:
        raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE')
    try:
        entries = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    except (ValueError, UnicodeError):
        raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE') from None
    if len(entries) > 2000:
        raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE')
    root = Path(settings.MEDIA_ROOT).resolve()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'id', 'key', 'sha256'}
                or not all(isinstance(value, str) for value in entry.values())
                or not entry['key'].startswith('production_tasks/')):
            raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE')
        if BusinessFile.objects.filter(pk=entry['id']).exists():
            continue
        path = root / entry['key']
        if path.resolve() != path or not path.is_relative_to(root / 'production_tasks'):
            raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE')
        if path.exists():
            if (not path.is_file() or path.stat().st_nlink != 1
                    or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']):
                raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE')
            path.unlink()
    journal.unlink()


def save_import(request, payload, serializer_context, validate_file_fields):
    require_schema()
    record_id = serializers.UUIDField().run_validation(payload.get('import_object_id'))
    record = owned(request, record_id)
    created_files = None
    try:
        with transaction.atomic():
            record = owned(request, record_id, lock=True)
            # 已保存墓碑必须先于 ETag、版本、合同号和任务号唯一性校验。
            if record.saved_at:
                if not record.saved_task_id or record.saved_task.archived_at:
                    raise Conflict(f'该导入已保存为 {record.saved_task_number}，原单据已归档或删除，不能再次建单。')
                return record.saved_task, True
            require_matching_etag(request, record)
            if record.state != 'REVIEW' or record.expires_at <= timezone.now():
                raise Conflict('导入尚未完成核对或已经过期。')
            if not settings.FILE_VIRUS_SCAN_ENABLED or record.scan_status != 'CLEAN':
                raise ImportFailure('SCAN_UNAVAILABLE')
            reconcile_media(record)
            revision = serializers.IntegerField(min_value=1).run_validation(payload.get('result_revision'))
            if revision != record.result_revision:
                raise Conflict('解析结果版本已变化，请重新核对。')
            validate_review(record, record.review)
            values = {key: value for key, value in payload.items() if key not in ('import_object_id', 'result_revision')}
            reviewed = {key: value for key, value in values.items() if key not in ('contract_number', 'contract_number_token')}
            if reviewed != record.review['payload']:
                raise Conflict('表单内容与已核对稿不同，请先保存当前核对稿。')
            try:
                reservation = signing.loads(values.get('contract_number_token', ''), salt=CONTRACT_NUMBER_TOKEN_SALT,
                                            max_age=CONTRACT_NUMBER_TOKEN_MAX_AGE_SECONDS)
            except signing.BadSignature:
                raise ValidationError({'contract_number_token': 'ERP 合同编号预留失效，请重新预留。'}) from None
            if reservation.get('contract_number') != values.get('contract_number'):
                raise ValidationError({'contract_number': '导入保存必须使用 ERP 预留合同号。'})
            validate_file_fields(values)
            serializer = ProductionTaskWriteSerializer(data=values, context={**serializer_context, 'require_contract_number_token': True})
            serializer.is_valid(raise_exception=True)
            files = MultiValueDict({key: request.FILES.getlist(key) for key in request.FILES})
            images = {item['id']: item for item in record.manifest['images']}
            with zipfile.ZipFile(source_path(record)) as archive:
                for key, image_id in record.review['selected_images'].items():
                    if not image_id or files.getlist('product_image_' + key):
                        continue
                    image = images[image_id]
                    data = archive.read(image['part'])
                    if hashlib.sha256(data).hexdigest() != image['sha256']:
                        raise ImportFailure('SOURCE_CHANGED')
                    files.setlist('product_image_' + key, [SimpleUploadedFile(image['output'].split('/')[-1], data,
                        content_type='image/png' if image['format'] == 'PNG' else 'image/jpeg')])
            created_files = CreatedMedia(record)
            task = create_production_task(validated_data=serializer.validated_data, files=files,
                actor_employee=record.owner, request=request, created_files=created_files)
            record.state, record.saved_task = 'SAVED', task
            record.saved_task_id_snapshot, record.saved_task_number = task.pk, task.task_number
            record.saved_at = timezone.now()
            record.save()
            audit(record, 'IMPORT_SAVED', request)
        if created_files is not None:
            reconcile_media(record)
        return task, False
    except BaseException:
        if created_files is not None:
            reconcile_media(record)
        raise
