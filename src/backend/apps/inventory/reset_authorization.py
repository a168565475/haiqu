"""S9 仅为已批准的本地业务库开放一次明确的维护窗口。"""
import re
from datetime import datetime
from django.core.management.base import CommandError
from django.utils import timezone


def validate_reset_authorization(identity, manifest_sha256, operator, authorization=None):
    isolated = identity['host']=='haiqu-material-flow-s3-pg' and identity['name'].startswith(('material_flow_s8_','test_s8_'))
    if isolated and authorization is None:
        return
    if (identity['host'],identity['port'],identity['name']) != ('postgres','5432','haiqu_erp'):
        raise CommandError('目标不是已批准的本地业务库或独立恢复库。')
    if not isinstance(authorization,dict):
        raise CommandError('正式清理必须提供已批准的 S9 执行记录。')
    if (authorization.get('scope')!='S9_BUSINESS_RESET' or authorization.get('user_approval')!='B->A'
            or authorization.get('database')!=identity or authorization.get('manifest_sha256')!=manifest_sha256
            or authorization.get('operator')!=operator.strip() or authorization.get('restore_verified') is not True):
        raise CommandError('S9 审核记录与当前数据库、清单、操作者或恢复证明不一致。')
    if not re.fullmatch(r'[0-9a-f]{64}',str(authorization.get('backup_sha256',''))):
        raise CommandError('缺少有效备份摘要。')
    try:
        start=datetime.fromisoformat(authorization['maintenance_started_at'])
        end=datetime.fromisoformat(authorization['maintenance_expires_at'])
    except (KeyError,ValueError,TypeError) as error:
        raise CommandError('维护窗口时间无效。') from error
    if timezone.is_naive(start) or timezone.is_naive(end) or not start<=timezone.now()<end:
        raise CommandError('不在已登记维护窗口内，禁止执行。')
    if (end-start).total_seconds()>7200:
        raise CommandError('单次维护授权最多两小时，请重新核对执行条件。')
