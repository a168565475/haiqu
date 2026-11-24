"""新页面复用已确认业务规则及字段解析说明；不加载聊天、密钥或整个知识库。"""

import hashlib
import json
from pathlib import Path

from .errors import AiProviderRequestFailed


RULE_VERSION = "2026-11-14.1"
CONTRACT_VERSION = 2

# 只保留方法和业务语义。原订单的确认值须经源指纹筛选后另行传入。
RULES = {
    "A01": "有管材表头、材质和单位依据的型材归管材；部件、材质、截面、外径、壁厚、切长、每成品支数、每根切数、长料长度分别提取。管材length_value、unit_consumption、tube_cut_piece_count须逐项返回证据值或明确MISSING/UNREADABLE/CONFLICT，不能省略。原材料长度栏中的‘切N支’是每根切割支数，须写入tube_cut_piece_count，不能只放raw_content；不能误用旁边采购支数列。Φ结合明确管材语境可表示圆管，不能推广到五金塑件。",
    "A02": "长料长度以米承接，原值保留三位小数，不自动截成两位；其他字段精度不随此改变。",
    "A03": "管材业务重量和面积由ERP有效公式计算，模型不代算。原表单支、每成品、长料单根、整单数值及基数完整保留raw_content，供ERP显示差异；公式依据缺失待处理。",
    "A04": "面料复合描述分别提取规格、涂层、门幅、色卡、色号和颜色；基础纤维材质未说明不猜。面料中的PE涂层不能推广为塑件涂层。",
    "A05": "明确为长度与两端宽度的裁片，只以长度乘最大宽度填写加工后尺寸，不另设小宽或异形参数；不同用途的适配尺寸不能取最大。单位和尺寸含义仍须有依据。",
    "A06": "已确定为每成品裁片量的数量按每成品片数提取；套数表达须等价且不重复相乘，不能当整单片数或耗米。共用原料只设一个父行并只计一次用量。",
    "A07": "塑件材质、颜色与适配规格分别提取，开口、配孔等不同功能尺寸全部保留，不套裁片最大宽度规则。",
    "A08": "蓝白锌填五金颜色hardware_color；盐雾小时数、盐水浓度完整保留在适用五金材料行notes，不新设表面处理或质量列，也不扩大到整份BOM。",
    "A09": "五金明确有效的单件重量采用原值，单位确定时可换算克/千克并注明；缺失由ERP可用公式处理，不能自行补造。单件、每成品合计和整单重量分清；辅助区先核对材料身份，不能只按同行拼接。",
    "A10": "棉原料与裁后片数必须分开，裁片PCS不是原料耗米，按样品克重不等于已有克重数值。仅在本次源版本确认明确本厂裁剪时采用该安排，不能默认所有棉料厂内裁剪。",
    "A11": "同文件的所有实际任务分别识别，首个放主任务块，其余放additional_tasks；每任务保留自己的产品、BOM和来源，不能只取第一个。用户逐个选择预览和确认创建，不能输出自动批量创建动作。同任务颜色与交货批次不另建任务。",
    "A12": "尽量多做等意向数量先记对应备注，人工明确确认后才增加数量；明确多备按原表余量规则处理。数量、单位、适用范围保留，已计入总量的余量不能再加，不改变成品生产量。",
    "A13": "原表合同号及客户PO暂不填业务字段，contract_number留空并在note标明A13用户暂不承接；原文件证据仍保留。指定来源的特定编号仅按宿主传入的源版本确认跳过，不忽略全部产品货号、生产任务号或批次。",
    "A14": "产品明确长宽高按原表填写；坐宽、背高、坐高保留名称和数值，不能混成整体长宽高。成品规格、部件规格和包装箱规分开，不猜单位。",
    "A15": "生产明细按所属产品和现有模板类别填写：明确需要该项填true并保留要求，明确不需要填false并保留说明，没有明确依据为null且标MISSING/UNREADABLE/CONFLICT。非空文字不一定需要，否定字也不一定表示不需要。",
    "A16": "任务日期、人员、产品名称/材质/颜色/数量/单位、包装与批次、价税费用、计划和其他要求分别对应现有字段。生产数量与箱数、材料用量分开；特殊要求按任务或产品范围归属，无法对应内容仍列issues待处理。",
    "D01": "未知价税允许待补，不填0、不默认为不含税。原表明确币种独立保留，外币不能写成人民币；材料成本不能填产品售价。",
    "D04": "一致内容可合并，实质冲突保留双方来源并集中列问题，不静默选值或覆盖人工修正。",
    "D05": "共用材料保留适用范围、数量基数和总耗；分色材料按各色数量记录，不能对每个颜色复制整单共用总耗。",
    "D06": "明确外供仍保留材料及制造用量、原0采购量和供料说明；0采购不等于所有材料外供，不猜具体供料人。",
    "D09": "产品原名称、规格等完整保留；模型不猜ERP主档ID，实际关联由ERP匹配，无法匹配或歧义列待处理。",
    "D10": "材料名称、规格、单位和用量完整保留；未匹配不删行、不猜配主档。",
    "D11": "数量、交期等关键冲突按任务集中列待处理，不因一项任务有问题丢弃其他任务；日期须先区分任务表头和具体批次，仅同一日期字段存在互相矛盾的证据才判CONFLICT，不把不同批次交期当成同一字段冲突。本页面仍先预览确认，禁止代替ERP决定已接单。",
    "D12": "分批交货保留在原任务内；任务表头明确交货日期独立填写task.delivery_date，各批product_key、颜色、包装方式、数量、箱数和日期分别填写task.delivery_batches。不同批次日期不清空或替换表头交期，不自行取最早或最晚批次日期代填任务交期，也不因批次拆任务。",
    "D13": "缺计划开工/完工可后补，不用交期或当天替代。",
    "D14": "识别结果不决定权限和业务状态；创建和接单由ERP现有权限、确认及事务处理。",
    "D15": "原表制单人对应业务员；跟单员按明确角色保留。姓名缩写、多人不明或角色冲突待选，不伪造员工ID。",
    "D16": "仅已读完整相关内容且确实未写订单误差时，默认0%，status=DEFAULTED，note注明D16及确实未填写，source_ids引用核对过的任务上下文。材料损耗不是订单误差。",
    "D17": "仅确实未写产前样要求时，默认不需要产前样，status=DEFAULTED，note注明D17，引用已读任务上下文；未读控件、冲突或部分颜色适用不得套默认。大货留样不是产前样。",
    "D18": "仅确实未注明翻单时，默认新单，即is_repeat_order=false，status=DEFAULTED且note注明D18；引用旧样不能独立证明翻单，未读/冲突不能套默认。",
    "D19": "明确零生产量的产品不生成实际产品/BOM，但在issues保留原值、来源及跳过去向；未填不是0，零采购材料仍保留。",
    "D21": "同任务后续文件保留来源和差异，不静默覆盖已确认值；由ERP处理查重、复用或更新，模型不输出数据库动作。",
    "D22": "明确采购余量保留，未写不额外增加、不重复叠加。净需求、余量、最终需求和来源口径分别保留；订单误差0不表示采购余量0。",
    "D23": "相关文字及附页已读，只有一个交期且没有分批证据时可默认SINGLE，status=DEFAULTED、note注明D23，引用任务上下文；已匹配的来源确认规则解决的旧日期冲突不得再次阻挡默认，真实批次证据仍优先；附页缺失、未读、待定或尚未解决的冲突不能套默认。",
    "G01": "缺失、未读、冲突、明确0、不适用和用户要求跳过必须区别；问题集中展示原值、来源、对象及处理方式。未读图片不等于表格未填写，不能以技术成功冒充业务正确。",
    "T01": "日期字段解析说明（不是新增用户业务确认）：省略年份的月日，只能在同一任务已有完整日期与连续批次语境能唯一确定年份时补全年份，输出ISO YYYY-MM-DD并标EXTRACTED；note保留原月日及年份解析依据，source_ids同时引用原月日和完整日期/批次关系证据。不使用当前年份、文件名年份或其他任务年份；跨年须有明确或唯一的时间顺序依据，不能盲目沿用同年或自动加一年。年份不能唯一判断时保留原文及原因待确认，不因此清空已有独立证据的任务表头交期。",
}

DEFAULT_RULES = {
    "order_tolerance_percent": ("D16", 0),
    "preproduction_sample_required": ("D17", False),
    "is_repeat_order": ("D18", False),
    "delivery_method": ("D23", "SINGLE"),
}

DETAIL_TEMPLATE = json.loads(
    (Path(__file__).resolve().parents[1] / "samples/config/sampling_detail_template.json").read_text(encoding="utf-8")
)["rows"]
DETAIL_KEYS = tuple(row["key"] for row in DETAIL_TEMPLATE)


def rule_instructions():
    lines = "\n".join(f"{key}: {text}" for key, text in RULES.items())
    details = "\n".join(f"- {row['key']}：{row['type']} / {row['category']}" for row in DETAIL_TEMPLATE)
    return f"识别规则版本 {RULE_VERSION}（复用已确认业务规则及字段解析说明；仅识别与预填，不执行写库）：\n{lines}\n生产明细模板：\n{details}"


def source_rule_context(source, confirmed_rules=()):
    """只接受宿主传入且匹配当前源指纹的定向确认；不自行扫描私有资料。"""
    fingerprint = source.get("source_sha256")
    selected = []
    for item in confirmed_rules:
        if not isinstance(item, dict):
            raise AiProviderRequestFailed("OPENAI_INPUT_SOURCE_INVALID")
        if item.get("source_sha256") != fingerprint or not fingerprint:
            continue
        if (set(item) != {"rule_id", "source_sha256", "task_number", "instruction"}
                or item["rule_id"] not in {"D07", "D08", "D20", "A10", "A13"}
                or not isinstance(item["task_number"], str) or not item["task_number"].strip()
                or not isinstance(item["instruction"], str) or not item["instruction"].strip()):
            raise AiProviderRequestFailed("OPENAI_INPUT_SOURCE_INVALID")
        selected.append({key: item[key] for key in ("rule_id", "task_number", "instruction")})
    return selected


def recognition_metadata(source_rules=()):
    digest = hashlib.sha256(rule_instructions().encode("utf-8")).hexdigest()
    return {
        "contract_version": CONTRACT_VERSION,
        "rule_version": RULE_VERSION,
        "rule_ids": list(RULES),
        "rule_sha256": digest,
        "source_rule_ids": sorted({item["rule_id"] for item in source_rules}),
    }
