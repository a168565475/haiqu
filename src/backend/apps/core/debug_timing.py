import re
from time import perf_counter

from django.conf import settings
from django.db import connection


class ProductionReadTimingMiddleware:
    """仅在开发环境向超级管理员返回业务读取诊断，不记录 SQL 或业务内容。"""

    paths = {
        "/api/v1/reference-data/tube-shapes/",
        "/api/v1/reference-data/tube-product-names/",
        "/api/v1/reference-data/tube-materials/",
        "/api/v1/reference-data/tube-diameters/",
        "/api/v1/reference-data/tube-thicknesses/",
        "/api/v1/reference-data/tube-coating-colors/",
        "/api/v1/unified-outsourcing-orders/",
        "/api/v1/sample-inventory/summary/",
        "/api/v1/access/employees/",
        "/api/v1/access/roles/",
        "/api/v1/access/departments/",
        "/api/v1/access/sales-teams/",
        "/api/v1/access/catalog/",
        "/api/v1/access/catalog/scope-options/",
        "/api/v1/production-tasks/",
        "/api/v1/production-tasks/options/",
        "/api/v1/production-tasks/stats/",
        "/api/v1/boms/",
        "/api/v1/boms/options/",
        "/api/v1/boms/stats/",
        "/api/v1/purchase-orders/",
        "/api/v1/purchase-orders/options/",
        "/api/v1/purchase-orders/filter-options/",
        "/api/v1/purchase-orders/stats/",
        "/api/v1/material-inventory/procurement-inbound-orders/",
        "/api/v1/material-inventory/options/",
        "/api/v1/material-inventory/eligible-purchase-orders/",
        "/api/v1/material-inventory/eligible-lines/",
        "/api/v1/purchase-returns/",
        "/api/v1/purchase-returns/stats/",
        "/api/v1/purchase-returns/filter-options/",
        "/api/v1/material-inventory/quality-batches/",
    }
    bom_detail_path = re.compile(r"/api/v1/boms/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/")
    purchase_detail_path = re.compile(r"/api/v1/purchase-orders/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/")
    return_detail_path = re.compile(r"/api/v1/purchase-returns/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/")
    quality_detail_path = re.compile(r"/api/v1/material-inventory/quality-batches/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.DEBUG or request.method != "GET" or not (
            request.path in self.paths or self.bom_detail_path.fullmatch(request.path)
            or self.purchase_detail_path.fullmatch(request.path)
            or self.return_detail_path.fullmatch(request.path)
            or self.quality_detail_path.fullmatch(request.path)
        ):
            return self.get_response(request)
        sql_seconds = 0.0
        sql_count = 0

        def measure_sql(execute, sql, params, many, context):
            nonlocal sql_seconds, sql_count
            start = perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                sql_seconds += perf_counter() - start
                sql_count += 1

        start = perf_counter()
        with connection.execute_wrapper(measure_sql):
            response = self.get_response(request)
        total_ms = (perf_counter() - start) * 1000
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser:
            timing = f'app;dur={total_ms:.2f}, db;dur={sql_seconds * 1000:.2f}, queries;desc="{sql_count}"'
            existing = response.get("Server-Timing")
            response["Server-Timing"] = f"{existing}, {timing}" if existing else timing
        return response
