from rest_framework.routers import SimpleRouter

from .views import InquiryItemViewSet, InquiryViewSet


router = SimpleRouter()
router.register("inquiries", InquiryViewSet, basename="inquiry")
router.register("inquiry-items", InquiryItemViewSet, basename="inquiry-item")

urlpatterns = router.urls
