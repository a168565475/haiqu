class AiProductionImportError(Exception):
    """对外可展示的 AI 导入错误，不携带密钥、堆栈或原始外部响应。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AiProviderNotConfigured(AiProductionImportError):
    def __init__(self):
        super().__init__("OPENAI_NOT_CONFIGURED", "当前账号尚未配置 OpenAI Key。")


class AiProviderRequestFailed(AiProductionImportError):
    def __init__(self, code="OPENAI_REQUEST_FAILED"):
        messages = {
            "OPENAI_TIMEOUT": "OpenAI 识别等待超时，本次未获得识别结果，未创建生产任务或 BOM。",
            "OPENAI_NETWORK_ERROR": "后端无法连接 OpenAI，请检查服务器网络后重试。",
            "OPENAI_AUTH_FAILED": "OpenAI 拒绝了当前 Key，请检查 Key 是否有效。",
            "OPENAI_ACCESS_DENIED": "当前 OpenAI 项目没有调用该模型的权限。",
            "OPENAI_MODEL_NOT_FOUND": "OpenAI 模型或接口地址不可用，请检查配置。",
            "OPENAI_RATE_LIMITED": "OpenAI 达到调用限额，请检查额度或稍后重试。",
            "OPENAI_BAD_REQUEST": "OpenAI 拒绝了识别请求的参数，请联系维护人员检查请求格式。",
            "OPENAI_SERVER_ERROR": "OpenAI 服务暂时异常，请稍后重试。",
            "OPENAI_KEY_EMPTY": "当前账号尚未填写 OpenAI Key。",
            "OPENAI_INPUT_SOURCE_INVALID": "表格来源记录不完整，本次未发送识别请求，请重新上传文件。",
            "OPENAI_RESPONSE_TOO_LARGE": "OpenAI 返回结果超过读取上限，本次未创建业务单据。",
            "OPENAI_RESPONSE_JSON_INVALID": "OpenAI 返回的响应不是有效 JSON，本次未获得可用结果。",
            "ERP_ASSISTANT_LOOKUP_LIMIT": "生产助手本轮查询已达上限，尚未完成 ERP 对应；未创建生产任务或 BOM，请重试或核对原表说明。",
        }
        super().__init__(code, messages.get(code, "OpenAI 识别请求失败，请稍后重试。"))


class AiOutputInvalid(AiProductionImportError):
    def __init__(self, code="OPENAI_OUTPUT_INVALID", *, path="", reason=""):
        self.path = path
        self.reason = reason
        messages = {
            "OPENAI_RESPONSE_INCOMPLETE": "OpenAI 尚未返回完整识别结果，本次未创建业务单据。",
            "OPENAI_RESPONSE_INTERRUPTED": "OpenAI 连接提前结束，未收到完整识别结果，本次未创建业务单据。",
            "OPENAI_OUTPUT_LIMIT": "识别内容超过本次模型输出上限，未收到完整结果，本次未创建业务单据。",
            "OPENAI_RESPONSE_REFUSED": "OpenAI 未接受本次识别内容，本次未创建业务单据。",
            "OPENAI_RESPONSE_JSON_INVALID": "OpenAI 返回的响应不是有效 JSON，本次未获得可用结果。",
            "OPENAI_OUTPUT_ERP_FIELD_INVALID": "OpenAI 返回的字段内容不符合 ERP 字段规则。",
            "OPENAI_OUTPUT_SOURCE_INVALID": "OpenAI 返回的来源编号无法对应到本次表格。",
            "OPENAI_OUTPUT_SCHEMA_INVALID": "OpenAI 返回的任务、产品或 BOM 结构不完整。",
            "OPENAI_OUTPUT_TASK_KEY_INVALID": "OpenAI 返回的任务标识为空或重复。",
            "OPENAI_OUTPUT_PRODUCT_KEY_INVALID": "OpenAI 返回的产品标识为空或重复。",
            "OPENAI_OUTPUT_BOM_KEY_INVALID": "OpenAI 返回的 BOM 产品或原料关联不正确。",
            "OPENAI_OUTPUT_BATCH_KEY_INVALID": "OpenAI 返回的交付批次关联了不属于该任务的产品。",
            "ERP_ASSISTANT_OUTPUT_INVALID": "生产助手返回的 ERP 对应结果不完整或结构有误。",
            "ERP_ASSISTANT_CANDIDATE_INVALID": "生产助手选择了本轮未查到的材料、属性、单位或工艺，已停止采用。",
            "ERP_ASSISTANT_INCOMPLETE": "生产助手尚未处理全部材料行，本轮 ERP 对应未完成。",
        }
        message = messages.get(code, "OpenAI 返回内容未通过来源和结构校验。")
        if path and reason:
            message += f" 字段 {path}：{reason}"
        super().__init__(code, message)

