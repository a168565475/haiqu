"""切换期间允许查询；相关业务写请求与停写操作共用事务锁。"""

from django.db import transaction
from django.http import JsonResponse
from django.urls import Resolver404, resolve

from .public_stock_cutover import cache_request_control, lock_stock_writes, require_business_stock_write
from .stock_services import InventoryStockValidationError


PROTECTED_APPS = {"inventory", "material_issues", "outsourcing", "procurement", "boms",
                  "production_tasks", "production_scheduling", "products", "sales_orders",
                  "reference_data", "workshop_config", "organizations", "imports", "workshop_reporting"}


class PublicStockCutoverMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)
        view = getattr(match.func, "view_class", getattr(match.func, "cls", match.func))
        module = getattr(view, "__module__", "").split(".")
        protected = len(module) > 1 and module[0] == "apps" and module[1] in PROTECTED_APPS
        if not protected:
            return self.get_response(request)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            with cache_request_control():
                return self.get_response(request)
        with transaction.atomic():
            lock_stock_writes()
            with cache_request_control():
                try:
                    require_business_stock_write()
                except InventoryStockValidationError as exc:
                    return JsonResponse({"code": exc.api_error_code, "detail": str(exc.detail["detail"])}, status=503)
                return self.get_response(request)
