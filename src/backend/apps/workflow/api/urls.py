from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ApprovalViewSet, SlaTrackingViewSet, TaskSourceOptionsView, TaskViewSet


router = SimpleRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("approvals", ApprovalViewSet, basename="approval")
router.register("sla-trackings", SlaTrackingViewSet, basename="sla-tracking")

urlpatterns = [path("task-source-options/", TaskSourceOptionsView.as_view(), name="task-source-options"), *router.urls]
