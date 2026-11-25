from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.module_policy import has_permission
from apps.access_control.resource_scopes import has_resource_grant
from apps.access_control.sales_policy import access_for
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_tasks.selectors import accessible_production_tasks
from apps.workshop_config.constants import METAL_WORKSHOP_NAME
from apps.workshop_config.models import CraftType, Operation, PlanCategory, RecordStatus

from .models import WageScheme, WageSchemeStatus
from .selectors import accessible_wage_schemes, allowed_workshop_ids, reporting_source_products
from .services import (
    EDITABLE_SCHEME_STATUSES,
    WAGE_SCHEME_TASK_STATUSES,
    _line_counting_basis,
    bom_options_for_product_line,
)


VIEW = "workshop_reporting.view_wagescheme"
ADD = "workshop_reporting.add_wagescheme"
SUBMIT = "workshop_reporting.submit_wagescheme"
CHANGE = "workshop_reporting.change_wagescheme"


def _links_in_workshop_scope(request, links, permission):
    workshop_ids = allowed_workshop_ids(request, permission=permission)
    return links if workshop_ids is None else links.filter(craft__workshop_id__in=workshop_ids)


def _eligible_links(request):
    can_add = has_permission(request, ADD)
    can_change = has_permission(request, CHANGE)
    if not (can_add or can_change) or not all(has_permission(request, permission) for permission in (VIEW, SUBMIT)):
        raise PermissionDenied("当前账号没有填写并提交工价方案的权限。")
    products = reporting_source_products(request, VIEW).filter(
        schedule__production_task__status__in=WAGE_SCHEME_TASK_STATUSES,
    )
    links = ProductionScheduleProductCraft.objects.filter(
        schedule_product__in=products,
        removed_at__isnull=True,
        craft_type_snapshot=CraftType.INTERNAL,
        craft__craft_type=CraftType.INTERNAL,
        craft__status=RecordStatus.ACTIVE,
        craft__workshop__status=RecordStatus.ACTIVE,
    ).select_related(
        "schedule_product__product_line__production_task", "schedule_product__schedule", "craft__workshop",
    )
    for permission in (VIEW, SUBMIT):
        links = _links_in_workshop_scope(request, links, permission)
    latest_scheme = WageScheme.objects.filter(
        product_line_id=OuterRef("schedule_product__product_line_id"),
        workshop_id=OuterRef("craft__workshop_id"),
        scope_craft_id=OuterRef("craft_id"),
    ).order_by("-version", "-created_at", "-pk")
    links = links.annotate(latest_scheme_id=Subquery(latest_scheme.values("pk")[:1]))
    add_links = links.none()
    if can_add:
        add_links = _links_in_workshop_scope(request, links, ADD)
        if not has_resource_grant(request, ADD, "WORKSHOP"):
            add_links = add_links.filter(schedule_product__schedule__production_task__in=accessible_production_tasks(request))
    if not can_change:
        return add_links
    change_links = _links_in_workshop_scope(request, links, CHANGE).filter(latest_scheme_id__isnull=False)
    return add_links | change_links


def _schemes_in_change_scope(request):
    return accessible_wage_schemes(request, permission=CHANGE) if has_permission(request, CHANGE) else WageScheme.objects.none()


def _editable_schemes(request):
    schemes = _schemes_in_change_scope(request).filter(status__in=EDITABLE_SCHEME_STATUSES)
    scopes = access_for(request)["actions"].get(CHANGE, {}).get("scopes", [])
    if not request.user.is_superuser and not set(scopes) & {"MODULE", "ALL"}:
        schemes = schemes.filter(created_by_employee_id=request.employee.pk)
    return schemes


def _target_data(link, scheme, *, can_edit, can_change):
    schedule_product = link.schedule_product
    product = schedule_product.product_line
    craft = link.craft
    return {
        "schedule_product_id": str(link.schedule_product_id),
        "product_line_id": str(product.pk),
        "task_number": product.production_task.task_number,
        "schedule_date": timezone.localdate(schedule_product.schedule.created_at).isoformat(),
        "product_name": product.product_name_snapshot,
        "product_number": product.product_code_snapshot or product.product_number_snapshot,
        "product_specification": product.specification_snapshot,
        "product_color": product.color_name_snapshot,
        "workshop_id": str(craft.workshop_id),
        "workshop_name": craft.workshop.name,
        "craft_id": str(craft.pk),
        "craft_name": craft.name,
        "scheme": {
            "id": str(scheme.pk), "number": scheme.scheme_number, "status": scheme.status,
            "status_display": scheme.get_status_display(), "can_edit": can_edit, "can_change": can_change,
            "is_change": scheme.parent_scheme_id is not None,
        } if scheme else None,
    }


def mobile_wage_targets(request, task_number):
    links = _eligible_links(request)
    card_order = ("schedule_product__product_line__line_number", "craft__workshop__name", "craft__name", "pk")
    if task_number:
        return links.filter(
            schedule_product__schedule__production_task__task_number__iexact=task_number,
        ).order_by(*card_order)
    editable = _editable_schemes(request).filter(
        pk=OuterRef("latest_scheme_id"), schedule_product_id=OuterRef("schedule_product_id"),
    )
    return links.filter(Q(latest_scheme_id__isnull=True) | Q(Exists(editable))).order_by(
        "-schedule_product__schedule__production_task__created_at",
        "schedule_product__schedule__production_task_id",
        *card_order,
    )


def mobile_wage_target_data(request, links):
    links = list(links)
    schemes = WageScheme.objects.in_bulk({link.latest_scheme_id for link in links if link.latest_scheme_id})
    editable_ids = set(_editable_schemes(request).filter(pk__in=schemes).values_list("pk", flat=True))
    changeable_ids = set(_schemes_in_change_scope(request).filter(
        pk__in=schemes, status=WageSchemeStatus.APPROVED, change_versions__isnull=True,
    ).values_list("pk", flat=True))
    targets = []
    for link in links:
        scheme = schemes.get(link.latest_scheme_id)
        can_edit = link.latest_scheme_id in editable_ids and scheme.schedule_product_id == link.schedule_product_id
        targets.append(_target_data(link, scheme, can_edit=can_edit, can_change=link.latest_scheme_id in changeable_ids))
    return targets


def mobile_wage_change_targets(request, schemes):
    approved = [scheme for scheme in schemes if scheme.status == WageSchemeStatus.APPROVED]
    if not approved or not all(has_permission(request, permission) for permission in (VIEW, CHANGE, SUBMIT)):
        return {}
    links = _eligible_links(request).filter(
        schedule_product__product_line_id__in={scheme.product_line_id for scheme in approved},
        latest_scheme_id__in={scheme.pk for scheme in approved},
    )
    return {
        target["scheme"]["id"]: target for target in mobile_wage_target_data(request, links)
        if target["scheme"] and target["scheme"]["can_change"]
    }


def mobile_wage_form(request, schedule_product_id, craft_id):
    link = get_object_or_404(_eligible_links(request), schedule_product_id=schedule_product_id, craft_id=craft_id)
    craft = link.craft
    product = link.schedule_product
    target, = mobile_wage_target_data(request, [link])
    order_quantity = product.source_quantity_snapshot
    metal = craft.workshop.name == METAL_WORKSHOP_NAME
    category = PlanCategory.METAL if metal else craft.plan_category
    kinds = {PlanCategory.CUTTING: "CUT_PIECE", PlanCategory.SEWING: "SEWN_PART"}
    options = None
    if category == PlanCategory.METAL or category in kinds:
        options = []
        for item in bom_options_for_product_line(product.product_line_id):
            belongs = item["source_type"] == PlanCategory.METAL if category == PlanCategory.METAL else (
                item["source_type"] == PlanCategory.CUTTING and item["component_kind"] == kinds[category]
            )
            if not belongs:
                continue
            quantity, problem = None, ""
            try:
                basis = _line_counting_basis(
                    craft=craft, item={"bom_line_id": item["id"]},
                    bom_options={item["id"]: item}, order_quantity=order_quantity,
                )
                quantity = str(basis["required_quantity"])
            except ValidationError as exc:
                problem = str(exc.detail["lines"])
            options.append({
                "id": item["id"], "identity": item["component_identity"], "name": item["label"],
                "required_quantity": quantity, "problem": problem,
            })
    operations = Operation.objects.filter(craft=craft, status=RecordStatus.ACTIVE).select_related(
        "reporting_unit",
    ).order_by("product_name", "name", "pk")
    return {
        "target": target,
        "order_quantity": str(order_quantity),
        "bom_options": options,
        "requires_product_name": not metal,
        "operations": [{
            "id": str(item.pk), "name": item.name, "product_name": item.product_name,
            "unit": item.reporting_unit.unit_name if item.reporting_unit_id else "",
        } for item in operations],
    }
