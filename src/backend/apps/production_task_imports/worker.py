import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from PIL import Image

from apps.codex_connection.models import ACTIVE_STATES, CodexConnection, CodexOperation
from apps.organizations.models import Employee
from .access import worker_allowed
from .matching import match_result
from .models import ProductionTaskImport
from .services import audit
from .storage import ImportFailure, remove_files, scan_source, source_path
from .validation import discovery_result, extraction_result, source_scope

logger = logging.getLogger(__name__)


@transaction.atomic
def claim_preprocessing():
    now = timezone.now()
    # 进程丢失只标失败；不能无提示重新解析或重发模型请求。
    ProductionTaskImport.objects.filter(state='SCANNING', processing_started_at__lt=now - timedelta(seconds=370)).update(
        state='FAILED', error_code='INTERRUPTED', updated_at=now)
    record = ProductionTaskImport.objects.select_for_update(skip_locked=True).filter(
        state='CHECKING', expires_at__gt=now).order_by('created_at', 'id').first()
    if record is None:
        return None
    if not worker_allowed(record.owner):
        record.state, record.error_code = 'FAILED', 'PERMISSION_REVOKED'
        record.save()
        return None
    record.state, record.processing_started_at = 'SCANNING', now
    record.save()
    return record


def preprocess_once():
    record = claim_preprocessing()
    if record is None:
        return False
    code, manifest = '', None
    scan_status = 'PENDING'
    try:
        path = source_path(record)
        scan_source(path)
        scan_status = 'CLEAN'
        script = Path(__file__).with_name('preprocess_runner.py')
        # 子解释器不继承业务环境；不执行模型或用户提供的代码，超时杀死本次子进程。
        result = subprocess.run([sys.executable, '-I', '-B', str(script), str(path)],
                                env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                                capture_output=True, timeout=300, check=False)
        if result.returncode == 2:
            raise ImportFailure(json.loads(result.stdout)['error_code'])
        if result.returncode:
            logger.error('Import preprocessor exited unexpectedly: exit=%s; stderr_bytes=%s', result.returncode, len(result.stderr))
            raise ImportFailure('PREPROCESS_INTERNAL_ERROR')
        if len(result.stdout) > 2 * 1024 * 1024:
            raise ImportFailure('MANIFEST_SIZE_LIMIT')
        manifest = json.loads(result.stdout)
        if manifest['source_sha256'] != record.sha256:
            raise ImportFailure('SOURCE_CHANGED')
        manifest['scan_status'] = 'CLEAN'
    except ImportFailure as exc:
        code = exc.code
        if code.startswith('SCAN_'):
            scan_status = 'INFECTED' if code == 'SCAN_INFECTED' else 'FAILED'
    except subprocess.TimeoutExpired:
        code = 'PREPROCESS_TIMEOUT'
    except OSError:
        logger.exception('Import source storage or subprocess failed')
        code = 'SOURCE_UNAVAILABLE'
    with transaction.atomic():
        current = ProductionTaskImport.objects.select_for_update().get(pk=record.pk)
        if current.state != 'SCANNING' or current.attempt_no != record.attempt_no:
            return True
        if not worker_allowed(current.owner):
            code = 'PERMISSION_REVOKED'
        current.scan_status = scan_status
        current.error_code = code
        current.state = 'FAILED' if code else 'QUEUED'
        if not code:
            current.manifest = manifest
        current.save()
        audit(current, 'IMPORT_SOURCE_CHECKED')
    return True


@transaction.atomic
def enqueue_next():
    connection = CodexConnection.objects.select_for_update().first()
    if (connection is None or connection.paused or connection.status != 'READY'
            or not connection.account or connection.operations.filter(state__in=ACTIVE_STATES).exists()):
        return False
    record = ProductionTaskImport.objects.select_for_update(skip_locked=True).filter(
        state='QUEUED', scan_status='CLEAN', expires_at__gt=timezone.now()).order_by('created_at', 'id').first()
    if record is None:
        return False
    if not worker_allowed(record.owner):
        record.state, record.error_code = 'FAILED', 'PERMISSION_REVOKED'
        record.save()
        return True
    operation = CodexOperation.objects.create(connection=connection, actor=record.owner,
        action='discover' if record.phase == 'discovery' else 'extract',
        generation=connection.config_generation, model=connection.selected_model)
    record.operation, record.state = operation, 'PARSING'
    record.save()
    connection.paused = True
    connection.save(update_fields=['paused', 'updated_at'])
    audit(record, 'IMPORT_PARSE_QUEUED')
    return True


def runtime_payload(operation):
    record = ProductionTaskImport.objects.select_related('owner__user').get(operation=operation)
    if record.state != 'PARSING' or not worker_allowed(record.owner) or record.expires_at <= timezone.now():
        raise ImportFailure('PERMISSION_REVOKED')
    if record.scan_status != 'CLEAN':
        raise ImportFailure('SCAN_UNAVAILABLE')
    manifest = deepcopy(record.manifest)
    selected = record.selected_candidate if record.phase == 'extraction' else None
    image_ids = set()
    if selected:
        scope, image_ids = source_scope(manifest, selected)
        manifest['source_index'] = {key: value for key, value in manifest['source_index'].items() if key in scope}
        sheets = []
        for sheet in manifest['sheets']:
            for group in ('cells', 'pictures', 'comments'):
                sheet[group] = [row for row in sheet[group] if row['source_id'] in scope]
            if sheet['source_id'] in scope or any(sheet[group] for group in ('cells', 'pictures', 'comments')):
                sheets.append(sheet)
        manifest['sheets'] = sheets
        manifest['images'] = [image for image in manifest['images'] if image['id'] in image_ids]
        manifest['cell_images'] = {key: value for key, value in manifest['cell_images'].items()
                                   if value.get('embed_image_id') in image_ids or value.get('link_image_id') in image_ids}
        manifest['external_relationships'] = [item for item in manifest['external_relationships'] if item['source_id'] in scope]
    images = []
    if image_ids:
        path = source_path(record)
        if hashlib.sha256(path.read_bytes()).hexdigest() != record.sha256:
            raise ImportFailure('SOURCE_CHANGED')
        with zipfile.ZipFile(path) as archive:
            for image in manifest['images']:
                data = archive.read(image['part'])
                if hashlib.sha256(data).hexdigest() != image['sha256']:
                    raise ImportFailure('SOURCE_CHANGED')
                with Image.open(io.BytesIO(data)) as decoded:
                    decoded.thumbnail((1280, 1280))
                    output = io.BytesIO()
                    decoded.convert('RGB').save(output, format='JPEG', quality=85)
                encoded = base64.b64encode(output.getvalue()).decode('ascii')
                if len(encoded) > 599977:
                    raise ImportFailure('MODEL_INPUT_LIMIT')
                images.append({'image_id': image['id'], 'source_id': image['source_id'],
                               'data_url': 'data:image/jpeg;base64,' + encoded})
    payload = {'sources': manifest, 'selected_candidate': selected, 'images': images}
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 12 * 1024 * 1024:
        raise ImportFailure('MODEL_INPUT_LIMIT')
    return payload


def finish_import(operation, result, error_code):
    """调用方已锁连接并开启短事务；只接受仍绑定本操作的当前尝试。"""
    owner_id = ProductionTaskImport.objects.filter(operation=operation).values_list('owner_id', flat=True).first()
    if owner_id:
        # 同员工选择串行，但允许草稿/审计的员工外键检查，避免反向等待。
        Employee.objects.select_for_update(no_key=True).get(pk=owner_id)
    record = ProductionTaskImport.objects.select_for_update().filter(operation=operation).first()
    if record is None or record.state not in ('PARSING', 'QUEUED'):
        return ''
    code = error_code
    if not worker_allowed(record.owner):
        code = 'PERMISSION_REVOKED'
    if record.expires_at <= timezone.now():
        code = 'IMPORT_EXPIRED'
    if not code:
        try:
            if operation.action == 'discover':
                candidates = discovery_result(result, record.manifest)
                # 模型的版本描述可能换一种写法。相同员工/文件以首次成功的列表为准，
                # 防止自由文本变化产生第二个 object_id，绕过已有草稿的墓碑。
                previous = ProductionTaskImport.objects.filter(owner_id=record.owner_id, sha256=record.sha256).filter(
                    Q(saved_at__isnull=False) | Q(expires_at__gt=timezone.now())).exclude(
                    pk=record.pk).exclude(discovery={}).exclude(candidates=[]).order_by('created_at', 'id').first()
                if previous:
                    result = previous.discovery
                    candidates = discovery_result(result, record.manifest)
                record.candidates, record.discovery = candidates, result
                record.state = 'NEEDS_SELECTION'
                if len(record.candidates) == 1 and not record.candidates[0]['grouping_uncertain']:
                    candidate = record.candidates[0]
                    # 所有自动/人工选择同样串行，避免同文件同对象的竞态。
                    duplicate = ProductionTaskImport.objects.filter(owner=record.owner, sha256=record.sha256,
                        object_key=candidate['object_id']).exclude(pk=record.pk).exists()
                    if not duplicate:
                        record.selected_candidate, record.object_key = candidate, candidate['object_id']
                        record.phase, record.state = 'extraction', 'QUEUED'
            else:
                record.extraction = extraction_result(result, record.manifest, record.selected_candidate)
                record.matching = match_result(record.extraction)
                record.result_revision += 1
                record.state = 'REVIEW'
                record.review = {}
        except ImportFailure as exc:
            code = exc.code
    if code:
        record.state = 'FAILED'
    record.error_code = code
    record.save()
    audit(record, 'IMPORT_PARSE_FINISHED')
    return code


def expire_once():
    with transaction.atomic():
        record = ProductionTaskImport.objects.select_for_update(skip_locked=True).filter(
            expires_at__lte=timezone.now(), saved_at__isnull=True).exclude(
            state__in=['EXPIRED', 'SCANNING', 'PARSING']).order_by('expires_at').first()
        if record is None:
            return False
        if record.operation_id and record.operation.state in ('RUNNING', 'CANCELING'):
            return False
        from .saving import reconcile_media
        reconcile_media(record)
        remove_files(record)
        record.state, record.object_key = 'EXPIRED', ''
        record.manifest, record.discovery, record.extraction, record.review, record.matching = {}, {}, {}, {}, {}
        record.candidates, record.selected_candidate = [], {}
        record.save()
        audit(record, 'IMPORT_EXPIRED')
    return True


def recover_media_once():
    """仅核对有持久化归属清单、且能锁定对应导入记录的文件。"""
    from uuid import UUID
    from .saving import reconcile_media
    from .storage import directory
    root = Path(settings.PRODUCTION_IMPORT_ROOT).absolute()
    if not root.exists():
        return
    if root.resolve() != root:
        raise ImportFailure('STORAGE_UNSAFE')
    for entry in root.iterdir():
        try:
            record_id = UUID(entry.name)
        except ValueError:
            continue
        if not (directory(record_id) / 'pending-media.json').exists():
            continue
        with transaction.atomic():
            record = ProductionTaskImport.objects.select_for_update(skip_locked=True).filter(pk=record_id).first()
            if record is not None:
                reconcile_media(record)
