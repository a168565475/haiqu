"""U02仅隔离数据库/合成普通身份的真实Vue/HTTP检查，不替代主库员工验收。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import LiveServerTestCase, override_settings

from apps.organizations.models import Employee
from apps.finance.subject_services import insert_subject, lock_subjects
from .test_subjects import grant_subjects


@skipUnless(os.getenv('FINANCE_U02_BROWSER') == '1', '仅U02独占浏览器验证启用')
@override_settings(ALLOWED_HOSTS=['*'], CSRF_TRUSTED_ORIGINS=['http://127.0.0.1:18748'],
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    CACHES={key:{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'finance-u02-'+key} for key in ('default','configuration','wecom')})
class SubjectBrowserTests(LiveServerTestCase):
    host='0.0.0.0'
    port=18747

    def test_browser_session(self):
        self.assertEqual(connection.settings_dict['NAME'],'test_finance_u02_01a1681e')
        folder=Path('/app/_tmp/finance_u02_01a1681e'); folder.mkdir(parents=True,exist_ok=True)
        ready=folder/'browser-ready.json'; done=folder/'browser-done.json'
        identities=[]
        for code in ('FINANCE','CASHIER','FACTORY_MANAGER','GENERAL_MANAGER','NO_FINANCE'):
            password=secrets.token_urlsafe(24)
            user=get_user_model().objects.create_user('u02_'+code.lower(),password=password)
            employee=Employee.objects.create(user=user,employee_code='U02_'+code,display_name='隔离页面 '+code)
            if code!='NO_FINANCE': grant_subjects(employee,code)
            identities.append({'role':code,'username':user.username,'password':password})
        actor=Employee.objects.get(employee_code='U02_FINANCE')
        with transaction.atomic():
            lock_subjects()
            root=insert_subject({'parent_id':None,'level':1,'name':'隔离费用','status':'ACTIVE'},actor)
            parent=insert_subject({'parent_id':root.pk,'level':2,'name':'隔离办公','status':'ACTIVE'},actor)
            inactive=insert_subject({'parent_id':root.pk,'level':2,'name':'隔离停用分类','status':'INACTIVE'},actor)
            for index in range(23):
                insert_subject({'parent_id':parent.pk,'level':3,'name':f'隔离科目{index:03}','status':'INACTIVE' if index==2 else 'ACTIVE'},actor)
        try:
            ready.write_text(json.dumps({'isolated':True,'identities':identities,'root_id':str(root.pk),'parent_id':str(parent.pk),'inactive_id':str(inactive.pk)}),encoding='utf-8')
            deadline=time.monotonic()+1500
            while not done.exists() and time.monotonic()<deadline: time.sleep(1)
            self.assertTrue(done.exists(),'浏览器超时，测试库仍按测试结束销毁')
            self.assertTrue(json.loads(done.read_text(encoding='utf-8')).get('passed'),'页面检查失败，见U02_browser证据')
        finally:
            ready.unlink(missing_ok=True); done.unlink(missing_ok=True)
