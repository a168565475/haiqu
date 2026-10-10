import uuid

from django.contrib.auth import logout as django_logout

from .auth import can_access_erp


class RequestIdMiddleware:
    header_name = "HTTP_X_REQUEST_ID"
    response_header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = self._request_id(request.META.get(self.header_name))
        response = self.get_response(request)
        response[self.response_header_name] = request.request_id
        return response

    @staticmethod
    def _request_id(value):
        if value:
            try:
                return str(uuid.UUID(value))
            except (TypeError, ValueError, AttributeError):
                pass
        return str(uuid.uuid4())


class ErpSessionAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not can_access_erp(request.user):
            django_logout(request)
        return self.get_response(request)
