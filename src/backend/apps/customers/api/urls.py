from django.urls import path
from rest_framework.routers import SimpleRouter

from .governance_views import (
    CustomerAccessGrantNestedViewSet,
    CustomerAccessGrantViewSet,
    CustomerDuplicateCandidateViewSet,
    CustomerDuplicateCaseViewSet,
    CustomerMergeOperationViewSet,
    CustomerTransferRequestViewSet,
)

from .views import (
    AddressUsageViewSet,
    ContactMethodViewSet,
    ContactRoleViewSet,
    CustomerAddressViewSet,
    CustomerContactViewSet,
    CustomerEntityViewSet,
    CustomerViewSet,
    EntityRoleViewSet,
)


router = SimpleRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("customer-entities", CustomerEntityViewSet, basename="customer-entity")
router.register("customer-addresses", CustomerAddressViewSet, basename="customer-address")
router.register("contacts", CustomerContactViewSet, basename="contact")
router.register("contact-methods", ContactMethodViewSet, basename="contact-method")
router.register("customer-entity-roles", EntityRoleViewSet, basename="customer-entity-role")
router.register("customer-address-usages", AddressUsageViewSet, basename="customer-address-usage")
router.register("contact-roles", ContactRoleViewSet, basename="contact-role")
router.register("customer-transfer-requests", CustomerTransferRequestViewSet, basename="customer-transfer-request")
router.register("customer-access-grants", CustomerAccessGrantViewSet, basename="customer-access-grant")
router.register("customer-duplicate-cases", CustomerDuplicateCaseViewSet, basename="customer-duplicate-case")
router.register("customer-duplicate-candidates", CustomerDuplicateCandidateViewSet, basename="customer-duplicate-candidate")
router.register("customer-merges", CustomerMergeOperationViewSet, basename="customer-merge")

customer_access_grants = CustomerAccessGrantNestedViewSet.as_view({"get": "list", "post": "create"})

urlpatterns = [
    path(
        "customers/<uuid:customer_pk>/access-grants/",
        customer_access_grants,
        name="customer-access-grant-nested-list",
    ),
    *router.urls,
]
