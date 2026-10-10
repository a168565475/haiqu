from rest_framework.routers import SimpleRouter

from django.urls import path

from .views import (
    ProductInformationViewSet,
    ProductOptionsView,
    RawMaterialInformationViewSet,
    RawMaterialOptionsView,
)


router = SimpleRouter()
router.register("products", ProductInformationViewSet, basename="product-information")
router.register("raw-materials", RawMaterialInformationViewSet, basename="raw-material-information")

urlpatterns = [
    path("products/options/", ProductOptionsView.as_view({"get": "list"}), name="product-options"),
    path(
        "raw-materials/options/",
        RawMaterialOptionsView.as_view({"get": "list"}),
        name="raw-material-options",
    ),
    *router.urls,
]
