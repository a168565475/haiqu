"""保留已删除待入库请求的终态，避免响应丢失后的重试重新建单。"""
from apps.audit.models import AuditLog
from apps.core.api.exceptions import Conflict


class ReceiptRequestDeleted(Conflict):
    api_error_code = 'RECEIPT_REQUEST_DELETED'


def require_receipt_request_not_deleted(*, object_type, request_id):
    # 调用者必须先持有请求锁并查过存活原单，再检查同事务保存的删除审计。
    if AuditLog.objects.filter(object_type=object_type, action='DELETED',
            before_data__submission_request_id=str(request_id)).exists():
        raise ReceiptRequestDeleted('本次待入库记录已删除，不能重复提交；如需重新入库，请重新填写。')
