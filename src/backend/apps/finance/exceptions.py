from rest_framework.exceptions import APIException


class FinanceConflict(APIException):
    status_code = 409

    def __init__(self, code, message, *, meta=None):
        self.api_error_code = code
        self.error_meta = meta
        super().__init__(message)


class OriginalResultDeleted(FinanceConflict):
    status_code = 410

    def __init__(self, resource_id):
        super().__init__("ORIGINAL_RESULT_DELETED", "原创建结果已删除，不能通过重试重新创建。",
                         meta={"resource_id": str(resource_id), "deleted": True})
