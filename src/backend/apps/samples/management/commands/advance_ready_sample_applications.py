"""预检旧版材料齐备停留单；显式 --apply --sample-id 才推进指定单据。"""
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.samples.models import SampleRequest, SampleRequestStatus
from apps.samples.production_services import enter_parameter_stage
from apps.samples.services import SAMPLE_FIELDS, _write_sample_records
from apps.customers.services import model_snapshot


def eligible(sample):
    record = getattr(sample, 'material_request', None)
    if (not sample.application_payload_hash or sample.status != SampleRequestStatus.MATERIALS_READY
            or sample.archived_at or sample.customer_account.archived_at or not record
            or not record.submitted_at or not record.reviewed_at or not record.reviewed_by_id
            or getattr(record, 'procurement_request', None)):
        return False
    demand = record.draft.get('lines', [])
    supply = record.warehouse_draft.get('lines', [])
    try:
        required = {row['key']: Decimal(row['quantity']) for row in demand}
        provided = {row['key']: Decimal(row['supplyQuantity']) for row in supply}
        return bool(required) and len(required) == len(demand) == len(provided) == len(supply) and required == provided and all(q.is_finite() and q > 0 for q in required.values())
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return False


class Command(BaseCommand):
    help = '默认只预检材料齐备的新申请；--apply 必须指定 --sample-id（可重复）。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--sample-id', action='append', default=[])

    @transaction.atomic
    def handle(self, *args, **options):
        if options['apply'] and not options['sample_id']:
            raise CommandError('推进前必须预检，并用 --sample-id 指定已核实的申请。')
        queryset = SampleRequest.objects.filter(status=SampleRequestStatus.MATERIALS_READY)
        if options['sample_id']:
            queryset = queryset.filter(pk__in=options['sample_id'])
        if options['apply']:
            queryset = queryset.select_for_update()
        for sample in queryset:
            ok = eligible(sample)
            self.stdout.write(f'{sample.pk} {sample.request_number}: {"可推进" if ok else "跳过，依据不完整"}')
            if ok and options['apply']:
                before = model_snapshot(sample, SAMPLE_FIELDS)
                actor = sample.material_request.reviewed_by
                enter_parameter_stage(sample, actor_employee=actor, note='衔接历史停留的新申请：已有仓库足量核对记录。')
                _write_sample_records(sample_request=sample, action='MATERIALS_READY_ADVANCED', actor_employee=actor,
                                      request=None, before_data=before, note='按已核实仓库记录推进至参数上传，未补写生产完成状态。')
