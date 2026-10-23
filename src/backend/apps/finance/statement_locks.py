from django.db import connection
from rest_framework.generics import get_object_or_404

from .statement_models import ReceivableStatement


def lock_statement(statement_id):
    """U03/U04/U05共用账单锁；涉及来源时调用方必须先按UUID锁旧/新任务。"""
    if not connection.in_atomic_block:
        raise RuntimeError("账单锁必须在业务事务内使用。")
    return get_object_or_404(ReceivableStatement.objects.select_for_update(), pk=statement_id)
