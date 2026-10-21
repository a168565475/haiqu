from django.db.migrations.recorder import MigrationRecorder

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import OrganizationUnit
from .models import WeComDepartmentMapping


def schema_is_ready():
    return MigrationRecorder.Migration.objects.filter(app="wecom", name="0004_wecom_department_mapping").exists()


def mapping_snapshot(corp_id):
    rows = WeComDepartmentMapping.objects.filter(corp_id=corp_id).select_related("organization_unit").order_by("wecom_department_id")
    return {"mappings": [{
        "id": str(row.pk), "wecom_department_id": row.wecom_department_id,
        "organization_unit_id": str(row.organization_unit_id) if row.organization_unit_id else None,
        "updated_at": row.updated_at.isoformat(),
        "organization_etag": etag_for_instance(row.organization_unit) if row.organization_unit_id else None,
        "organization_active": bool(row.organization_unit_id and row.organization_unit.status == "ACTIVE"
                                    and row.organization_unit.archived_at is None),
        "organization_name": row.organization_unit.unit_name if row.organization_unit_id else "",
    } for row in rows]}


def organization_snapshot():
    return [{"id": str(unit.pk), "unit_code": unit.unit_code, "unit_name": unit.unit_name,
             "status": unit.status, "archived": unit.archived_at is not None, "etag": etag_for_instance(unit)}
            for unit in OrganizationUnit.objects.order_by("id")]
