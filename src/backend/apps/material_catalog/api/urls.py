from django.urls import path

from .views import MaterialCatalogViewSet


urlpatterns = [
    path("material-catalog/options/", MaterialCatalogViewSet.as_view({"get": "options_list"}), name="material-catalog-options"),
    path("material-catalog/", MaterialCatalogViewSet.as_view({"get": "list", "post": "create"}), name="material-catalog-list"),
    path("material-catalog/<uuid:pk>/", MaterialCatalogViewSet.as_view({"get": "retrieve", "patch": "partial_update"}), name="material-catalog-detail"),
    path("material-catalog/<uuid:pk>/values/", MaterialCatalogViewSet.as_view({"post": "add_value"}), name="material-catalog-add-value"),
    path("material-catalog/<uuid:pk>/values/<uuid:value_id>/", MaterialCatalogViewSet.as_view({"delete": "remove_value"}), name="material-catalog-remove-value"),
    path("material-catalog/<uuid:pk>/units/", MaterialCatalogViewSet.as_view({"post": "add_unit"}), name="material-catalog-add-unit"),
    path("material-catalog/<uuid:pk>/units/<uuid:option_id>/", MaterialCatalogViewSet.as_view({"delete": "remove_unit"}), name="material-catalog-remove-unit"),
]
