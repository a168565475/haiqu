from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import HasActiveEmployee
from apps.core.audit import write_audit_log
from apps.customers.api.views import CustomerApiViewSetBase

from ..models import EmailAccount, EmailAccountTestStatus
from ..services import email_account_snapshot, send_test_email
from .serializers import EmailAccountSerializer, EmailAccountTestSerializer, EmailAccountWriteSerializer


class OwnEmailAccountPermission(BasePermission):
    """用户确认的策略：所有有效员工都可维护其本人邮箱，服务端始终限定所属员工。"""

    message = "当前账号没有有效员工档案，无法维护邮件账户。"

    def has_permission(self, request, view):
        return getattr(request, "employee", None) is not None


class EmailAccountViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = EmailAccountSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, OwnEmailAccountPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def _employee(self):
        employee = self.actor_employee()
        if employee is None:
            raise PermissionDenied("邮件账户必须绑定到有效员工档案。")
        return employee

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EmailAccount.objects.none()
        return EmailAccount.objects.filter(employee=self._employee())

    def retrieve(self, request, *args, **kwargs):
        account = self.get_object()
        return self.response_with_etag({"data": EmailAccountSerializer(account).data}, account)

    def create(self, request, *args, **kwargs):
        serializer = EmailAccountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                account = serializer.save(employee=self._employee())
                write_audit_log(
                    object_type="EMAIL_ACCOUNT",
                    object_id=account.pk,
                    action="CREATED",
                    actor_employee=self._employee(),
                    after_data=email_account_snapshot(account),
                    request=request,
                )
        except IntegrityError as exc:
            raise Conflict("同一账户不能使用重复的邮件账户名称。") from exc
        return self.response_with_etag(
            {"data": EmailAccountSerializer(account).data},
            account,
            status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        account = self.get_object()
        require_matching_etag(request, account)
        if not request.data:
            raise ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        try:
            with transaction.atomic():
                locked = EmailAccount.objects.select_for_update().get(pk=account.pk, employee=self._employee())
                require_matching_etag(request, locked)
                before_data = email_account_snapshot(locked)
                serializer = EmailAccountWriteSerializer(locked, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                account = serializer.save()
                write_audit_log(
                    object_type="EMAIL_ACCOUNT",
                    object_id=account.pk,
                    action="UPDATED",
                    actor_employee=self._employee(),
                    before_data=before_data,
                    after_data=email_account_snapshot(account),
                    request=request,
                )
        except IntegrityError as exc:
            raise Conflict("同一账户不能使用重复的邮件账户名称。") from exc
        return self.response_with_etag({"data": EmailAccountSerializer(account).data}, account)

    def destroy(self, request, *args, **kwargs):
        account = self.get_object()
        require_matching_etag(request, account)
        with transaction.atomic():
            account = EmailAccount.objects.select_for_update().get(pk=account.pk, employee=self._employee())
            require_matching_etag(request, account)
            before_data = email_account_snapshot(account)
            account_id = account.pk
            account.delete()
            write_audit_log(
                object_type="EMAIL_ACCOUNT",
                object_id=account_id,
                action="DELETED",
                actor_employee=self._employee(),
                before_data=before_data,
                request=request,
            )
        return Response({"data": {"id": str(account_id), "deleted": True}}, status=status.HTTP_200_OK)

    @extend_schema(responses=EmailAccountSerializer)
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        account = self.get_object()
        require_matching_etag(request, account)
        with transaction.atomic():
            account = EmailAccount.objects.select_for_update().get(pk=account.pk, employee=self._employee())
            require_matching_etag(request, account)
            if not account.is_enabled:
                raise Conflict("停用的邮件账户不能设为默认。")
            EmailAccount.objects.filter(
                employee=account.employee,
                is_default=True,
            ).exclude(pk=account.pk).update(is_default=False, updated_at=timezone.now())
            before_data = email_account_snapshot(account)
            account.is_default = True
            account.save(update_fields=["is_default", "updated_at"])
            write_audit_log(
                object_type="EMAIL_ACCOUNT",
                object_id=account.pk,
                action="DEFAULT_SET",
                actor_employee=self._employee(),
                before_data=before_data,
                after_data=email_account_snapshot(account),
                request=request,
            )
        return self.response_with_etag({"data": EmailAccountSerializer(account).data}, account)

    @extend_schema(request=EmailAccountTestSerializer, responses=EmailAccountSerializer)
    @action(detail=True, methods=["post"], url_path="test-send")
    def test_send(self, request, pk=None):
        account = self.get_object()
        require_matching_etag(request, account)
        serializer = EmailAccountTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        failure = None
        with transaction.atomic():
            account = EmailAccount.objects.select_for_update().get(pk=account.pk, employee=self._employee())
            require_matching_etag(request, account)
            before_data = email_account_snapshot(account)
            try:
                send_test_email(account=account, recipient=serializer.validated_data["recipient"])
            except Conflict as exc:
                failure = exc
                account.last_test_status = EmailAccountTestStatus.FAILED
            else:
                account.last_test_status = EmailAccountTestStatus.SUCCESS
            account.last_tested_at = timezone.now()
            account.save(update_fields=["last_test_status", "last_tested_at", "updated_at"])
            write_audit_log(
                object_type="EMAIL_ACCOUNT",
                object_id=account.pk,
                action="TEST_SEND_FAILED" if failure else "TEST_SEND_SUCCEEDED",
                actor_employee=self._employee(),
                before_data=before_data,
                after_data=email_account_snapshot(account),
                request=request,
            )
        if failure:
            raise failure
        return self.response_with_etag({"data": EmailAccountSerializer(account).data}, account)
