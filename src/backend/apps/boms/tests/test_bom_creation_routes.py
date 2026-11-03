from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

from apps.boms.api.urls import router
from apps.boms.api.views import BomViewSet


class BomCreationRouteTests(SimpleTestCase):
    databases = set()

    def test_bom_does_not_expose_auxiliary_configuration_creation(self):
        self.assertNotIn("create_auxiliary_reference", {action.__name__ for action in BomViewSet.get_extra_actions()})
        self.assertNotIn("bom-create-auxiliary-reference", {route.name for route in router.urls})
        with self.assertRaises(NoReverseMatch):
            reverse("bom-create-auxiliary-reference")
