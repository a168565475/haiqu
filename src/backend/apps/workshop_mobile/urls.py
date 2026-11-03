from django.urls import path

from .views import MobileContextView, MobileFinishedReceiptOptionsView, MobilePlanDetailView, MobilePlanListView


urlpatterns = [
    path("context/", MobileContextView.as_view(), name="workshop-mobile-context"),
    path("finished-receipt-options/", MobileFinishedReceiptOptionsView.as_view(), name="workshop-mobile-finished-receipt-options"),
    path("plans/", MobilePlanListView.as_view(), name="workshop-mobile-plans"),
    path("plans/<uuid:schedule_product_id>/", MobilePlanDetailView.as_view(), name="workshop-mobile-plan"),
]
