from rest_framework.routers import SimpleRouter

from .views import (
    QuotationContainerTierViewSet,
    QuotationEmailDispatchAttemptViewSet,
    QuotationLineViewSet,
    QuotationTemplateViewSet,
    QuotationVersionViewSet,
    QuotationViewSet,
)


router = SimpleRouter()
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("quotation-templates", QuotationTemplateViewSet, basename="quotation-template")
router.register("quotation-versions", QuotationVersionViewSet, basename="quotation-version")
router.register("quotation-email-attempts", QuotationEmailDispatchAttemptViewSet, basename="quotation-email-attempt")
router.register("quotation-lines", QuotationLineViewSet, basename="quotation-line")
router.register("quotation-container-tiers", QuotationContainerTierViewSet, basename="quotation-container-tier")

urlpatterns = router.urls
