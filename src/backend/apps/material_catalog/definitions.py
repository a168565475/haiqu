"""已确认的类别属性名单；属性值由各份物料档案独立维护。"""


def field(key, label, kind="text"):
    return {"key": key, "label": label, "kind": kind}


def template(key, label, fields, *, supports_spray=False):
    return {
        "key": key, "label": label, "supports_spray": supports_spray,
        "fields": [*fields, field("unit", "可用单位", "unit")],
    }


CATEGORIES = [
    {"key": "TUBE", "label": "管材", "templates": [template("TUBE", "管材", [
        field("material", "材质"), field("color", "颜色"), field("shape", "截面形状", "shape"),
        field("section_size", "截面尺寸", "dimension"), field("thickness", "厚度"), field("length", "长度"),
    ], supports_spray=True)]},
    {"key": "FABRIC", "label": "面料", "templates": [template("FABRIC", "面料", [
        field("material", "材质"), field("color", "颜色"), field("fabric_spec", "面料规格"),
        field("width", "门幅"), field("gram_weight", "克重"), field("finish", "涂层/后处理"),
    ])]},
    {"key": "HARDWARE", "label": "五金", "templates": [template("HARDWARE", "五金", [
        field("material", "材质"), field("color", "颜色"), field("surface_finish", "表面处理"),
        field("specification", "型号/规格"), field("size", "尺寸"), field("thread", "螺纹规格"),
        field("flow_unit", "流转单位"),
    ], supports_spray=True)]},
    {"key": "PLASTIC", "label": "塑料件", "templates": [template("PLASTIC", "塑料件", [
        field("material", "材质"), field("color", "颜色"), field("model", "型号/图号"),
        field("size", "尺寸"), field("tube_size", "适配管材尺寸"),
        field("specification", "规格描述"),
    ])]},
    {"key": "PACKAGING", "label": "包材", "templates": [
        template("CARTON", "纸箱", [
            field("material", "纸质/材质"), field("layers", "层数"), field("size", "长宽高尺寸"),
            field("box_type", "箱子形状"), field("model", "型号"), field("color", "颜色"), field("printing", "印刷版本/唛头"),
        ]),
        template("BAG", "塑料袋", [
            field("material", "材质"), field("color", "颜色"), field("size", "长宽尺寸"),
            field("box_type", "箱子形状"), field("model", "型号"),
            field("thickness", "厚度"), field("bag_type", "袋型/封口方式"), field("printing", "印刷版本"),
        ]),
        template("PACKAGING_GENERAL", "通用包材", [
            field("material", "材质"), field("color", "颜色"), field("specification", "规格"),
            field("box_type", "箱子形状"), field("model", "型号"),
        ]),
    ]},
    {"key": "AUXILIARY", "label": "辅料", "templates": [
        template("TAPE", "带类", [
            field("material", "材质"), field("color", "颜色"), field("width", "宽度"), field("thickness", "厚度"),
            field("specification", "规格描述"),
        ]),
        template("COTTON", "棉类", [
            field("material", "材质"), field("color", "颜色"), field("thickness", "厚度"),
            field("gram_weight", "克重"), field("width", "幅宽"),
            field("specification", "规格描述"),
        ]),
        template("AUXILIARY_GENERAL", "通用辅料", [
            field("material", "材质"), field("color", "颜色"), field("specification", "规格"),
        ]),
    ]},
    {"key": "FABRIC_SEMI", "label": "委外布面", "templates": [template("FABRIC_SEMI", "委外布面", [
        field("material", "材质"), field("color", "颜色"), field("fabric_spec", "面料规格"),
        field("width", "门幅"),
        field("size", "加工后尺寸"), field("model", "款号/图号"), field("process", "加工做法/工艺版本"),
        field("specification", "规格描述"),
    ])]},
]

SPRAY_FIELDS = [field("color", "颜色"), field("length", "长度"), field("unit", "可用单位", "unit")]
CATEGORY_CHOICES = [(item["key"], item["label"]) for item in CATEGORIES]
TEMPLATES = {item["key"]: item for category in CATEGORIES for item in category["templates"]}
TEMPLATE_CHOICES = [(key, item["label"]) for key, item in TEMPLATES.items()]
CATEGORY_TEMPLATES = {item["key"]: {row["key"] for row in item["templates"]} for item in CATEGORIES}
