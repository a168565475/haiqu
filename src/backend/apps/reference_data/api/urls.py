from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AccessoryColorViewSet,
    AccessoryMaterialViewSet,
    AccessoryProductNameViewSet,
    AccessorySpecificationViewSet,
    ConfigReleaseViewSet,
    CountryViewSet,
    CourierViewSet,
    CurrencyViewSet,
    DictionaryTypeViewSet,
    ExchangeRateViewSet,
    FabricMaterialViewSet,
    FabricSpecificationViewSet,
    FabricWidthViewSet,
    IncotermViewSet,
    MasterDataSummaryView,
    NumberRuleViewSet,
    PaymentMethodViewSet,
    PortViewSet,
    ProductCategoryViewSet,
    ProductColorViewSet,
    ProductItemViewSet,
    ProductionDataSummaryView,
    ProductionUnitViewSet,
    PublishedOptionsView,
    PublishedConfigVersionView,
    PublishedOptionsBatchView,
    ReferenceDataSummaryView,
    ReferenceDictionaryViewSet,
    SystemParameterViewSet,
    TubeCoatingColorViewSet,
    TubeDiameterViewSet,
    TubeMaterialViewSet,
    TubeProductNameViewSet,
    TubeShapeViewSet,
    TubeThicknessViewSet,
    TransportMethodViewSet,
    UnitViewSet,
)


router = SimpleRouter()
router.register("reference-data/dictionary-types", DictionaryTypeViewSet, basename="dictionary-type")
router.register("reference-data/dictionary-items", ReferenceDictionaryViewSet, basename="dictionary-item")
router.register("reference-data/config-releases", ConfigReleaseViewSet, basename="config-release")
router.register("reference-data/system-parameters", SystemParameterViewSet, basename="system-parameter")
router.register("reference-data/countries", CountryViewSet, basename="country")
router.register("reference-data/currencies", CurrencyViewSet, basename="currency")
router.register("reference-data/exchange-rates", ExchangeRateViewSet, basename="exchange-rate")
router.register("reference-data/units", UnitViewSet, basename="unit")
router.register("reference-data/incoterms", IncotermViewSet, basename="incoterm")
router.register("reference-data/payment-methods", PaymentMethodViewSet, basename="payment-method")
router.register("reference-data/transport-methods", TransportMethodViewSet, basename="transport-method")
router.register("reference-data/ports", PortViewSet, basename="port")
router.register("reference-data/couriers", CourierViewSet, basename="courier")
router.register("reference-data/number-rules", NumberRuleViewSet, basename="number-rule")
router.register("reference-data/product-categories", ProductCategoryViewSet, basename="product-category")
router.register("reference-data/production-units", ProductionUnitViewSet, basename="production-unit")
router.register("reference-data/product-colors", ProductColorViewSet, basename="product-color")
router.register("reference-data/product-items", ProductItemViewSet, basename="product-item")
router.register("reference-data/fabric-materials", FabricMaterialViewSet, basename="fabric-material")
router.register("reference-data/fabric-specifications", FabricSpecificationViewSet, basename="fabric-specification")
router.register("reference-data/fabric-widths", FabricWidthViewSet, basename="fabric-width")
router.register("reference-data/tube-product-names", TubeProductNameViewSet, basename="tube-product-name")
router.register("reference-data/tube-thicknesses", TubeThicknessViewSet, basename="tube-thickness")
router.register("reference-data/tube-diameters", TubeDiameterViewSet, basename="tube-diameter")
router.register("reference-data/tube-materials", TubeMaterialViewSet, basename="tube-material")
router.register("reference-data/tube-shapes", TubeShapeViewSet, basename="tube-shape")
router.register("reference-data/tube-coating-colors", TubeCoatingColorViewSet, basename="tube-coating-color")
router.register("reference-data/accessory-product-names", AccessoryProductNameViewSet, basename="accessory-product-name")
router.register("reference-data/accessory-specifications", AccessorySpecificationViewSet, basename="accessory-specification")
router.register("reference-data/accessory-colors", AccessoryColorViewSet, basename="accessory-color")
router.register("reference-data/accessory-materials", AccessoryMaterialViewSet, basename="accessory-material")

urlpatterns = [
    path("reference-data/options-batch/", PublishedOptionsBatchView.as_view(), name="published-options-batch"),
    path("reference-data/published-version/", PublishedConfigVersionView.as_view(), name="published-config-version"),
    path(
        "reference-data/summary/",
        ReferenceDataSummaryView.as_view(),
        name="reference-data-summary",
    ),
    path(
        "reference-data/master-data-summary/",
        MasterDataSummaryView.as_view(),
        name="master-data-summary",
    ),
    path(
        "reference-data/production-data-summary/",
        ProductionDataSummaryView.as_view(),
        name="production-data-summary",
    ),
    path(
        "reference-data/options/<str:type_code>/",
        PublishedOptionsView.as_view(),
        name="reference-data-options",
    ),
    *router.urls,
]
