from rest_framework.exceptions import APIException, ValidationError


class ReceiptValidationError(ValidationError):
    def __init__(self, code, detail, *, meta=None):
        self.api_error_code = code
        self.error_meta = meta
        super().__init__(detail)


class ReceiptInputError(APIException):
    """穿过DRF嵌套字段校验，最外层再转为保留字段信息的业务校验异常。"""
    status_code = 400

    def __init__(self, code, detail, *, meta=None):
        self.api_error_code = code
        self.error_meta = meta
        super().__init__(detail)


class ReceiptFileError(APIException):
    def __init__(self, code, detail, *, status=409, meta=None):
        self.api_error_code = code
        self.status_code = status
        self.error_meta = meta
        super().__init__(detail)
