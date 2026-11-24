"""合成业务资料、真实隔离数据库/API 的后台页面检查，不代表正式业务验收。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.boms.models import BomLine
from apps.boms.services import confirm_bom_product
from apps.boms.tests import test_bom_api as bom_api_fixture
from apps.inventory.models import InternalSemiFinishedReceipt, PublicStockMovement
from apps.inventory.tests.test_internal_receipt_sewing import SewingFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.material_issues.scopes import PLAN_WORKSHOP_NAMES
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.procurement.tracking_models import PurchaseTrackingPolicy
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_tasks.models import ProductionTaskProduct
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_config.tests.factories import production_employee


@skipUnless(os.environ.get('BOM_PARTS_BROWSER_QA') == '20261113', '仅显式启动本任务隔离页面检查')
@override_settings(ALLOWED_HOSTS=['*'],
    CSRF_TRUSTED_ORIGINS=['http://127.0.0.1:18514', 'http://127.0.0.1:18515'],
    DEV_AUTO_LOGIN_ENABLED=False, MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True,
    SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class PartFlowBrowserTests(D1Fixture, LiveServerTestCase):
    host = '0.0.0.0'
    port = 18513
    client_class = APIClient

    def setUp(self):
        self.assertEqual(connection.settings_dict['NAME'], 'test_bom_parts_20261113_a1d32c')
        # 同轮 TransactionTestCase flush 后迁移种子不自动重建，仅补本夹具依赖。
        PurchaseTrackingPolicy.objects.get_or_create(key='default')
        super().setUp()

    def ordinary_role(self, code, permissions, *, user=None, employee=None):
        password = secrets.token_urlsafe(24)
        user = user or get_user_model().objects.create_user(username=f'parts-browser-{code}')
        employee = employee or Employee.objects.create(user=user, employee_code=f'PARTS-QA-{code}', display_name=f'隔离{code}岗位')
        user.is_superuser = False
        user.is_staff = False
        user.set_password(password)
        user.save(update_fields=['password', 'is_superuser', 'is_staff'])
        role = RoleProfile.objects.create(role_code=f'PARTS_QA_{code}', display_name=f'隔离{code}岗位',
            auth_group=Group.objects.create(name=f'parts-browser-{code}'))
        for name in permissions:
            app, codename = name.split('.')
            permission = Permission.objects.get(content_type__app_label=app, codename=codename)
            role.auth_group.permissions.add(permission)
            RoleActionGrant.objects.create(role=role, permission=permission, scope='MODULE')
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        return {'username': user.username, 'password': password}

    def prepare_editor_bom(self):
        # 桌面编辑独立建单；不把 D1 报工夹具中的历史来源字段复制进当前编辑接口。
        source = self.product_line
        product_line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=self.task.products.order_by('-line_number').first().line_number + 1,
            product=source.product, product_category=source.product_category,
            product_number_snapshot=source.product_number_snapshot, product_code_snapshot=source.product_code_snapshot,
            item_number_snapshot=source.item_number_snapshot, product_name_snapshot=source.product_name_snapshot,
            specification_snapshot=source.specification_snapshot, material_snapshot=source.material_snapshot,
            product_color=source.product_color, color_card_snapshot=source.color_card_snapshot,
            color_name_snapshot=source.color_name_snapshot, color_code_snapshot=source.color_code_snapshot,
            quantity=source.quantity, unit=source.unit, currency=source.currency,
            unit_price=source.unit_price, total_amount=source.total_amount, exchange_rate=source.exchange_rate)
        created = self.client.post('/api/v1/boms/', {'production_task_product_id': str(product_line.pk),
            'creation_method': 'BLANK'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        bom_id = created.data['data']['id']
        current = self.client.post(f'/api/v1/boms/{bom_id}/confirm-product/', {
            'product_id': str(source.product_id), 'product_color_id': str(source.product_color_id),
            'color_code': source.color_code_snapshot}, format='json', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(current.status_code, 200, current.data)
        source_key = str(uuid4())
        sections = bom_api_fixture.BomApiTests.fixed_sections([
            {'title': '面料类', 'section_type': 'FABRIC', 'lines': [{
                'client_key': source_key, 'part_name': '面布', 'unit_consumption': '1',
                'source_inventory_material_id': str(self.fabric_material.pk),
                'fabric_color_name': self.fabric_material.color_snapshot}]},
            {'title': '裁剪明细', 'section_type': 'FABRIC', 'lines': []},
        ])
        section_ids = {section['title']: section['id'] for section in current.data['data']['sections']}
        for section in sections:
            if section['title'] in section_ids:
                section['id'] = section_ids[section['title']]
        body = {'sections': sections}
        preview = self.client.post(f'/api/v1/boms/{bom_id}/material-save-preview/',
            body, format='json', HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data['data']['confirmation_token'], '规范夹具应复用已有原料')
        saved = self.client.patch(f'/api/v1/boms/{bom_id}/', body, format='json', HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        current = self.client.get(f'/api/v1/boms/{bom_id}/')
        self.assertEqual(current.status_code, 200, current.data)
        persisted_sections = current.data['data']['sections']
        lines = [line for section in persisted_sections for line in section['lines']]
        self.assertEqual(len(lines), 1)
        self.assertTrue(all(not line['source_raw_material_id'] for line in lines))
        self.assertFalse(next(section for section in persisted_sections if section['title'] == '管材类')['lines'])
        # 再次使用持久化详情预检，覆盖页面读取后原样提交的全部来源字段。
        preview = self.client.post(f'/api/v1/boms/{bom_id}/material-save-preview/',
            {'sections': persisted_sections}, format='json', HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data['data']['confirmation_token'])
        return bom_id

    def prepare_component_catalogs(self):
        # 仅在独占测试库用真实建档 API 准备候选，BOM 岗位不借用维护写权限。
        auth = self.ordinary_role('CATALOG', [
            'material_catalog.view_materialcatalog', 'material_catalog.add_materialcatalog'])
        self.client.force_authenticate(get_user_model().objects.get(username=auth['username']))
        catalogs = {}
        for key, name, unit in [('part', '隔离椅面', '个'), ('piece', '隔离布片', '片'), ('cotton', '隔离棉片', '片')]:
            result = self.client.post('/api/v1/material-catalog/', {
                'name': name, 'category_key': 'FABRIC_SEMI', 'template_key': 'FABRIC_SEMI',
                'values': [],  # 只建品名，不触发旧调用默认“无颜色”的公共配置补录。
                'units': [{'id': str(uuid4()), 'scope': 'BASE', 'unit_name': unit}],
            }, format='json')
            self.assertEqual(result.status_code, 201, result.data)
            catalog = result.data['data']
            catalogs[key] = {'id': catalog['id'], 'name': catalog['name'], 'unit': unit,
                'version': catalog['updated_at']}
        return catalogs

    def test_parts_mobile_receipts_and_bom_editor(self):
        self.assertEqual(connection.settings_dict['NAME'], 'test_bom_parts_20261113_a1d32c')
        control = Path('/qa/browser-control')
        control.mkdir(parents=True, exist_ok=True)
        self.assertFalse(any(control.iterdir()), '控制目录存在文件，拒绝覆盖未知凭据或结果')
        ready, done = control / 'ready.json', control / 'done.json'
        try:
            ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
            SewingFixture.prepare_sewing(self)
            ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code': 'BOM_CUT_PIECE'})
            ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'PARTS_QA_EACH'})
            catalogs = self.prepare_component_catalogs()
            self.part = BomLine.objects.create(section=self.parts[0].section, line_number=3,
                component_kind='SEWN_PART', part_name='床面', unit='个', parts_per_product=1)
            for line in self.parts:
                line.component_kind, line.parent_part, line.pieces_per_part, line.unit = 'CUT_PIECE', self.part, 2, '片'
                line.cutting_pieces_per_set = line.cutting_sets_per_product = None
                line.fabric_meters_per_piece = line.fabric_meters_per_set = None
                line.save()
            # 本测试只创建运行所需的真实资料，不伪造库存或页面响应。
            self.fabric.raw_values['source_inventory_material_id'] = str(self.fabric_material.pk)
            self.fabric.save(update_fields=['raw_values'])
            self.bom = confirm_bom_product(bom=self.bom, product=self.product_line.product,
                product_color=self.product_line.product_color, color_code=self.product_line.color_code_snapshot,
                actor_employee=self.employee)
            workshops = {}
            for category in ('CUTTING', 'SEWING'):
                workshop, _ = Workshop.objects.get_or_create(name=PLAN_WORKSHOP_NAMES[category])
                craft, _ = Craft.objects.get_or_create(plan_category=category, defaults={
                    'name': f'隔离部位流程{category}', 'craft_type': 'INTERNAL', 'workshop': workshop, 'status': 'ACTIVE'})
                self.assertEqual((craft.craft_type, craft.workshop_id, craft.status), ('INTERNAL', workshop.pk, 'ACTIVE'))
                ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
                    craft=craft, craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name, plan_category=category)
                workshops[category] = workshop
            recipient = production_employee(workshop=workshops['SEWING'], position='领料员', name='隔离车缝领料员')
            read_task = ['production_tasks.view_productiontask', 'production_tasks.view_all_productiontask',
                'production_scheduling.view_productionschedule']
            workshop_auth = self.ordinary_role('WORKSHOP', read_task + [
                'inventory.view_internalsemifinishedreceipt', 'inventory.add_internalsemifinishedreceipt',
                'material_issues.view_materialissue', 'material_issues.add_materialissue',
                'material_issues.change_materialissue', 'material_issues.submit_materialissue'],
                user=self.user, employee=self.employee)
            warehouse_auth = self.ordinary_role('WAREHOUSE', read_task + [
                'inventory.view_internalsemifinishedreceipt', 'inventory.confirm_internalsemifinishedreceipt'])
            bom_auth = self.ordinary_role('BOM', read_task + ['boms.view_bom', 'boms.change_bom', 'boms.add_bom',
                'material_catalog.view_materialcatalog'])
            denied_auth = self.ordinary_role('DENIED', [])
            # 在发出 ready 前核对角色及计划边界；浏览器仍独立走真实登录与 HTTP。
            self.client.force_authenticate(self.user)
            for category in ('CUTTING', 'SEWING'):
                query = {'plan_category': category, 'workshop_id': str(workshops[category].pk)}
                result = self.client.get(f'/api/v1/workshop-mobile/plans/{self.schedule_product.pk}/', query)
                self.assertEqual(result.status_code, 200, result.data)
                self.assertTrue(result.data['data']['can_receive_semi'], result.data)
                result = self.client.get('/api/v1/semi-finished-receipts/preview/',
                    {'schedule_product_id': str(self.schedule_product.pk), 'plan_category': category})
                self.assertEqual(result.status_code, 200, result.data)
            self.client.force_authenticate(get_user_model().objects.get(username=bom_auth['username']))
            result = self.client.get('/api/v1/boms/editor-reference-options/')
            self.assertEqual(result.status_code, 200, result.data)
            result = self.client.get('/api/v1/material-catalog/', {'category': 'FABRIC_SEMI', 'page_size': 100})
            self.assertEqual(result.status_code, 200, result.data)
            self.assertTrue({item['id'] for item in catalogs.values()}.issubset(
                {item['id'] for item in result.data['data']}))
            editor_bom_id = self.prepare_editor_bom()
            initial_movements = PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').count()
            payload = {'database': connection.settings_dict['NAME'], 'bomId': str(editor_bom_id),
                'scheduleProductId': str(self.schedule_product.pk), 'taskId': str(self.task.pk),
                'productLineId': str(self.product_line.pk), 'partName': self.part.part_name,
                'pieceName': self.parts[0].part_name, 'pieceId': str(self.parts[0].pk), 'partId': str(self.part.pk),
                'zoneName': self.semi_zone.zone_name, 'zoneId': str(self.semi_zone.pk),
                'workshops': {key: str(value.pk) for key, value in workshops.items()},
                'recipientId': str(recipient.pk), 'sourceLabel': '面布 · 150cm', 'catalogs': catalogs,
                'users': {'bom': bom_auth, 'workshop': workshop_auth, 'warehouse': warehouse_auth, 'denied': denied_auth}}
            temporary = control / 'ready.tmp'
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            temporary.replace(ready)
            print('部位流程隔离页面资料已就绪，凭据不输出。', flush=True)
            deadline = time.monotonic() + 600
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), '等待后台页面检查超时')
            self.assertTrue(json.loads(done.read_text(encoding='utf-8')).get('passed'), '后台页面检查失败，见脱敏报告')
            receipts = InternalSemiFinishedReceipt.objects.filter(plan_category__in=['CUTTING', 'SEWING'])
            self.assertEqual(receipts.count(), 2)
            self.assertTrue(all(receipt.status == 'CONFIRMED' for receipt in receipts))
            self.assertEqual(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').count(), initial_movements + 2)
            created = BomLine.objects.get(section__bom_id=editor_bom_id, component_kind='SEWN_PART',
                material_catalog_id=catalogs['part']['id'])
            child = created.cut_pieces.get()
            self.assertEqual((created.part_name, created.parts_per_product, created.unit), ('隔离椅面', 1, '个'))
            self.assertEqual((child.part_name, child.unit, child.pieces_per_part), ('隔离布片', '片', 2))
            self.assertEqual(child.specification, '30*40cm')
            self.assertEqual(str(child.material_catalog_id), catalogs['piece']['id'])
            self.assertEqual(child.fabric_source_line.section.bom_id, created.section.bom_id)
            self.assertEqual(child.fabric_source_line.part_name, '面布')
            for line, key in [(created, 'part'), (child, 'piece')]:
                snapshot = line.material_selection_snapshot
                self.assertEqual((snapshot['catalog_id'], snapshot['name'], snapshot['unit_name']),
                    (catalogs[key]['id'], catalogs[key]['name'], catalogs[key]['unit']))
        finally:
            for path in (ready, done, control / 'ready.tmp', control / 'done.tmp'):
                path.unlink(missing_ok=True)
