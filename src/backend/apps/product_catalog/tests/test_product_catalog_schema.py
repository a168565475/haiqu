from django.apps import apps
from django.test import SimpleTestCase
from django.urls import include, path
from drf_spectacular.generators import SchemaGenerator


ROOT = "/api/v1/product-catalog/"


class ProductCatalogSchemaTests(SimpleTestCase):
    def test_category_options_document_read_only_nonnegative_name_count(self):
        schema = SchemaGenerator(patterns=[path("api/v1/", include("apps.product_catalog.api.urls"))]).get_schema(public=True)
        category = schema["components"]["schemas"]["ProductCatalogCategory"]
        self.assertIn("name_count", category["properties"])
        self.assertEqual(category["properties"]["name_count"], {"type": "integer", "minimum": 0, "readOnly": True})
        self.assertIn("name_count", category["required"])

    def test_full_schema_keeps_product_options_separate_from_material_options(self):
        schema = SchemaGenerator().get_schema(public=True)
        response = schema["paths"][f"{ROOT}options/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        while "$ref" in response:
            response = schema["components"]["schemas"][response["$ref"].split("/")[-1]]
        options = response["properties"]["data"]
        while "$ref" in options:
            options = schema["components"]["schemas"][options["$ref"].split("/")[-1]]
        self.assertEqual(set(options["properties"]), {"categories", "units", "scales"})

    def test_schema_documents_response_envelopes_and_concurrency_headers(self):
        self.assertTrue(apps.is_installed("apps.product_catalog"), "尚未实现独立产品API契约")
        schema = SchemaGenerator(patterns=[path("api/v1/", include("apps.product_catalog.api.urls"))]).get_schema(public=True)

        def resolve(value):
            while "$ref" in value:
                value = schema["components"]["schemas"][value["$ref"].split("/")[-1]]
            return value

        paths = schema["paths"]
        listing = paths[ROOT]["get"]
        body = resolve(listing["responses"]["200"]["content"]["application/json"]["schema"])
        self.assertEqual(set(body["properties"]), {"data", "meta"})
        self.assertEqual({parameter["name"] for parameter in listing["parameters"]}, {"name_id", "category_id", "q", "page", "page_size"})
        for url, operations in paths.items():
            for method, operation in operations.items():
                if method not in {"post", "patch", "delete"}:
                    continue
                success = "201" if method == "post" and url in {ROOT, f"{ROOT}names/"} else "200"
                self.assertIn("ETag", operation["responses"][success].get("headers", {}))
                if success == "200":
                    header = next(parameter for parameter in operation["parameters"] if parameter["name"] == "If-Match")
                    self.assertTrue(header["required"])
                    self.assertIn("412", operation["responses"])
                    self.assertIn("428", operation["responses"])
        patch = paths[f"{ROOT}{{id}}/"]["patch"]
        fields = resolve(patch["requestBody"]["content"]["application/json"]["schema"])["properties"]
        self.assertEqual(set(fields), {"product_code", "item_number", "specification", "unit", "scale"})
        for code in ("400", "401", "403", "404", "412", "428"):
            error = resolve(patch["responses"][code]["content"]["application/json"]["schema"])
            self.assertIn("error", error["properties"])
