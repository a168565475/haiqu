"""Read actual issue, completion, dispatch and receipt batches for the selected products."""
from django.db.models import F
from django.utils import timezone

from apps.inventory.internal_receipt_models import InternalReceiptStatus, InternalSemiFinishedReceiptLine
from apps.material_issues.models import (
    MaterialIssueLine, MaterialIssueStatus, MetalProcessingCompletion, MetalProcessingExternalGoodReturn,
    MetalProcessingExternalHandoff, MetalProcessingOriginalHandoff, MetalProcessingRework,
)
from apps.material_issues.scopes import PLAN_WORKSHOP_NAMES
from apps.outsourcing.models import OutsourcingDispatchLine, OutsourcingOrderStatus, OutsourcingReturnLine
from apps.outsourcing.plan_models import TubePlanReceiptLine
from apps.outsourcing.tube_kinds import output_unit
from apps.outsourcing.tube_models import TubeOutsourcingLine, TubeOutsourcingReceiptLine
from apps.workshop_config.models import OutsourcingCode

from .material_tracking import add_batch

POWDER = OutsourcingCode.POWDER_COATING
SEWING = OutsourcingCode.SEWING


def metal_batches(ids, batches):
    issues = MaterialIssueLine.objects.filter(
        issue__product_line_id__in=ids, issue__production_task_id=F("issue__product_line__production_task_id"),
        issue__status=MaterialIssueStatus.ISSUED, issue__issued_at__isnull=False,
        issue__workshop__name=PLAN_WORKSHOP_NAMES["METAL"], line_type="RAW",
        section_code_snapshot__in=("PROFILE", "TUBE"), issued_quantity__gt=0,
    ).order_by()
    for product, day, number, material, quantity, unit in issues.values_list(
        "issue__product_line_id", "issue__issued_at", "issue__issue_number",
        "material_name_snapshot", "issued_quantity", "unit_snapshot",
    ):
        add_batch(batches[product], "metal_issue", timezone.localdate(day), number,
                  material=material, quantity=quantity, unit=unit)

    for model, field, note in (
        (MetalProcessingCompletion, "good_pieces", ""), (MetalProcessingRework, "completed_pieces", "返工合格"),
    ):
        records = model.objects.filter(
            source__issue_line__issue__product_line_id__in=ids,
            source__issue_line__issue__production_task_id=F("source__issue_line__issue__product_line__production_task_id"),
        ).order_by()
        for product, day, number, material, quantity in records.values_list(
            "source__issue_line__issue__product_line_id", "completion_date", "source__issue_line__issue__issue_number",
            "source__issue_line__material_name_snapshot", field,
        ):
            add_batch(batches[product], "metal_completion", day, number,
                      material=material, quantity=quantity, unit="支", note=note)

    originals = MetalProcessingOriginalHandoff.objects.filter(
        source__issue_line__issue__product_line_id__in=ids,
        original_order__schedule__production_task_id=F("source__issue_line__issue__product_line__production_task_id"),
        original_order__craft__outsourcing_code=POWDER,
    ).order_by()
    for product, day, number, factory, snapshot, quantity in originals.values_list(
        "source__issue_line__issue__product_line_id", "handoff_date", "original_order__order_number",
        "factory__name", "source__source_snapshot", "handoff_pieces",
    ):
        add_batch(batches[product], "coating_dispatch", day, number, party=factory,
                  material=snapshot.get("part_name", ""), quantity=quantity, unit="支")

    for model, kind, date_field, number_field, quantity_field in (
        (MetalProcessingExternalHandoff, "coating_dispatch", "handoff_date", "order__order_number", "handoff_pieces"),
        (MetalProcessingExternalGoodReturn, "coating_receipt", "return_date", "return_number", "good_pieces"),
    ):
        records = model.objects.filter(
            order__source__issue_line__issue__product_line_id__in=ids, order__craft__outsourcing_code=POWDER,
        ).order_by()
        for product, day, number, factory, snapshot, quantity in records.values_list(
            "order__source__issue_line__issue__product_line_id", date_field, number_field,
            "order__factory__name", "order__source__source_snapshot", quantity_field,
        ):
            add_batch(batches[product], kind, day, number, party=factory,
                      material=snapshot.get("part_name", ""), quantity=quantity, unit="支", note="返工")


def external_batches(ids, batches):
    tube_lines = TubeOutsourcingLine.objects.filter(
        order__product_line_id__in=ids, order__craft__outsourcing_code=POWDER, order__is_plan=False,
        order__status__in=("PROCESSING", "COMPLETED"), order__actions__kind="DISPATCH",
    ).order_by()
    for product, day, number, factory, snapshot, quantity in tube_lines.values_list(
        "order__product_line_id", "order__actions__actual_dispatch_date", "order__order_number", "factory__name",
        "snapshot", "quantity",
    ):
        add_batch(batches[product], "coating_dispatch", day, number, party=snapshot.get("factory_name") or factory,
                  material=snapshot.get("part_name", ""), quantity=quantity, unit=snapshot.get("unit") or "支")

    for model in (TubePlanReceiptLine, TubeOutsourcingReceiptLine):
        receipts = model.objects.filter(
            receipt__order__product_line_id__in=ids, receipt__order__craft__outsourcing_code__in=(POWDER, SEWING),
            order_line__order_id=F("receipt__order_id"), received_quantity__gt=0,
        ).order_by()
        if model is TubePlanReceiptLine:
            receipts = receipts.filter(receipt__voided_at__isnull=True)
        for product, day, number, craft, source, factory, snapshot, quantity in receipts.values_list(
            "receipt__order__product_line_id", "receipt__receipt_date", "receipt__receipt_number",
            "receipt__order__craft__outsourcing_code", "receipt__order__source_kind",
            "order_line__factory__name", "order_line__snapshot", "received_quantity",
        ):
            kind = "coating_receipt" if craft == POWDER else "sewn_receipt"
            add_batch(batches[product], kind, day, number, party=snapshot.get("factory_name") or factory,
                      material=snapshot.get("part_name", ""), quantity=quantity, unit=snapshot.get("unit") or output_unit(source))


def legacy_external_batches(ids, batches):
    dispatches = OutsourcingDispatchLine.objects.filter(
        dispatch__order__craft__outsourcing_code=POWDER,
        material_item__allocation__processing_item__order_product__schedule_product__product_line_id__in=ids,
        material_item__allocation__processing_item__order_product__order_id=F("dispatch__order_id"),
    ).exclude(dispatch__order__status=OutsourcingOrderStatus.CANCELLED).order_by()
    for product, day, number, order, factory, material, pieces, quantity, unit in dispatches.values_list(
        "material_item__allocation__processing_item__order_product__schedule_product__product_line_id",
        "dispatch__dispatch_date", "dispatch__dispatch_number", "dispatch__order__order_number",
        "material_item__allocation__factory__name", "material_item__allocation__processing_item__bom_line__part_name",
        "issued_piece_count", "issued_quantity", "unit__unit_name",
    ):
        add_batch(batches[product], "coating_dispatch", day, number or order, party=factory, material=material,
                  quantity=pieces if pieces is not None else quantity, unit="支" if pieces is not None else unit)

    receipts = OutsourcingReturnLine.objects.filter(
        allocation__processing_item__order_product__schedule_product__product_line_id__in=ids,
        allocation__processing_item__order_product__order_id=F("return_record__order_id"),
        return_record__order__craft__outsourcing_code__in=(POWDER, SEWING),
    ).order_by()
    for product, day, number, craft, factory, snapshot, material, quantity, unit, quality in receipts.values_list(
        "allocation__processing_item__order_product__schedule_product__product_line_id",
        "return_record__return_date", "return_record__return_number", "return_record__order__craft__outsourcing_code",
        "allocation__factory__name", "allocation__factory_snapshot", "allocation__processing_item__bom_line__part_name",
        "returned_quantity", "allocation__processing_item__unit_snapshot", "quality",
    ):
        if craft == SEWING and quality != "AVAILABLE":
            continue
        add_batch(batches[product], "coating_receipt" if craft == POWDER else "sewn_receipt", day, number,
                  party=snapshot.get("factory_name") or factory, material=material, quantity=quantity, unit=unit,
                  note="不良隔离" if quality == "DEFECTIVE" else "")


def processing_batches(ids, batches):
    metal_batches(ids, batches)
    external_batches(ids, batches)
    legacy_external_batches(ids, batches)

    sewn = InternalSemiFinishedReceiptLine.objects.filter(
        receipt__schedule_product__product_line_id__in=ids, receipt__plan_category="SEWING",
        receipt__status=InternalReceiptStatus.CONFIRMED,
    ).order_by()
    for product, day, number, material, quantity, unit in sewn.values_list(
        "receipt__schedule_product__product_line_id", "receipt__receipt_date", "receipt__receipt_number",
        "bom_line__part_name", "quantity", "unit__unit_name",
    ):
        add_batch(batches[product], "sewn_receipt", day, number, party="车缝车间",
                  material=material, quantity=quantity, unit=unit)
