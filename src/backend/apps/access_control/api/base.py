from drf_spectacular.utils import OpenApiParameter
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.api.permissions import HasActiveEmployee
from ..permissions import CanManageAccess

IF_MATCH = OpenApiParameter("If-Match", str, location=OpenApiParameter.HEADER, required=True)


class AccessViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageAccess]
    filter_backends = []
