from django.urls import path

from .send_record_views import NotificationSendRecordsView
from .notification_views import (
    NotificationDeliveriesView, NotificationInboxView, NotificationReadView,
    NotificationRuleDetailView, NotificationRulePreviewView, NotificationRulesView,
    NotificationTargetView, NotificationUnreadCountView, NotificationInboxDetailView,
    NotificationPreviewRecipientsView, NotificationPreviewSendView, NotificationPreviewAttemptView,
)


urlpatterns = [
    path("send-records/", NotificationSendRecordsView.as_view(), name="notification-send-records"),
    path("rules/", NotificationRulesView.as_view(), name="notification-rules"),
    path("rules/<str:event_code>/", NotificationRuleDetailView.as_view(), name="notification-rule-detail"),
    path("rules/<str:event_code>/preview/", NotificationRulePreviewView.as_view(), name="notification-rule-preview"),
    path("rules/<str:event_code>/preview-send/", NotificationPreviewSendView.as_view(), name="notification-preview-send"),
    path("preview-recipients/", NotificationPreviewRecipientsView.as_view(), name="notification-preview-recipients"),
    path("preview-attempts/<uuid:preview_id>/", NotificationPreviewAttemptView.as_view(), name="notification-preview-attempt"),
    path("inbox/", NotificationInboxView.as_view(), name="notification-inbox"),
    path("inbox/unread-count/", NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path("inbox/<uuid:recipient_id>/", NotificationInboxDetailView.as_view(), name="notification-inbox-detail"),
    path("inbox/<uuid:recipient_id>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("inbox/<uuid:recipient_id>/target/", NotificationTargetView.as_view(), name="notification-target"),
    path("deliveries/", NotificationDeliveriesView.as_view(), name="notification-deliveries"),
]
