from django.urls import reverse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response


@extend_schema(
    responses={
        200: inline_serializer(
            name="ApiV1RootResponse",
            fields={
                "data": serializers.DictField(),
            },
        )
    }
)
@api_view(["GET"])
def api_v1_root(request):
    return Response(
        {
            "data": {
                "name": "haiqu ERP CRM API",
                "version": "1.0",
                "authenticated": True,
                "links": {
                    "auth_me": request.build_absolute_uri(reverse("auth-me")),
                    "customers": request.build_absolute_uri(reverse("customer-list")),
                    "communications": request.build_absolute_uri(reverse("communication-list")),
                    "tasks": request.build_absolute_uri(reverse("task-list")),
                    "inquiries": request.build_absolute_uri(reverse("inquiry-list")),
                    "quotations": request.build_absolute_uri(reverse("quotation-list")),
                    "sample_requests": request.build_absolute_uri(reverse("sample-request-list")),
                    "approvals": request.build_absolute_uri(reverse("approval-list")),
                    "sla_trackings": request.build_absolute_uri(reverse("sla-tracking-list")),
                    "customer_transfer_requests": request.build_absolute_uri(reverse("customer-transfer-request-list")),
                    "customer_duplicate_cases": request.build_absolute_uri(reverse("customer-duplicate-case-list")),
                    "saved_views": request.build_absolute_uri(reverse("saved-view-list")),
                    "audit_logs": request.build_absolute_uri(reverse("audit-log-list")),
                    "search": request.build_absolute_uri(reverse("global-search")),
                    "dashboard_me": request.build_absolute_uri(reverse("dashboard-me")),
                    "dashboard_manager": request.build_absolute_uri(reverse("dashboard-manager")),
                    "schema": request.build_absolute_uri(reverse("api-schema")),
                },
            }
        }
    )
