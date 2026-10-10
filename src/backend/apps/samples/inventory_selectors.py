from django.db.models import Exists, ExpressionWrapper, F, IntegerField, OuterRef, Prefetch, Subquery, Sum, Value, Q
from django.db.models.functions import Coalesce

from .models import (
    SampleInventoryLine,
    SampleInventoryReceipt,
    SampleItem,
    SampleMaterialRequest,
    SampleRequestStatus,
    SampleParameterImage,
    SampleWorkflowRecord,
    SampleWorkflowStage,
    SampleMaterialIssueStatus,
)


def sample_inventory_lines_with_context(queryset=None):
    if queryset is None:
        queryset = SampleInventoryLine.objects.all()
    return queryset.select_related(
        "receipt",
        "receipt__submitted_by_employee",
        "sample_item",
        "sample_item__sample_request",
        "sample_item__sample_product",
        "finished_goods_receipt__location__zone__warehouse",
    ).annotate(
        available_quantity=ExpressionWrapper(
            F("received_quantity") - F("outbound_quantity") - F("loaned_quantity"),
            output_field=IntegerField(),
        )
    )


def sample_inventory_receipts_with_detail(queryset=None):
    if queryset is None:
        queryset = SampleInventoryReceipt.objects.all()
    cumulative_received = (
        SampleInventoryLine.objects.filter(sample_item_id=OuterRef("sample_item_id"))
        .values("sample_item_id")
        .annotate(total=Sum("received_quantity"))
        .values("total")[:1]
    )
    workflow_records = SampleWorkflowRecord.objects.filter(
        sample_request_id=OuterRef("sample_item__sample_request_id")
    )
    detail_lines = (
        sample_inventory_lines_with_context()
        .annotate(
            cumulative_received=Coalesce(
                Subquery(cumulative_received),
                Value(0),
                output_field=IntegerField(),
            ),
            has_pmc_approval=Exists(
                workflow_records.filter(stage=SampleWorkflowStage.PMC_APPROVED)
            ),
            has_finished_workflow=Exists(
                workflow_records.filter(stage=SampleWorkflowStage.WORKFLOW_FINISHED)
            ),
        )
        .order_by("created_at", "id")
    )
    return queryset.select_related("submitted_by_employee").prefetch_related(
        Prefetch("lines", queryset=detail_lines, to_attr="detail_lines")
    )


def eligible_sample_items_for_inventory(queryset=None):
    if queryset is None:
        queryset = SampleItem.objects.all()
    workflow_records = SampleWorkflowRecord.objects.filter(
        sample_request_id=OuterRef("sample_request_id")
    )
    parameter_images = SampleParameterImage.objects.filter(
        sample_request_id=OuterRef("sample_request_id"),
        archived_at__isnull=True,
    )
    from .models import SampleMaterialIssue
    material_issue = SampleMaterialIssue.objects.filter(
        material_request__sample_request_id=OuterRef("sample_request_id"),
        status=SampleMaterialIssueStatus.ISSUED,
    )
    no_materials = SampleMaterialRequest.objects.filter(
        sample_request_id=OuterRef("sample_request_id"),
        no_materials=True,
    )
    return (
        queryset.select_related("sample_request", "sample_product")
        .filter(
            sample_request__archived_at__isnull=True,
            sample_request__status=SampleRequestStatus.FINISHED,
            sample_quantity__isnull=False,
            sample_quantity__gt=0,
            metalwork_completed=True,
            cutting_completed=True,
        )
        .annotate(
            has_pmc_approval=Exists(
                workflow_records.filter(stage=SampleWorkflowStage.PMC_APPROVED)
            ),
            has_finished_workflow=Exists(
                workflow_records.filter(stage=SampleWorkflowStage.WORKFLOW_FINISHED)
            ),
            cumulative_received=Coalesce(
                Sum("inventory_lines__received_quantity"),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .annotate(
            has_material_readiness=Exists(workflow_records.filter(stage=SampleWorkflowStage.MATERIALS_READY)),
            has_metalwork_parameters=(
                Exists(workflow_records.filter(stage=SampleWorkflowStage.METALWORK_PARAMETERS, business_file__isnull=False))
                | Exists(parameter_images.filter(parameter_type="METALWORK"))
            ),
            has_cutting_parameters=(
                Exists(workflow_records.filter(stage=SampleWorkflowStage.CUTTING_PARAMETERS, business_file__isnull=False))
                | Exists(parameter_images.filter(parameter_type="CUTTING"))
            ),
            has_sample_material_issue=Exists(material_issue),
            sample_has_no_materials=Exists(no_materials),
        )
        .filter(has_finished_workflow=True)
        .filter(Q(sample_request__application_payload_hash='', has_pmc_approval=True)
                | (~Q(sample_request__application_payload_hash='') & Q(has_material_readiness=True,
                   has_metalwork_parameters=True, has_cutting_parameters=True)
                   & (Q(sample_has_no_materials=True) | Q(has_sample_material_issue=True))))
        .annotate(
            remaining_quantity=ExpressionWrapper(
                F("sample_quantity") - F("cumulative_received"),
                output_field=IntegerField(),
            )
        )
        .filter(remaining_quantity__gt=0)
        .order_by("-sample_request__requested_at", "sample_request_id", "line_number", "id")
    )
