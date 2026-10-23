import hashlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.http import Http404
from openpyxl import Workbook
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.finance.models import AccountingSubject, FinanceMutationKey
from apps.finance.subject_importing import read_subject_workbook, apply_subject_import, subject_import_plan
from apps.finance.subject_services import create_subject, update_subject, delete_subject

ROOT = '/api/v1/finance/subjects/'
TREE = '/api/v1/finance/subject-tree/'


def grant_subjects(employee, code):
    role = RoleProfile.objects.create(role_code=code, display_name=code, auth_group=Group.objects.create(name=code))
    permissions = Permission.objects.filter(content_type__app_label='finance', content_type__model='accountingsubject')
    for permission in permissions:
        RoleActionGrant.objects.create(role=role, permission=permission, scope='MODULE')
    role.auth_group.permissions.add(*permissions)
    EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
    return role


def body(name='管理费用', parent=None, level=1, **changes):
    return {'name': name, 'parent_id': str(parent) if parent else None, 'level': level, 'status': 'ACTIVE', **changes}


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
class SubjectTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('subject_test', password='isolated-only')
        self.actor = Employee.objects.create(user=self.user, employee_code='U02_TEST', display_name='隔离测试')
        self.role = grant_subjects(self.actor, 'FINANCE')
        self.client = APIClient()
        self.client.force_login(self.user)

    def create(self, data=None, key=None):
        return self.client.post(ROOT, data or body(), format='json', HTTP_IDEMPOTENCY_KEY=str(key or uuid4()))

    def node(self, data=None):
        response = self.create(data)
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['data']

    def current(self, node):
        return self.client.get(ROOT + node['id'] + '/').data['data']

    def change(self, node, **data):
        return self.client.patch(ROOT + node['id'] + '/', data, format='json', HTTP_IF_MATCH=node['etag'])

    def chain(self):
        root = self.node()
        parent = self.node(body('办公费', root['id'], 2))
        leaf = self.node(body('应付账款', parent['id'], 3))
        return self.current(root), self.current(parent), leaf

    def test_paths_duplicates_filters_pagination_tree(self):
        root, parent, leaf = self.chain()
        other = self.node(body('销售费用'))
        other_parent = self.node(body('办公费', other['id'], 2))
        self.node(body('应付账款', other_parent['id'], 3))
        self.assertEqual(leaf['full_path'], '管理费用 / 办公费 / 应付账款')
        self.assertEqual(self.create(body()).status_code, 409)
        self.assertEqual(self.create(body('应付账款', parent['id'], 3)).status_code, 409)
        listed = self.client.get(ROOT, {'q':'应付账款','level':3,'page_size':1})
        self.assertEqual(listed.data['meta']['total'], 2)
        self.assertEqual(len(listed.data['data']), 1)
        self.assertEqual(self.client.get(ROOT, {'q':'管理费用','level':3}).data['meta']['total'], 1)
        self.assertEqual(self.client.get(TREE).data['meta']['total'], 2)
        self.assertEqual(self.client.get(TREE, {'parent_id':root['id']}).data['data'][0]['id'], parent['id'])
        self.assertEqual(root['affected_path_count'], 1)

    def test_parent_disable_restore_retains_child_status_and_invalidates_etags(self):
        root, parent, leaf = self.chain()
        self.assertEqual(self.change(leaf, status='INACTIVE').status_code, 200)
        root = self.current(root)
        self.assertEqual(self.change(root, status='INACTIVE').status_code, 200)
        self.assertEqual(self.current(parent)['status'], 'ACTIVE')
        self.assertEqual(self.current(parent)['effective_status'], 'INACTIVE')
        self.assertIn('管理费用', self.current(parent)['blocked_by_ancestor'])
        self.assertEqual(self.create(body('新科目', parent['id'], 3)).status_code, 409)
        self.assertEqual(self.change(parent, name='旧版本').status_code, 412)
        self.assertEqual(self.change(self.current(root), status='ACTIVE').status_code, 200)
        self.assertEqual(self.current(parent)['effective_status'], 'ACTIVE')
        self.assertEqual(self.current(leaf)['status'], 'INACTIVE')
        self.assertEqual(self.current(leaf)['effective_status'], 'INACTIVE')

    def test_rename_parent_changes_paths_only_and_stale_rejected(self):
        root, parent, leaf = self.chain()
        self.assertEqual(self.change(root, name='  新管理  费用  ').status_code, 200)
        current = self.current(leaf)
        self.assertEqual(current['full_path'], '新管理  费用 / 办公费 / 应付账款')
        self.assertNotEqual(current['etag'], leaf['etag'])
        self.assertEqual(current['name'], leaf['name'])
        self.assertEqual(self.change(leaf, name='过时输入').status_code, 412)

    def test_etag_delete_nonleaf_idempotent_deleted_and_failed_keys(self):
        key, data = uuid4(), body('独立节点')
        response = self.create(data, key); node = response.data['data']
        self.assertEqual(self.create(data, key).status_code, 200)
        self.assertEqual(self.create({**data,'name':'不同'}, key).status_code, 409)
        url = ROOT + node['id'] + '/'
        self.assertEqual(self.client.patch(url, {'name':'改名'}, format='json').status_code, 428)
        self.assertEqual(self.client.delete(url).status_code, 428)
        self.assertEqual(self.client.delete(url, HTTP_IF_MATCH=node['etag']).status_code, 204)
        self.assertEqual(self.create(data, key).status_code, 410)
        root, parent, leaf = self.chain()
        refused = self.client.delete(ROOT+parent['id']+'/', HTTP_IF_MATCH=parent['etag'])
        self.assertEqual(refused.data['error']['code'], 'SUBJECT_HAS_CHILDREN')
        self.assertEqual(AccountingSubject.objects.count(), 3)
        before = FinanceMutationKey.objects.count()
        self.assertEqual(self.create(body('错误',root['id'],3)).status_code, 400)
        self.assertEqual(FinanceMutationKey.objects.count(), before)

    def test_invalid_inputs_immutable_hierarchy_and_db_constraints(self):
        root, parent, leaf = self.chain()
        for data in (body('x', None, 2), body('x',leaf['id'],4), body(' '), body(123), body('x'*101), body(unknown='x')):
            self.assertEqual(self.create(data).status_code, 400)
        for changes in ({'parent_id':root['id']}, {'level':2}, {'id':str(uuid4())}):
            self.assertEqual(self.change(leaf, **changes).status_code, 400)
        for query in ({'level':4},{'parent_id':'bad'},{'status':'bad'},{'page_size':101},{'page':0}):
            self.assertEqual(self.client.get(ROOT,query).status_code, 400)
        values = {'created_by_employee':self.actor,'updated_by_employee':self.actor}
        for data in ({'name':'管理费用','level':1}, {'name':'越级','level':3,'parent_id':root['id']}, {'name':'无父','level':2}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                AccountingSubject.objects.create(**values,**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountingSubject.objects.filter(pk=root['id']).update(parent_id=leaf['id'],level=2)

    def test_audit_failure_rolls_back_and_action_separate(self):
        with patch('apps.finance.subject_services.write_audit_log',side_effect=RuntimeError('isolated')):
            with self.assertRaises(RuntimeError): self.create()
        self.assertFalse(AccountingSubject.objects.exists())
        self.assertFalse(FinanceMutationKey.objects.exists())
        self.node()
        self.assertEqual(FinanceMutationKey.objects.get().action,'CREATE_SUBJECT')

    def test_four_roles_and_csrf_denials(self):
        for code in ('CASHIER','FACTORY_MANAGER','GENERAL_MANAGER'):
            user=get_user_model().objects.create_user(code)
            actor=Employee.objects.create(user=user,employee_code=code,display_name=code)
            grant_subjects(actor,code); self.client.force_login(user)
            node=self.node(body(code))
            self.assertEqual(self.client.get(ROOT).status_code,200)
            self.assertEqual(self.client.get(TREE).status_code,200)
            changed=self.change(node,status='INACTIVE')
            self.assertEqual(changed.status_code,200)
            self.assertEqual(self.client.delete(ROOT+node['id']+'/',HTTP_IF_MATCH=changed['ETag']).status_code,204)
        self.client.force_login(self.user)
        csrf=APIClient(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.post(ROOT,body(),format='json',HTTP_IDEMPOTENCY_KEY=str(uuid4())).status_code,403)
        RoleActionGrant.objects.filter(role=self.role).delete(); self.role.auth_group.permissions.clear()
        self.assertEqual(self.client.get(ROOT).status_code,403)
        self.assertEqual(self.client.get(TREE).status_code,403)
        self.assertEqual(self.create().status_code,403)
        self.actor.status='INACTIVE'; self.actor.save()
        self.assertIn(self.client.get(ROOT).status_code,(401,403))
        self.client.logout(); self.assertIn(self.client.get(ROOT).status_code,(401,403))

    def workbook(self, rows=None):
        book=Workbook(); sheet=book.active; sheet.title='会计科目'
        sheet.append(['费用类型','一级科目','二级科目'])
        for row in rows or [('类型A','一级A','应付账款'),('类型B','一级B','应付账款')]: sheet.append(row)
        stream=BytesIO(); book.save(stream); book.close(); return stream.getvalue()

    def test_import_all_paths_idempotency_conflict_atomic_and_invalid_files(self):
        content=self.workbook(); paths=read_subject_workbook(content,hashlib.sha256(content).hexdigest())
        self.assertEqual(subject_import_plan(paths)['node_count'],6)
        apply_subject_import(paths,self.actor); apply_subject_import(paths,self.actor)
        self.assertEqual(AccountingSubject.objects.count(),6)
        AccountingSubject.objects.filter(name='类型B').update(status='INACTIVE')
        with self.assertRaises(APIException): apply_subject_import([('类型新','新','新'),*paths],self.actor)
        self.assertFalse(AccountingSubject.objects.filter(name='类型新').exists())
        for rows in ([('A','B','=1+2')],[('A','B',1)],[('A','B','C'),('A','B','C')],[('A',None,'C')]):
            content=self.workbook(rows)
            with self.assertRaises(ValidationError): read_subject_workbook(content,hashlib.sha256(content).hexdigest())
        with self.assertRaises(ValidationError): read_subject_workbook(b'bad',hashlib.sha256(b'bad').hexdigest())
        with self.assertRaises(ValidationError): read_subject_workbook(self.workbook(),'0'*64)

    def test_grants_preserve_accounts_and_other_roles(self):
        account_perm=Permission.objects.get(content_type__app_label='finance',codename='view_financeaccount')
        RoleActionGrant.objects.create(role=self.role,permission=account_perm,scope='MODULE')
        self.role.auth_group.permissions.add(account_perm)
        for code in ('CASHIER','FACTORY_MANAGER','GENERAL_MANAGER'):
            RoleProfile.objects.create(role_code=code,display_name=code,auth_group=Group.objects.create(name=code))
        admin=get_user_model().objects.create_superuser('admin',email='')
        actor=Employee.objects.create(user=admin,employee_code='U02_ADMIN',display_name='隔离管理员')
        assignments=list(EmployeeRoleAssignment.objects.values())
        params={'database_name':connection.settings_dict['NAME'],'actor_employee_id':str(actor.pk),'stdout':StringIO()}
        call_command('grant_finance_subject_roles',**params)
        self.assertEqual(RoleActionGrant.objects.count(),5)
        call_command('grant_finance_subject_roles',apply=True,**params)
        call_command('grant_finance_subject_roles',apply=True,**params)
        self.assertEqual(RoleActionGrant.objects.filter(permission__content_type__model='accountingsubject').count(),16)
        self.assertEqual(RoleActionGrant.objects.filter(permission=account_perm).count(),1)
        self.assertEqual(list(EmployeeRoleAssignment.objects.values()),assignments)


class SubjectConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor=Employee.objects.create(employee_code='U02_LOCK',display_name='隔离并发')

    def concurrent(self, functions):
        barrier=Barrier(2)
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    with connection.cursor() as cursor: cursor.execute("SET LOCAL lock_timeout='10s'")
                    try: return function()
                    except APIException as exc: return exc.api_error_code if hasattr(exc,'api_error_code') else str(exc.status_code)
                    except Http404: return '404'
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool: return list(pool.map(run,functions))

    def request(self,data=None,key=None,etag=None):
        return SimpleNamespace(employee=self.actor,data=data,headers={'Idempotency-Key':str(key or uuid4()),'If-Match':etag},META={})

    def test_same_key_and_root_unique_concurrency(self):
        key=uuid4()
        def same():
            obj,replayed=create_subject(self.request(body(),key)); return str(obj.pk),replayed
        results=self.concurrent([same,same])
        self.assertEqual(len({r[0] for r in results}),1)
        self.assertEqual(sorted(r[1] for r in results),[False,True])
        def duplicate(): create_subject(self.request(body('并发根'))); return 'CREATED'
        self.assertCountEqual(self.concurrent([duplicate,duplicate]),['CREATED','DUPLICATE_SUBJECT_PATH'])

    def test_parent_status_or_delete_vs_create_and_import(self):
        root,_=create_subject(self.request(body()))
        etag=etag_for_instance(root)
        def child(): create_subject(self.request(body('下级',root.pk,2))); return 'CREATED'
        def disable(): update_subject(self.request(etag=etag),root.pk,{'status':'INACTIVE'}); return 'DISABLED'
        result=self.concurrent([child,disable])
        self.assertIn(result, [['CREATED','412'],['SUBJECT_UNAVAILABLE','DISABLED']])
        root.refresh_from_db()
        if root.status=='INACTIVE': self.assertFalse(AccountingSubject.objects.filter(parent=root).exists())
        other,_=create_subject(self.request(body('待删除')))
        def remove(): delete_subject(self.request(etag=etag_for_instance(other)),other.pk); return 'DELETED'
        def insert(): create_subject(self.request(body('下级',other.pk,2))); return 'CREATED'
        result=self.concurrent([remove,insert])
        self.assertIn(result, [['DELETED','404'],['412','CREATED']])
        def imported(): apply_subject_import([('导入根','一级','末级')],self.actor); return 'IMPORTED'
        def created(): create_subject(self.request(body('导入根'))); return 'CREATED'
        results=self.concurrent([imported,created])
        self.assertIn(results,[['IMPORTED','CREATED'],['IMPORTED','DUPLICATE_SUBJECT_PATH']])
        self.assertEqual(AccountingSubject.objects.filter(name='导入根').count(),1)
