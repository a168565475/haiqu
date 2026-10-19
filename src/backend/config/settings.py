import os
import json
from pathlib import Path

from corsheaders.defaults import default_headers


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-development-only")
DEBUG = env_bool("DJANGO_DEBUG", True)
# 第 4 步仅独立环境开启；正式切换须等完整库存写入链验收。
PUBLIC_STOCK_ISSUES_ENABLED = env_bool("PUBLIC_STOCK_ISSUES_ENABLED", False)
PUBLIC_STOCK_FLOW_ENABLED = env_bool("PUBLIC_STOCK_FLOW_ENABLED", False)
TUBE_OUTSOURCING_ENABLED = env_bool("TUBE_OUTSOURCING_ENABLED", False)
PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS = json.loads(os.getenv("PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS", "[]"))
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "django_filters",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.reference_data",
    "apps.products",
    "apps.material_catalog",
    "apps.product_catalog",
    "apps.organizations",
    "apps.access_control",
    "apps.files",
    "apps.workflow",
    "apps.customers",
    "apps.inquiries",
    "apps.quotations",
    "apps.samples",
    "apps.sales_orders",
    "apps.production_tasks",
    "apps.production_scheduling",
    "apps.outsourcing",
    "apps.boms",
    "apps.procurement",
    "apps.inventory",
    "apps.material_issues",
    "apps.workshop_config",
    "apps.workshop_reporting",
    "apps.crm",
    "apps.audit",
    "apps.imports",
    "apps.preferences",
    "apps.email_accounts",
    "apps.wecom",
]

MIDDLEWARE = [
    "apps.wecom.middleware.WeComOAuthSensitiveMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.debug_timing.ProductionReadTimingMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.ErpSessionAccessMiddleware",
    "apps.inventory.cutover_middleware.PublicStockCutoverMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"wecom_access": {"()": "apps.core.logging.WeComAccessLogFilter"}},
    "formatters": {
        "django.server": {
            "()": "django.utils.log.ServerFormatter", "format": "[{server_time}] {message}", "style": "{",
        },
    },
    "handlers": {
        "django.server": {
            "class": "logging.StreamHandler", "level": "INFO", "formatter": "django.server",
            "filters": ["wecom_access"],
        },
    },
    "loggers": {"django.server": {"handlers": ["django.server"], "level": "INFO", "propagate": False}},
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "haiqu_erp"),
        "USER": os.getenv("POSTGRES_USER", "haiqu"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "postgres"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "TEST": {"NAME": os.getenv("POSTGRES_TEST_DB") or None},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = ["apps.core.auth.ErpModelBackend"]

# Stage-gated rollout: enable only after migration and reviewed activation.
ACCESS_MANAGEMENT_ENABLED = env_bool("ACCESS_MANAGEMENT_ENABLED", False)
SALES_ACCESS_ENABLED = env_bool("SALES_ACCESS_ENABLED", False)
MODULE_ACCESS_ENABLED = env_bool("MODULE_ACCESS_ENABLED", False)
ACCESS_RESOURCE_SCOPES_ENABLED = env_bool("ACCESS_RESOURCE_SCOPES_ENABLED", False)
WORK_REPORT_DELETION_ENABLED = env_bool("WORK_REPORT_DELETION_ENABLED", False)
WORK_REPORT_HISTORY_ENABLED = env_bool("WORK_REPORT_HISTORY_ENABLED", False)

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080",
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, "if-match")
CORS_EXPOSE_HEADERS = ["ETag", "X-Export-Count"]

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080",
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.api.authentication.ApiSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.core.api.permissions.HasActiveEmployee",
    ],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.pagination.StandardPageNumberPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.core.api.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "SEARCH_PARAM": "q",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "haiqu ERP CRM API",
    "DESCRIPTION": "haiqu ERP 第一阶段客户 CRM API V1",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "ContactStatusEnum": "apps.customers.models.ContactStatus.choices",
        "TaskStatusEnum": "apps.workflow.models.TaskStatus.choices",
        "InquiryStatusEnum": "apps.inquiries.models.InquiryStatus.choices",
        "ApprovalStatusEnum": "apps.workflow.models.ApprovalStatus.choices",
        "QuotationVersionStatusEnum": "apps.quotations.models.QuotationVersionStatus.choices",
        "SampleRequestStatusEnum": "apps.samples.models.SampleRequestStatus.choices",
        "SalesOrderStatusEnum": "apps.sales_orders.models.SalesOrderStatus.choices",
        "ProductionTaskStatusEnum": "apps.production_tasks.models.ProductionTaskStatus.choices",
        "BomStatusEnum": "apps.boms.models.BomStatus.choices",
        "BomCreationMethodEnum": "apps.boms.models.BomCreationMethod.choices",
        "SupplierTypeEnum": "apps.procurement.models.SupplierType.choices",
        "SupplierCategoryEnum": "apps.procurement.models.SupplierCategory.choices",
        "SupplierPaymentCycleEnum": "apps.procurement.models.SupplierPaymentCycle.choices",
        "InventoryRecordStatusEnum": "apps.inventory.models.RecordStatus.choices",
        "WarehouseTypeEnum": "apps.inventory.models.WarehouseType.choices",
        "WorkshopConfigRecordStatusEnum": "apps.workshop_config.models.RecordStatus.choices",
        "WorkshopEmployeeStatusEnum": "apps.workshop_config.models.WorkshopEmployeeStatus.choices",
        "WorkshopCraftTypeEnum": "apps.workshop_config.models.CraftType.choices",
        "ProductionScheduleStatusEnum": "apps.production_scheduling.models.ScheduleStatus.choices",
        "ProductionPlanCategoryEnum": "apps.workshop_config.models.PlanCategory.choices",
        "CustomerTransferStatusEnum": "apps.customers.models.TransferStatus.choices",
        "CustomerDuplicateCaseStatusEnum": "apps.customers.models.DuplicateCaseStatus.choices",
        "CustomerDuplicateDecisionEnum": "apps.customers.models.DuplicateDecision.choices",
        "CustomerMergeStatusEnum": "apps.customers.models.MergeStatus.choices",
        "ComplaintStatusEnum": "apps.customers.models.ComplaintStatus.choices",
    },
}

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# 独立配置缓存，避免改变认证/会话等其他缓存策略。
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "configuration": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "haiqu:configuration:v1",
        "OPTIONS": {"socket_connect_timeout": 0.2, "socket_timeout": 0.2},
    },
    "wecom": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "haiqu:wecom:v1",
        "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
    },
}

CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_PORT = int(os.getenv("CLAMAV_PORT", "3310"))
CLAMAV_TIMEOUT = float(os.getenv("CLAMAV_TIMEOUT", "15"))
# 默认开启；内部开发环境可通过 .env 显式关闭，文件仍保留格式、签名、大小和权限校验。
FILE_VIRUS_SCAN_ENABLED = env_bool("FILE_VIRUS_SCAN_ENABLED", True)
CONTACT_IMPORT_MAX_BYTES = int(os.getenv("CONTACT_IMPORT_MAX_BYTES", str(5 * 1024 * 1024)))
CONTACT_IMPORT_MAX_ROWS = int(os.getenv("CONTACT_IMPORT_MAX_ROWS", "500"))
BOM_IMPORT_MAX_BYTES = int(os.getenv("BOM_IMPORT_MAX_BYTES", str(100 * 1024 * 1024)))

# 账户级邮件 SMTP 授权码加密密钥。第一个用于写入，后续密钥用于轮换期解密。
EMAIL_ACCOUNT_FERNET_KEYS = env_list("EMAIL_ACCOUNT_FERNET_KEYS")

# 企业微信应用及消息回调凭据；与邮件账户密钥独立，首个写入、其余轮换解密。
WECOM_FERNET_KEYS = env_list("WECOM_FERNET_KEYS")

# 仅用于本机开发演示。生产环境即使误设环境变量，也会因 DEBUG=False 而保持关闭。
DEV_AUTO_LOGIN_ENABLED = DEBUG and env_bool("DEV_AUTO_LOGIN_ENABLED", False)
DEV_AUTO_LOGIN_USERNAME = os.getenv("DEV_AUTO_LOGIN_USERNAME", "admin").strip()
DEV_AUTO_LOGIN_ALLOWED_HOSTS = env_list(
    "DEV_AUTO_LOGIN_ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1]",
)
