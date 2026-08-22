from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.core.api.authentication.ApiSessionAuthentication"
    name = "sessionCookie"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": "Django Session Cookie；写操作还必须携带 X-CSRFToken。",
        }
