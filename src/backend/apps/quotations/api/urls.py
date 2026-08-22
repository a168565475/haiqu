from rest_framework.routers import SimpleRouter

from .views import QuotationLineViewSet, QuotationTemplateViewSet, QuotationVersionViewSet, QuotationViewSet


router = SimpleRouter()
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("quotation-templates", QuotationTemplateViewSet, basename="quotation-template")
router.register("quotation-versions", QuotationVersionViewSet, basename="quotation-version")
router.register("quotation-lines", QuotationLineViewSet, basename="quotation-line")

urlpatterns = router.urls
