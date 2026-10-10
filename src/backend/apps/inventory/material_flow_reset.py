"""已批准 V1.3 材料账重置：只读清单、精确执行和事务内保留校验。"""
import hashlib
import json
import uuid
from decimal import Decimal

from django.apps import apps
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone


VERSION = 'material-flow-v1.3-s8-1'
# 顺序为子表在前；绝不依赖 CASCADE 猜测删除范围。
DELETE_LABELS = (
    'material_issues.MaterialIssueBatchAllocation',
    'material_issues.MaterialIssueAuditEvent', 'material_issues.MaterialIssueLine',
    'material_issues.MaterialIssue',
    'outsourcing.OutsourcingRawReturnLine', 'outsourcing.OutsourcingRawReturn',
    'outsourcing.OutsourcingReconciliationEntry', 'outsourcing.OutsourcingReconciliation',
    'outsourcing.OutsourcingReturnLine', 'outsourcing.OutsourcingReturn',
    'outsourcing.OutsourcingDispatchLine', 'outsourcing.OutsourcingDispatch',
    'outsourcing.OutsourcingMaterialItem', 'outsourcing.OutsourcingFactoryAllocation',
    'outsourcing.OutsourcingProcessingItem', 'outsourcing.OutsourcingOrderProduct',
    'outsourcing.OutsourcingOrder',
    'inventory.MaterialStockMovement', 'inventory.SemiFinishedStockMovement',
    'inventory.MaterialStockBalance', 'inventory.SemiFinishedStockBalance',
    'samples.SampleMaterialArrival',
    'procurement.PurchaseReturnLine', 'procurement.PurchaseReturn',
    'inventory.MaterialInboundLine', 'inventory.MaterialInbound',
    'material_issues.RequirementContribution', 'material_issues.OrderMaterialRequirement',
    'procurement.SupplierPurchaseSheetLineImage', 'procurement.SupplierPurchaseSheetSealImage',
    'procurement.SupplierPurchaseSheet',
)
UPDATE_LABELS = ('procurement.PurchaseOrder', 'procurement.PurchaseOrderLine')


def canonical(value):
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def table_snapshot():
    """原始 SQL 可用于迁移前后，不导出业务内容；所有表均纳入漂移检测。"""
    result = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f'SELECT row_to_json(t)::text FROM {connection.ops.quote_name(table)} t')
            hashes, ids = [], []
            for (raw,) in cursor:
                row = json.loads(raw, parse_float=Decimal)
                hashes.append(digest(row))
                if 'id' in row:
                    ids.append(str(row['id']))
            result[table] = {'count': len(hashes), 'sha256': digest(sorted(hashes)), 'ids': sorted(ids)}
    return result


def schema_snapshot():
    with connection.cursor() as cursor:
        cursor.execute("""SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2""")
        columns = cursor.fetchall()
        cursor.execute("""SELECT c.relname, k.conname, pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2""")
        constraints = cursor.fetchall()
        cursor.execute("""SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2""")
        triggers = cursor.fetchall()
        cursor.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2")
        indexes = cursor.fetchall()
        cursor.execute("""SELECT p.proname, pg_get_function_identity_arguments(p.oid), pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prokind IN ('f','p') ORDER BY 1,2""")
        functions = cursor.fetchall()
    return {'columns': columns, 'constraints': constraints, 'triggers': triggers, 'indexes':indexes, 'functions':functions}


def database_identity():
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database(), oid FROM pg_database WHERE datname=current_database()')
        name, oid = cursor.fetchone()
    return {'name': name, 'oid': oid, 'host': str(connection.settings_dict['HOST']),
            'port': str(connection.settings_dict['PORT'])}


def pipe_reset_values(line):
    from apps.boms.material_flow_calculations import pipe_plan
    from apps.procurement.pipe_purchase import pipe_source_snapshot
    from apps.samples.pipe_materials import sample_pipe_snapshot
    warning = ''
    values = dict(unit_price=None, amount=None, actual_purchase_quantity=None,
                  actual_bar_count=None, actual_purchase_meters=None, quantity_difference_reason='',
                  raw_bar_length_m=None, suggested_bar_count=None, suggested_purchase_meters=None,
                  calculation_snapshot={'requires_source_confirmation':True}, required_quantity=None, source_unit_text='米',
                  source_quantity_field='suggested_purchase_meters', source_quantity_text='',
                  quantity_parse_status='MISSING')
    try:
        if line.purchase_order.source_type == 'SAMPLE':
            binding = line.sample_material_source
            row = next(r for r in binding.procurement_request.lines if r['key'] == str(binding.line_key))
            plan = sample_pipe_snapshot(binding.procurement_request, row)
        elif line.bom_line_id:
            bom_line = line.bom_line
            if bom_line.section.section_type != 'PROFILE':
                raise ValueError('采购管材与 BOM 分类不一致')
            from apps.procurement.reset_sources import validate_purchase_description
            validate_purchase_description(line,bom_line)
            try:
                plan = pipe_source_snapshot(bom_line)
            except (ValueError, TypeError) as error:
                raise
            except Exception as error:
                from rest_framework.exceptions import APIException
                if not isinstance(error, APIException):
                    raise
                # 合法旧输入仅提供可核对的采购建议；不修改或假装已确认 BOM。
                plan = pipe_plan(cutting_length_mm=bom_line.cutting_length_mm or bom_line.length_value,
                    pieces_per_product=bom_line.pieces_per_product or bom_line.unit_consumption,
                    pieces_per_bar=bom_line.pieces_per_bar or (bom_line.raw_values or {}).get('tube_cut_piece_count'),
                    order_quantity=bom_line.section.bom.order_quantity)
                plan = {**plan, 'bom_id': str(bom_line.section.bom_id), 'bom_line_id': str(bom_line.pk),
                        'component_identity': str(bom_line.component_identity), 'requires_source_confirmation': True}
                warning = f'已按明确旧参数计算建议，须补齐并重新确认 BOM 后刷新采购来源：{error}'
        else:
            raise ValueError('缺少明确的管材来源')
        values.update({key: plan[key] for key in ('raw_bar_length_m','suggested_bar_count','suggested_purchase_meters')})
        values.update(calculation_snapshot=plan, required_quantity=plan['suggested_purchase_meters'],
                      source_quantity_text=str(plan['suggested_purchase_meters']), quantity_parse_status='READY')
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as error:
        warning = f'缺少合法管材参数，数量留空，确认采购前必须补齐：{error}'
    except Exception as error:
        from django.core.exceptions import ObjectDoesNotExist
        from rest_framework.exceptions import APIException
        if not isinstance(error, (ObjectDoesNotExist, APIException)):
            raise
        warning = f'管材来源校验未通过，数量留空：{error}'
    return values, warning


def build_manifest():
    from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequestAllocation
    updates, warnings, blockers = [], [], []
    lines_by_order = {}
    for line in PurchaseOrderLine.objects.select_related('purchase_order', 'bom_line__section__bom').order_by('pk'):
        if line.section_type_snapshot == 'PROFILE':
            values, warning = pipe_reset_values(line)
            updates.append({'model': 'procurement.PurchaseOrderLine', 'id': str(line.pk), 'values': values})
            if warning:
                warnings.append({'model': 'procurement.PurchaseOrderLine', 'id': str(line.pk), 'reason': warning})
            amount = None
        else:
            from apps.procurement.reset_sources import reset_source_snapshot
            snapshot, warning = reset_source_snapshot(line)
            values = {'calculation_snapshot':{**line.calculation_snapshot,'reset_source':snapshot}}
            if not warning and not snapshot.get('sample') and snapshot['unit'] == line.source_unit_text:
                values['required_quantity'] = snapshot['quantity']
                values.update(source_quantity_field=snapshot['source_quantity_field'],
                              source_quantity_text=snapshot['source_quantity_text'],quantity_parse_status='READY')
            updates.append({'model':'procurement.PurchaseOrderLine','id':str(line.pk),'values':values})
            if warning:
                warnings.append({'model':'procurement.PurchaseOrderLine','id':str(line.pk),'reason':warning})
            amount = line.amount
        lines_by_order.setdefault(line.purchase_order_id, []).append(amount)
    for order in PurchaseOrder.objects.order_by('pk'):
        amounts = lines_by_order.get(order.pk, [])
        total = sum(amounts, Decimal('0')) if amounts and all(a is not None for a in amounts) else None
        updates.append({'model': 'procurement.PurchaseOrder', 'id': str(order.pk),
                       'values': {'status': 'DRAFT', 'completed_at': None, 'completed_by_employee_id': None,
                                  'completion_remark': '', 'total_amount': total}})
    linked = PurchaseRequestAllocation.objects.filter(supplier_purchase_sheet__isnull=False)
    if linked.exists():
        blockers.append({'reason': '采购申请分配引用待删除供应商表，未批准分配重置规则；禁止自动扩删',
                         'ids': [str(x) for x in linked.order_by('pk').values_list('pk', flat=True)]})
    tables = table_snapshot()
    deleted = {apps.get_model(label)._meta.db_table for label in DELETE_LABELS}
    changed = {apps.get_model(label)._meta.db_table for label in UPDATE_LABELS}
    # 捕捉批准清单之外的外键依赖，不采用级联删除绕开保护。
    with connection.cursor() as cursor:
        cursor.execute("""SELECT a.relname, b.relname, k.conname FROM pg_constraint k
            JOIN pg_class a ON a.oid=k.conrelid JOIN pg_class b ON b.oid=k.confrelid
            WHERE k.contype='f' ORDER BY 1,2,3""")
        dependencies = [list(row) for row in cursor.fetchall() if row[0] in deleted or row[1] in deleted]
    for source, target, constraint in dependencies:
        if target in deleted and source not in deleted and tables.get(source, {}).get('count', 0):
            # 具体引用可能为空，数据库约束仍将在执行中逐项检查。
            if source != 'purchase_request_allocation':
                blockers.append({'reason': '清单外非空表存在反向依赖，需核对', 'table': source, 'target': target, 'constraint': constraint})
    manifest = {'version': VERSION, 'database': database_identity(), 'tables': tables,
                'schema': schema_snapshot(), 'delete_models': list(DELETE_LABELS),
                'updates': updates, 'warnings': warnings, 'blockers': blockers,
                'protected_tables': sorted(set(tables)-deleted-changed), 'dependencies': dependencies,
                'physical_files': 'PRESERVE_ALL', 'approval_scope':
                ('S9_BUSINESS_RESET' if database_identity()['name']=='haiqu_erp' else 'S8_REHEARSAL_ONLY')}
    manifest = json.loads(canonical(manifest))
    manifest['sha256'] = digest(manifest)
    return manifest


def preview():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return build_manifest()


def execute(manifest, approved_sha256, target_database, *, operator, authorization=None):
    from .models import PublicStockMovement
    from .public_stock_mode import public_flow_enabled
    if public_flow_enabled() or PublicStockMovement.objects.exists():
        raise CommandError('已有公共库存入口或流水，旧材料账重置工具不适用，禁止执行。')
    if not isinstance(operator, str) or not operator.strip() or len(operator.strip()) > 150:
        raise CommandError('必须填写可追溯的操作人员标识（最多150字）。')
    if approved_sha256 != manifest.get('sha256') or digest({k:v for k,v in manifest.items() if k != 'sha256'}) != approved_sha256:
        raise CommandError('清单摘要不匹配，禁止执行。')
    identity = database_identity()
    if target_database != identity['name'] or identity != manifest['database']:
        raise CommandError('数据库身份不匹配，禁止执行。')
    from .reset_authorization import validate_reset_authorization
    validate_reset_authorization(identity,approved_sha256,operator,authorization)
    if manifest['blockers']:
        raise CommandError('清单存在未解决依赖，禁止执行。')
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('material-flow-reset-v1',0))")
            # 全表锁堵住新插入和并发修改。锁失败即回滚，不等待无限维护窗口。
            for table in sorted(manifest['tables']):
                cursor.execute(f'LOCK TABLE {connection.ops.quote_name(table)} IN SHARE ROW EXCLUSIVE MODE')
        current = build_manifest()
        if current['sha256'] != approved_sha256:
            raise CommandError('数据或结构已漂移，请重新预览并审核清单。')
        from apps.audit.models import AuditLog
        if AuditLog.objects.filter(object_type='MATERIAL_FLOW_RESET', action='RESET_COMPLETED').exists():
            raise CommandError('此库已执行过本次材料账重置，禁止重复重置后续新采购。')
        validate_reset_authorization(identity,approved_sha256,operator,authorization)
        with connection.cursor() as cursor:
            for label in DELETE_LABELS:
                table = apps.get_model(label)._meta.db_table
                cursor.execute(f'DELETE FROM {connection.ops.quote_name(table)} WHERE id = ANY(%s::uuid[])', [manifest['tables'][table]['ids']])
        changed_at = timezone.now()
        for update in manifest['updates']:
            apps.get_model(update['model']).objects.filter(pk=update['id']).update(**update['values'], updated_at=changed_at)
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        after = table_snapshot()
        for table in manifest['protected_tables']:
            if after[table] != manifest['tables'][table]:
                raise CommandError(f'保留对象被改变，整单回滚：{table}')
        for label in DELETE_LABELS:
            if after[apps.get_model(label)._meta.db_table]['count']:
                raise CommandError('清理后仍有旧数据，整单回滚。')
        if canonical(schema_snapshot()) != canonical(manifest['schema']):
            raise CommandError('清理过程结构漂移，整单回滚。')
        event_id = uuid.uuid4()
        from apps.procurement.models import PurchaseOrder
        sample_ids = list(PurchaseOrder.objects.filter(source_type='SAMPLE').values_list(
            'sample_procurement_request__material_request__sample_request_id', flat=True))
        AuditLog.objects.create(id=event_id, object_type='MATERIAL_FLOW_RESET', object_id=event_id,
            actor_name_snapshot=operator.strip(),
            action='RESET_COMPLETED', occurred_at=timezone.now(),
            before_data={'manifest_sha256': approved_sha256, 'version': VERSION, 'authorization':authorization},
            after_data={'database': identity, 'deleted_counts': {apps.get_model(l)._meta.db_table: manifest['tables'][apps.get_model(l)._meta.db_table]['count'] for l in DELETE_LABELS},
                        'updated_rows':len(manifest['updates']), 'protected_tables_verified':len(manifest['protected_tables']),
                        'physical_files':'PRESERVED', 'sample_ids':[str(value) for value in sample_ids]})
        validate_reset_authorization(identity,approved_sha256,operator,authorization)
        return {'ok': True, 'manifest_sha256': approved_sha256, 'audit_id': str(event_id),
                'operator':operator.strip(),
                'before':manifest['tables'], 'after_before_audit':after,
                'protected_tables_verified':len(manifest['protected_tables'])}
