"""持久化单据的记账版本与运行开关必须一致，防止新旧余额同时被扣。"""

from django.conf import settings

from .stock_services import InventoryStockValidationError


LEGACY = "LEGACY"
PUBLIC = "PUBLIC_V2"


def public_flow_enabled():
    from .public_stock_cutover import get_cutover_control
    control = get_cutover_control()
    if control and control.state == "PUBLIC":
        return True
    return bool(getattr(settings, "PUBLIC_STOCK_FLOW_ENABLED", False))


def new_stock_mode():
    return PUBLIC if public_flow_enabled() else LEGACY


def public_issues_enabled():
    return public_flow_enabled() or bool(getattr(settings, "PUBLIC_STOCK_ISSUES_ENABLED", False))


def require_document_stock_mode(document, *, allow_issue_trial=False):
    """用于实际库存写入；已成功事件的幂等返回应放在此门禁之前。

    领料专项预演开关仅供第 4 步独立环境使用，完整切换开关优先。
    本函数不自动升级旧单，避免用当前 BOM 猜补当时在途实物。
    """
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write()
    mode = getattr(document, "stock_mode", None)
    if mode not in {LEGACY, PUBLIC}:
        raise InventoryStockValidationError(
            {"detail": "单据缺少有效库存版本，不能确定记账入口。"},
            code="PUBLIC_STOCK_MODE_INVALID",
        )
    enabled = public_flow_enabled()
    trial = allow_issue_trial and bool(getattr(settings, "PUBLIC_STOCK_ISSUES_ENABLED", False))
    if mode == LEGACY and enabled:
        raise InventoryStockValidationError(
            {"detail": "该单据沿用旧库存口径，须先核对未结数量及冻结属性并完成接续，不能继续扣写旧库存。"},
            code="PUBLIC_STOCK_LEGACY_DOCUMENT_BLOCKED",
            meta={"stock_mode": mode, "document_id": str(getattr(document, "pk", ""))},
        )
    if mode == PUBLIC and not (enabled or trial):
        raise InventoryStockValidationError(
            {"detail": "公共库存入口尚未启用，该单据不能回退到旧库存记账。"},
            code="PUBLIC_STOCK_FLOW_DISABLED",
        )
    return mode == PUBLIC


def require_transition_stock_mode():
    """仅供已验证历史交接桥接的服务调用；不改变原单据版本。"""
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write()
    if not public_flow_enabled():
        raise InventoryStockValidationError(
            {"detail": "旧单接续已准备，但公共库存尚未启用。"}, code="PUBLIC_STOCK_FLOW_DISABLED",
        )
    return True
