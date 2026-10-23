from rest_framework.exceptions import PermissionDenied


FINANCE_RECEIPT_FOLDER = "finance/receipt_uploads/"


def require_non_finance_receipt_file(business_file):
    """财务水单只允许受控收款绑定；不随销售权限开关或管理员身份放宽。"""
    if business_file is not None and business_file.storage_key.startswith(FINANCE_RECEIPT_FOLDER):
        raise PermissionDenied("财务水单不能复用到其他业务，请在对应业务重新上传文件。")
