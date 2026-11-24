from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from .models import Bom, BomLine
from .nesting_models import BomNestingJob
from .nesting_storage import read_upload, remove_new_source, write_source
from .selectors import accessible_boms


ACTIVE_STATUSES = ["QUEUED", "RUNNING"]
ACTION_PERMISSIONS = {action: "boms.change_bom" for action in
                      ["create", "list", "retrieve", "calculate", "cancel", "source", "preview", "dxf"]}


def get_bom(request, bom_id, *, lock=False):
    query = accessible_boms(request)
    if lock:
        query = query.select_for_update()
    try:
        return query.get(pk=bom_id)
    except Bom.DoesNotExist as exc:
        raise NotFound("未找到可访问的 BOM。") from exc


def scoped_jobs(request, bom):
    return BomNestingJob.objects.filter(bom=bom).filter(Q(draft_key__isnull=True) | Q(owner_user=request.user))


def get_job(request, bom, job_id, *, lock=False):
    query = scoped_jobs(request, bom)
    if lock:
        query = query.select_for_update()
    try:
        return query.get(pk=job_id)
    except BomNestingJob.DoesNotExist as exc:
        raise NotFound("未找到当前 BOM 的可访问排料记录。") from exc


def validate_saved_line(bom, line_id):
    try:
        line = BomLine.objects.select_related("section").get(pk=line_id, section__bom=bom)
    except BomLine.DoesNotExist as exc:
        raise NotFound("未找到当前 BOM 的面料行。") from exc
    snapshot = line.material_selection_snapshot or {}
    if (line.section.section_type != "FABRIC" or line.section.title.strip() != "面料类"
            or line.unit != "米" or (snapshot and (snapshot.get("category_key") != "FABRIC"
                or snapshot.get("processing_state") != "RAW" or snapshot.get("unit_name") != "米"))):
        raise ValidationError({"line_id": "仅支持面料类中单位为米的原料行，不能使用裁片半成品。"})


def bind_draft_jobs(*, bom, owner_user, new_lines_by_client_key):
    """由 BOM 保存事务调用；只把本人新增面料行的历史转到本次真实行 ID。"""
    if not new_lines_by_client_key:
        return
    lines = {str(key): line for key, line in new_lines_by_client_key.items()}
    jobs = BomNestingJob.objects.select_for_update().filter(
        bom=bom, owner_user=owner_user, line_id__isnull=True, draft_key__in=lines,
    ).order_by("id")
    valid_lines = {}
    for job in jobs:
        key = str(job.draft_key)
        line = lines[key]
        if key not in valid_lines:
            try:
                validate_saved_line(bom, line.pk)
            except (NotFound, ValidationError):
                valid_lines[key] = False
            else:
                valid_lines[key] = True
        if valid_lines[key]:
            job.line_id, job.draft_key = line.pk, None
            job.save(update_fields=["line_id", "draft_key", "updated_at"])


def lock_actor(request):
    # 同一操作者跨 BOM 提交也串行核对队列限额；不阻塞外键读取。
    get_user_model().objects.select_for_update(no_key=True).get(pk=request.user.pk)


def check_queue_limit(user, *, exclude=None):
    query = BomNestingJob.objects.filter(requested_by_user=user, status__in=ACTIVE_STATUSES)
    if exclude:
        query = query.exclude(pk=exclude)
    if query.count() >= 4:
        raise ValidationError("当前账号已有 4 个待处理排料任务，请等待完成或取消后再试。")


def create_job(request, bom_id, data):
    name, source, digest = read_upload(data["file"])
    job = None
    try:
        with transaction.atomic():
            lock_actor(request)
            bom = get_bom(request, bom_id, lock=True)
            require_matching_etag(request, bom)
            if data.get("line_id"):
                validate_saved_line(bom, data["line_id"])
            check_queue_limit(request.user)
            if BomNestingJob.objects.filter(owner_user=request.user,
                    created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 30:
                raise ValidationError("当前账号一小时内最多上传 30 个排料文件，请稍后重试。")
            job = BomNestingJob(bom=bom, owner_user=request.user, requested_by_user=request.user,
                line_id=data.get("line_id"), draft_key=data.get("draft_key"), target_snapshot=data["target_snapshot"],
                original_name=name, size_bytes=len(source), sha256=digest, source_unit=data["source_unit"])
            job.scan_status = write_source(job, source)
            job.save(force_insert=True)
        return job
    except BaseException:
        if job is not None:
            remove_new_source(job)
        raise


@transaction.atomic
def calculate_job(request, bom_id, job_id, parameters):
    lock_actor(request)
    bom = get_bom(request, bom_id)
    job = get_job(request, bom, job_id, lock=True)
    require_matching_etag(request, job)
    if job.line_id:
        validate_saved_line(bom, job.line_id)
    if job.status in ACTIVE_STATUSES:
        raise Conflict("当前排料任务仍在处理中，请先等待或取消。")
    if job.phase in ('CODEX', 'REFINE'):
        raise Conflict("旧本地排料记录只读，请重新上传并交给 Codex 执行。")
    if not job.analysis or not job.analysis_digest:
        raise Conflict("尚未完成裁片提取，请重新上传或等待提取完成。")
    expected = {piece["id"] for piece in job.analysis["pieces"]}
    if {piece["piece_id"] for piece in parameters["pieces"]} != expected:
        raise ValidationError({"pieces": "必须逐一填写所有提取裁片，不能遗漏或加入未知裁片。"})
    check_queue_limit(request.user, exclude=job.pk)
    job.parameters = {**parameters, "width_mm": str(parameters["width_mm"]), "gap_mm": str(parameters["gap_mm"])}
    job.requested_by_user = request.user
    job.status, job.phase, job.result = "QUEUED", "NEST", {}
    job.optimization, job.operation = {}, None
    job.execution, job.artifacts = {}, []
    job.error_code, job.error_message = "", ""
    job.started_at, job.finished_at = None, None
    job.attempt_no += 1
    job.save()
    return job


@transaction.atomic
def cancel_job(request, bom_id, job_id):
    bom = get_bom(request, bom_id)
    job = get_job(request, bom, job_id, lock=True)
    require_matching_etag(request, job)
    job.status, job.result = "CANCELED", {}
    job.error_code, job.error_message = "", ""
    job.finished_at = timezone.now()
    job.attempt_no += 1
    job.save()
    if job.operation_id:
        from .nesting_codex import cancel_operation
        transaction.on_commit(lambda operation_id=job.operation_id: cancel_operation(operation_id))
    return job


def worker_allowed(job):
    user = get_user_model().objects.filter(pk=job.requested_by_user_id).first()
    request = SimpleNamespace(user=user, method="POST")
    view = SimpleNamespace(action="calculate", action_permission_map=ACTION_PERMISSIONS)
    if not HasActiveEmployee().has_permission(request, view) or not BusinessActionPermission().has_permission(request, view):
        return False
    if job.draft_key and job.owner_user_id != user.pk:
        return False
    if not accessible_boms(request).filter(pk=job.bom_id).exists():
        return False
    if job.line_id:
        try:
            validate_saved_line(job.bom, job.line_id)
        except (NotFound, ValidationError):
            return False
    return True
