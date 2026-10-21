from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from . import message_selectors as selectors, message_services as services
from .message_serializers import (
    MessageAttemptListSerializer, MessageAttemptQuerySerializer, MessageAttemptResponseSerializer,
    MessageTemplateResponseSerializer, MessageTemplateWriteSerializer, MessageTestSerializer,
)
from .views import IF_MATCH, ManagementView, WeComUnavailable, paginated_response


@method_decorator(never_cache, name="dispatch")
class MessageManagementView(ManagementView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not selectors.schema_is_ready():
            raise WeComUnavailable()


def template_response(template):
    return Response(MessageTemplateResponseSerializer({"data": selectors.template_payload(template)}).data,
                    headers={"ETag": selectors.template_etag(template)})


class MessageTemplateView(MessageManagementView):
    @extend_schema(responses=MessageTemplateResponseSerializer)
    def get(self, request):
        return template_response(selectors.get_template())

    @extend_schema(request=MessageTemplateWriteSerializer, responses=MessageTemplateResponseSerializer, parameters=[IF_MATCH])
    def patch(self, request):
        serializer = MessageTemplateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return template_response(services.update_template(request, serializer.validated_data))


class MessageTestView(MessageManagementView):
    @extend_schema(request=MessageTestSerializer, responses=MessageAttemptResponseSerializer, parameters=[IF_MATCH])
    @sensitive_variables()
    def post(self, request):
        serializer = MessageTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = services.send_test_message(request, serializer.validated_data)
        return Response(MessageAttemptResponseSerializer({"data": selectors.attempt_payload(attempt)}).data)


class MessageAttemptsView(MessageManagementView):
    @extend_schema(parameters=[MessageAttemptQuerySerializer], responses=MessageAttemptListSerializer)
    def get(self, request):
        query = MessageAttemptQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return paginated_response(selectors.attempts_queryset(query.validated_data.get("idempotency_key")),
                                  query.validated_data, selectors.attempt_payload, MessageAttemptListSerializer)
