from django.urls import path

from .notification_views import (
    NotificationDeliveriesView, NotificationInboxView, NotificationReadView,
    NotificationRuleDetailView, NotificationRulePreviewView, NotificationRulesView,
    NotificationTargetView, NotificationUnreadCountView,
)


urlpatterns = [
    path("rules/", NotificationRulesView.as_view(), name="notification-rules"),
    path("rules/<str:event_code>/", NotificationRuleDetailView.as_view(), name="notification-rule-detail"),
    path("rules/<str:event_code>/preview/", NotificationRulePreviewView.as_view(), name="notification-rule-preview"),
    path("inbox/", NotificationInboxView.as_view(), name="notification-inbox"),
    path("inbox/unread-count/", NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path("inbox/<uuid:recipient_id>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("inbox/<uuid:recipient_id>/target/", NotificationTargetView.as_view(), name="notification-target"),
    path("deliveries/", NotificationDeliveriesView.as_view(), name="notification-deliveries"),
]
