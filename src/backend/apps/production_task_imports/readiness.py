from django.db.migrations.recorder import MigrationRecorder
from rest_framework.exceptions import APIException


class ImportSchemaUnavailable(APIException):
    status_code = 503
    default_detail = '生产任务导入模块尚未完成数据库迁移。'
    api_error_code = 'IMPORT_SCHEMA_UNAVAILABLE'


def require_schema():
    if not MigrationRecorder.Migration.objects.filter(app='production_task_imports', name='0001_initial').exists():
        raise ImportSchemaUnavailable()
