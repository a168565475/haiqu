from rest_framework.routers import SimpleRouter

from .views import InquiryItemViewSet, InquiryViewSet
from .handling_settings import InquiryHandlingSettingsViewSet


router = SimpleRouter()
router.register('inquiry-handling-time', InquiryHandlingSettingsViewSet, basename='inquiry-handling-time')
router.register("inquiries", InquiryViewSet, basename="inquiry")
router.register("inquiry-items", InquiryItemViewSet, basename="inquiry-item")

urlpatterns = router.urls
