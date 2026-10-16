from django.urls import path

from .views import ProductCatalogNameViewSet, ProductCatalogViewSet


urlpatterns = [
    path("product-catalog/options/", ProductCatalogViewSet.as_view({"get": "options_list"}), name="product-catalog-options"),
    path("product-catalog/names/", ProductCatalogNameViewSet.as_view({"get": "list", "post": "create"}), name="product-catalog-names"),
    path("product-catalog/names/<uuid:pk>/", ProductCatalogNameViewSet.as_view({"get": "retrieve", "patch": "partial_update"}), name="product-catalog-name-detail"),
    path("product-catalog/", ProductCatalogViewSet.as_view({"get": "list", "post": "create"}), name="product-catalog-list"),
    path("product-catalog/<uuid:pk>/", ProductCatalogViewSet.as_view({"get": "retrieve", "patch": "partial_update"}), name="product-catalog-detail"),
    path("product-catalog/<uuid:pk>/colors/", ProductCatalogViewSet.as_view({"post": "add_color"}), name="product-catalog-add-color"),
    path("product-catalog/<uuid:pk>/colors/<uuid:color_id>/", ProductCatalogViewSet.as_view({"delete": "remove_color"}), name="product-catalog-remove-color"),
]
