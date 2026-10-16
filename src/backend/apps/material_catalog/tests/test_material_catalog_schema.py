from django.test import SimpleTestCase
from django.urls import include, path
from drf_spectacular.generators import SchemaGenerator


ROOT = "/api/v1/material-catalog/"


class MaterialCatalogSchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator(patterns=[
            path("api/v1/", include("apps.material_catalog.api.urls")),
        ]).get_schema(public=True)

    def resolve(self, value):
        while "$ref" in value:
            value = self.schema["components"]["schemas"][value["$ref"].split("/")[-1]]
        return value

    def test_list_documents_actual_data_meta_envelope(self):
        operation = self.schema["paths"][ROOT]["get"]
        response = operation["responses"]["200"]
        body = self.resolve(response["content"]["application/json"]["schema"])
        self.assertEqual(set(body["properties"]), {"data", "meta"})
        self.assertEqual(body["properties"]["data"]["type"], "array")
        meta = self.resolve(body["properties"]["meta"])
        self.assertEqual(set(meta["properties"]), {"page", "page_size", "total", "total_pages"})
        self.assertEqual({parameter["name"] for parameter in operation["parameters"]}, {"category", "q", "page", "page_size"})

    def test_detail_writes_document_etag_and_required_if_match(self):
        paths = self.schema["paths"]
        for url, operations in paths.items():
            for method, operation in operations.items():
                if method not in {"get", "post", "patch", "delete"}:
                    continue
                detail_response = method != "get" or url == f"{ROOT}{{id}}/"
                if not detail_response:
                    continue
                with self.subTest(url=url, method=method):
                    success = "201" if url == ROOT and method == "post" else "200"
                    self.assertIn(success, operation["responses"])
                    self.assertIn("ETag", operation["responses"][success].get("headers", {}))
                    if method != "get" and url != ROOT:
                        header = next(parameter for parameter in operation["parameters"] if parameter["name"] == "If-Match")
                        self.assertEqual(header["in"], "header")
                        self.assertTrue(header["required"])
                        self.assertIn("412", operation["responses"])
                        self.assertIn("428", operation["responses"])

    def test_patch_documents_mandatory_boolean_and_structured_errors(self):
        operation = self.schema["paths"][f"{ROOT}{{id}}/"]["patch"]
        body = self.resolve(operation["requestBody"]["content"]["application/json"]["schema"])
        self.assertEqual(body.get("required", []), ["spray_enabled"])
        self.assertEqual(body["properties"]["spray_enabled"]["type"], "boolean")
        self.assertFalse(body["additionalProperties"])
        for code in ("400", "401", "403", "404", "412", "428"):
            with self.subTest(code=code):
                error = self.resolve(operation["responses"][code]["content"]["application/json"]["schema"])
                self.assertIn("error", error["properties"])
