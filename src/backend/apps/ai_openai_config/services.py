from .crypto import decrypt_key
from .models import OpenAIKeyConfig


def get_active_credentials(employee):
    """返回当前员工最近更新的调用凭据；调用方不得记录 api_key。"""

    config = OpenAIKeyConfig.objects.filter(employee=employee).order_by("-updated_at", "-id").first()
    if config is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("当前账号尚未配置 OpenAI Key。")
    return {
        "api_key": decrypt_key(config.key_ciphertext),
        "model": config.model,
        "document_reasoning_effort": config.document_reasoning_effort,
        "material_reasoning_effort": config.material_reasoning_effort,
        "base_url": config.base_url,
        "label": config.label,
        "fingerprint": config.key_fingerprint,
    }

