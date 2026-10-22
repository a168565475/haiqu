"""Authorization for non-sales modules. All activation remains explicit."""
from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from . import sales_policy
from .module_operations import ACTION_OVERRIDES, LEGACY_ALIASES


def enabled():
    return bool(getattr(settings, 'MODULE_ACCESS_ENABLED', False))


def action_permission(request, view):
    mapping = dict(getattr(view, 'action_permission_map', {}))
    mapping.update(ACTION_OVERRIDES.get(type(view).__name__, {}))
    action = getattr(view, 'action', None)
    from .resource_scopes import enabled as scopes_enabled
    if scopes_enabled() and type(view).__name__ == 'SampleRequestViewSet' and action in {'production_report', 'form'}:
        codes = list(sample_report_permissions())
        return codes if action == 'production_report' else ['samples.change_samplerequest', 'samples.complete_sample_requirements', *codes]
    return mapping.get(f'{action}.{request.method}') or mapping.get(action)


def has_permission(request, code):
    if not enabled():
        return request.user.has_perm(code)
    access = sales_policy.access_for(request)
    if not access['active']:
        return False
    if access['is_superuser'] or access['actions'].get(code, {}).get('scopes'):
        return True
    legacy = {row['permission'] for row in access['legacy_sources']}
    return code in legacy or LEGACY_ALIASES.get(code) in legacy


def has_module_grant(request, *modules):
    from .catalog import module_for
    access = sales_policy.access_for(request)
    return access['active'] and (access['is_superuser'] or any(
        module_for(code) in modules and 'MODULE' in entry['scopes']
        for code, entry in access['actions'].items()))


def has_operation(request, code, legacy):
    return has_permission(request, code) if enabled() else request.user.has_perm(legacy)


def can_sample(request, sample, code, legacy=None):
    if request is None:
        return False
    if not enabled():
        return request.user.has_perm(legacy or code)
    access = sales_policy.access_for(request)
    if not access['active']:
        return False
    if access['is_superuser'] or set(access['actions'].get(code, {}).get('scopes', [])) & {'MODULE', 'ALL'}:
        return True
    from apps.samples.selectors import accessible_sample_requests
    return accessible_sample_requests(request, code).filter(pk=sample.pk).exists()


def resource_permissions(request, instance, record_ids=None):
    from .catalog import module_for
    from apps.samples.selectors import accessible_sample_requests
    from apps.workflow.selectors import accessible_tasks
    access = sales_policy.access_for(request)
    from .catalog import PERMISSION_CODES
    candidates = (set(PERMISSION_CODES) if access['is_superuser'] else set(access['actions'])) | {row['permission'] for row in access['legacy_sources']}
    candidates.update(code for code in LEGACY_ALIASES if has_permission(request, code))
    app = instance._meta.app_label
    cache = getattr(request, '_module_resource_ids', None)
    if cache is None:
        cache = request._module_resource_ids = {}
    result = []
    for code in sorted(candidates):
        if module_for(code) != app or (app == 'workflow' and 'businesstask' not in code):
            continue
        if access['is_superuser'] or (app == 'samples' and set(access['actions'].get(code, {}).get('scopes', [])) & {'MODULE', 'ALL'}):
            result.append(code)
            continue
        cache_key = (app, code, tuple(record_ids) if record_ids is not None else None)
        if cache_key not in cache:
            queryset = accessible_sample_requests(request, code) if app == 'samples' else accessible_tasks(request, 'ANY_ACCESS', permission=code)
            cache[cache_key] = set(queryset.filter(pk__in=record_ids).values_list('pk', flat=True)) if record_ids is not None else queryset
        if record_ids is not None:
            if instance.pk in cache[cache_key]:
                result.append(code)
            continue
        key = (app, code, instance.pk)
        if key not in cache:
            cache[key] = cache[cache_key].filter(pk=instance.pk).exists()
        if cache[key]:
            result.append(code)
    return result


from rest_framework import serializers


class ModuleAccessSerializerMixin(serializers.Serializer):
    allowed_permissions = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and enabled():
            parent = getattr(self, 'parent', None)
            records = getattr(parent, 'instance', None) if isinstance(parent, serializers.ListSerializer) else None
            if records is not None and not hasattr(self, '_permission_page_ids'):
                self._permission_page_ids = [row.pk for row in records]
            data['allowed_permissions'] = resource_permissions(request, instance, getattr(self, '_permission_page_ids', None))
        return data


def prohibit_self_approval(actor, submitter_id):
    if not enabled():
        return
    if submitter_id is None:
        raise PermissionDenied('该申请缺少可核实的提交人，请由申请人重新提交后再审批。')
    if getattr(actor, 'pk', None) == submitter_id:
        user = getattr(actor, 'user', None)
        if (actor.status == 'ACTIVE' and actor.archived_at is None
                and user is not None and user.is_active and user.is_superuser):
            return
        raise PermissionDenied('提交人不能审批自己提交的申请。')


def prohibit_audit_self_approval(actor, object_type, object_id, actions):
    if not enabled():
        return
    from apps.audit.models import AuditLog
    submitter = AuditLog.objects.filter(object_type=object_type, object_id=object_id,
        action__in=actions).order_by('-occurred_at', '-id').values_list('actor_employee_id', flat=True).first()
    prohibit_self_approval(actor, submitter)


def sample_report_permissions():
    from .resource_scopes import enabled as scopes_enabled
    return ('access_control.productionreport_sample', 'access_control.metalreport_sample', 'access_control.cuttingreport_sample') if scopes_enabled() else ('access_control.productionreport_sample',)


def can_report_sample(request, sample, stage=None):
    codes = sample_report_permissions()
    if stage and len(codes) > 1:
        codes = (codes[0], 'access_control.metalreport_sample' if stage == 'metalwork' else 'access_control.cuttingreport_sample')
    return any(can_sample(request, sample, code, 'samples.change_samplerequest') for code in codes)


def reportable_samples(request):
    from apps.samples.selectors import accessible_sample_requests
    result = accessible_sample_requests(request, sample_report_permissions()[0])
    for code in sample_report_permissions()[1:]:
        result = result | accessible_sample_requests(request, code)
    return result


def require_sample_reporting_changes(request, sample, rows):
    """All form/item writers check report changes and exact legacy object scope."""
    if not enabled():
        return
    fields = ('cutting_reported_quantity', 'metalwork_reported_quantity', 'cutting_completed', 'metalwork_completed')
    existing = {str(item.pk): item for item in sample.items.all()}
    for row in rows:
        previous = existing.get(str(row.get('id', '')))
        if not any(field in row and row[field] != (getattr(previous, field) if previous else 0) for field in fields):
            continue
        changed_stages = [stage for stage in ('metalwork', 'cutting')
                          if any(field in row and row[field] != (getattr(previous, field) if previous else 0)
                                 for field in (f'{stage}_reported_quantity', f'{stage}_completed'))]
        if all(can_report_sample(request, sample, stage) for stage in changed_stages):
            continue
        old = 'samples.change_sampleitem' if previous else 'samples.add_sampleitem'
        if sales_policy.legacy_permission(request, old):
            from apps.samples.selectors import _legacy_accessible_sample_requests
            if _legacy_accessible_sample_requests(request, old.split('.', 1)[1]).filter(pk=sample.pk).exists():
                continue
        raise PermissionDenied('修改样品报工数量或完成状态需要独立的报工权限。')
