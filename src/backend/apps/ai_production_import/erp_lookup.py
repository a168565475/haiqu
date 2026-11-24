"""生产助手的有界只读工具；使用当前请求的身份及现行业务读取权限。"""
import json
from contextlib import contextmanager
from copy import deepcopy
from unicodedata import normalize
from uuid import UUID

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.boms.models import BomLine
from apps.boms.selectors import accessible_boms, search_boms
from apps.material_catalog.definitions import CATEGORIES, SPRAY_FIELDS, TEMPLATES
from apps.material_catalog.selectors import catalog_detail, catalog_list, catalog_summary
from apps.production_tasks.selectors import accessible_production_tasks
from apps.workshop_config.models import Craft


MAX_RESPONSE_BYTES = 200_000
HISTORY_NOTICE = "历史资料仅供品名、材料属性和工艺对应参考；本次任务、数量、尺寸及要求以当前上传来源为准，不得用历史值覆盖。"
CATEGORY_KEYS = [category["key"] for category in CATEGORIES]
ATTRIBUTE_KEYS = {field["key"] for template in TEMPLATES.values() for field in template["fields"]}
OPTION_KEYS = ("id", "field_key", "value", "parent_id", "product_color_id", "color_card", "color_code", "color_name")


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _function(name, description, properties):
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": _object(properties)}


QUERY = {"type": "string", "minLength": 1, "maxLength": 100}
DEFINITIONS = [
    _function("search_erp_materials", "批量搜索当前账号可读的真实材料品名；先搜品名，再取详情核对属性。category为空表示不限类别。", {
        "queries": {"type": "array", "minItems": 1, "maxItems": 12, "items": _object({
            "query": QUERY, "category": {"type": "string", "enum": ["", *CATEGORY_KEYS]},
        })},
    }),
    _function("get_erp_materials", "查询每个品名的单位及必填字段。options_ref引用本品名的基础属性；启用喷塑的管材或五金另有spray_options_ref引用本品名的喷塑色。每个引用的元数据仅首次返回，通过search_erp_attributes按需查询属性值。", {
        "catalog_ids": {"type": "array", "minItems": 1, "maxItems": 12,
                        "items": {"type": "string", "format": "uuid"}},
    }),
    _function("search_erp_attributes", "按已读取品名及属性组的options_ref与field_key批量查询候选。每项最多20条，完全匹配优先；空query用于小枚举，has_more时须缩小查询。支持大小写、空白、乘号规范匹配，不作单位换算。", {
        "queries": {"type": "array", "minItems": 1, "maxItems": 12, "items": _object({
            "options_ref": {"type": "string", "minLength": 1, "maxLength": 100},
            "field_key": {"type": "string", "minLength": 1, "maxLength": 100},
            "query": {"type": "string", "maxLength": 100},
        })},
    }),
    _function("search_production_history", "只读搜索可见历史生产任务及BOM，按任务号、产品品名或编号查找；历史数量不得覆盖本单。", {
        "query": QUERY, "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    }),
    _function("get_bom_history", "读取有权限查看的旧BOM材料属性快照及来源行，最多150行；只作对应参考，不沿用旧任务数量。", {
        "bom_id": {"type": "string", "format": "uuid"},
    }),
    _function("get_production_crafts", "查询现行可选裁剪、车缝、绣花、丝印工艺；query为空列出前100项。", {
        "query": {"type": "string", "maxLength": 100},
    }),
]


class LookupRejected(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(detail)


def _view(kind, action):
    # 延迟导入避免 AI 导入客户端与业务 ViewSet 的服务层形成循环依赖。
    if kind == "materials":
        from apps.material_catalog.api.views import MaterialCatalogViewSet
        view = MaterialCatalogViewSet()
    elif kind == "tasks":
        from apps.production_tasks.api.views import ProductionTaskViewSet
        view = ProductionTaskViewSet()
    else:
        from apps.boms.api.views import BomViewSet
        view = BomViewSet()
    view.action = action
    return view


def _keys(arguments, expected):
    if not isinstance(arguments, dict) or set(arguments) != set(expected):
        raise LookupRejected("INVALID_ARGUMENTS", "参数必须完整且不能包含额外字段。")


def _query(value, *, allow_empty=False):
    if not isinstance(value, str) or len(value) > 100 or "\x00" in value or (not allow_empty and not value.strip()):
        raise LookupRejected("INVALID_ARGUMENTS", "搜索文字须为0至100字。" if allow_empty else "搜索文字须为1至100字。")
    return value.strip()


def _uuid(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except ValueError as error:
        raise LookupRejected("INVALID_ARGUMENTS", "标识须为有效UUID。") from error


def _batch(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise LookupRejected("INVALID_ARGUMENTS", "每次须提供1至12项。")
    return value


def _required_fields(template_key):
    from apps.boms.catalog_selection import required_fields
    try:
        return {"all": list(required_fields(template_key, {}, require_tube_length=False)), "any": []}
    except ValidationError:
        alternatives = []
        for field in TEMPLATES[template_key]["fields"]:
            key = field["key"]
            try:
                required_fields(template_key, {key: "明确值"}, require_tube_length=False)
            except ValidationError:
                continue
            alternatives.append(key)
        return {"all": [], "any": alternatives}


def _selection(snapshot):
    """只输出材料身份白名单，不外发任意历史 metadata、价格或联系信息。"""
    if not isinstance(snapshot, dict):
        return {}
    scalar_keys = ("catalog_id", "catalog_version", "category_key", "template_key", "name", "scope",
                   "processing_state", "semi_kind", "unit_id", "unit_name", "product_color_id",
                   "color_card", "color_code", "color_name")
    result = {key: snapshot[key] for key in scalar_keys if key in snapshot and isinstance(snapshot[key], (str, type(None)))}
    attributes = snapshot.get("attributes", {})
    result["attributes"] = {key: value for key, value in attributes.items()
                            if key in ATTRIBUTE_KEYS and isinstance(value, str)} if isinstance(attributes, dict) else {}
    craft = snapshot.get("completed_craft")
    if isinstance(craft, dict):
        result["completed_craft"] = {key: craft[key] for key in ("id", "craft_type", "code")
                                     if key in craft and isinstance(craft[key], str)}
    return result


def _template_options(options):
    return {
        "values": [],
        "fields": [{key: row[key] for key in ("key", "label", "kind") if key in row}
                   for row in options.get("fields", [])],
        "units": [{key: row[key] for key in ("id", "unit_name") if key in row} for row in options.get("units", [])],
    }


def _catalog_options(catalog, detail, scope):
    return {
        "fields": SPRAY_FIELDS if scope == "SPRAY" else TEMPLATES[catalog.template_key]["fields"],
        "values": [row for row in detail["values"] if row["scope"] == scope and row.get("selectable", True)
                   and row["value"].strip() not in {"", "/", "-", "—"}],
        "units": [{"id": row["unit_id"], "unit_name": row["unit_name"]} for row in detail["units"]
                  if row["scope"] == scope and row.get("selectable", True)],
    }


def _attribute_text(value):
    return "".join(normalize("NFKC", value).casefold().split()).translate(str.maketrans({"×": "x", "*": "x", "✕": "x"}))


def _option_identity(row):
    # 同一直径可关联多个形状，不能只按 ID 合并而丢掉 parent_id。
    return tuple(row.get(key) for key in ("field_key", "id", "parent_id", "product_color_id"))


def _bom_summary(bom):
    return {"id": str(bom.pk), "bom_number": bom.bom_number, "version_number": bom.version_number,
            "task_id": str(bom.production_task_id), "task_number": bom.production_task.task_number,
            "product_name": bom.product_name_snapshot, "product_code": bom.product_code_snapshot,
            "specification": bom.specification_snapshot, "status": bom.status,
            "updated_at": bom.updated_at.isoformat()}


class ProductionAssistantTools:
    def __init__(self, request):
        self.request = request
        self.definitions = deepcopy(DEFINITIONS)
        self.catalog_details = {}
        self.crafts = {}
        self.audit = []
        self._sent_templates = set()
        self._template_options = {}
        self._full_template_options = {}

    @contextmanager
    def _read_context(self, kind, action="list"):
        request = self.request
        if request is None or not getattr(getattr(request, "user", None), "is_authenticated", False):
            raise LookupRejected("FORBIDDEN", "需要当前登录账号和有效员工身份。")
        view = _view(kind, action)
        view.request = request
        previous = request.parser_context
        # 范围选择器会读取当前视图action；必须使用实际业务读取上下文，不能继承导入写操作。
        request.parser_context = {**(previous or {}), "view": view}
        try:
            if not all(permission.has_permission(request, view) for permission in view.get_permissions()):
                raise LookupRejected("FORBIDDEN", "当前账号没有此资料的读取权限。")
            yield
        finally:
            request.parser_context = previous

    def execute(self, name, arguments):
        known = isinstance(name, str) and name in {item["name"] for item in DEFINITIONS}
        audit = {"tool": name if known else "unknown",
                 "argument_count": len(arguments) if isinstance(arguments, dict) else 0,
                 "status": "INTERNAL_ERROR", "response_bytes": 0, "result_count": 0}
        self._pending_catalogs, self._pending_crafts, self._pending_templates = {}, {}, {}
        self._pending_full_templates, self._pending_values = {}, {}
        try:
            if not known:
                raise LookupRejected("UNKNOWN_TOOL", "不支持此查询工具。")
            result = getattr(self, f"_{name}")(arguments)
            size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if size > MAX_RESPONSE_BYTES:
                raise LookupRejected("RESULT_TOO_LARGE", "查询结果过大，请减少查询项或缩小范围；本次未缓存未返回的候选。")
            self.catalog_details.update(self._pending_catalogs)
            self.crafts.update(self._pending_crafts)
            self._template_options.update(self._pending_templates)
            self._full_template_options.update(self._pending_full_templates)
            self._sent_templates.update(self._pending_templates)
            for reference, returned in self._pending_values.items():
                options = self._template_options[reference]
                visible = {_option_identity(row): row for row in options["values"]}
                visible.update(returned)
                # 每份品名和属性组只认可本轮已成功返回的候选。
                options["values"] = list(visible.values())
            audit.update(status="OK", response_bytes=size,
                         result_count=sum(len(result.get(key, [])) for key in ("results", "materials", "tasks", "boms", "lines", "crafts")))
            return result
        except LookupRejected as error:
            audit["status"] = error.code
            return {"error": error.code, "detail": error.detail}
        finally:
            # 内部异常继续抛出，只保留不含搜索词、原文、密钥的执行摘要。
            self.audit.append(audit)
            self._pending_catalogs, self._pending_crafts, self._pending_templates = {}, {}, {}
            self._pending_full_templates, self._pending_values = {}, {}

    def _search_erp_materials(self, arguments):
        _keys(arguments, ("queries",))
        queries = []
        for item in _batch(arguments["queries"]):
            _keys(item, ("query", "category"))
            if not isinstance(item["category"], str) or item["category"] not in ["", *CATEGORY_KEYS]:
                raise LookupRejected("INVALID_ARGUMENTS", "材料类别不正确。")
            queries.append((_query(item["query"]), item["category"]))
        with self._read_context("materials"):
            results = []
            for query, category in queries:
                rows = list(catalog_list(category=category, query=query)[:21])
                results.append({"query": query, "category": category,
                                "materials": [catalog_summary(row) for row in rows[:20]], "has_more": len(rows) > 20})
        return {"results": results}

    def _get_erp_materials(self, arguments):
        _keys(arguments, ("catalog_ids",))
        ids = list(dict.fromkeys(_uuid(value) for value in _batch(arguments["catalog_ids"])))
        with self._read_context("materials", "retrieve"):
            catalogs = list(catalog_list().filter(pk__in=ids))
            results = []
            for catalog in catalogs:
                detail = catalog_detail(catalog)
                scopes = ["BASE"]
                if catalog.spray_enabled and catalog.category_key in {"TUBE", "HARDWARE"}:
                    scopes.append("SPRAY")
                scoped_options = {}
                for scope in scopes:
                    reference = f"{catalog.pk}/{scope}/{catalog.updated_at.isoformat()}"
                    if reference in self._template_options:
                        options = self._template_options[reference]
                    elif reference in self._pending_templates:
                        options = self._pending_templates[reference]
                    else:
                        full_options = _catalog_options(catalog, detail, scope)
                        self._pending_full_templates[reference] = full_options
                        options = {**deepcopy(full_options), "values": []}
                        self._pending_templates[reference] = options
                    scoped_options[scope] = (reference, options)
                reference, options = scoped_options["BASE"]
                spray_reference, spray_options = scoped_options.get("SPRAY", (None, None))
                required = _required_fields(catalog.template_key)
                item = {"catalog": deepcopy(detail), "options": options, "spray_options": spray_options,
                        "required_fields": required}
                results.append({"catalog": {**catalog_summary(catalog), "units": [row for row in detail["units"] if row.get("selectable", True)]},
                                "options_ref": reference, "spray_options_ref": spray_reference, "required_fields": required})
                self._pending_catalogs[str(catalog.pk)] = item
            templates = [{"options_ref": reference, "options": _template_options(options)}
                         for reference, options in self._pending_templates.items() if reference not in self._sent_templates]
        return {"materials": results, "templates": templates,
                "not_found": [key for key in ids if key not in self._pending_catalogs]}

    def _search_erp_attributes(self, arguments):
        _keys(arguments, ("queries",))
        queries = []
        for item in _batch(arguments["queries"]):
            _keys(item, ("options_ref", "field_key", "query"))
            reference, field = item["options_ref"], item["field_key"]
            if not isinstance(reference, str) or reference not in self._sent_templates:
                raise LookupRejected("UNKNOWN_OPTIONS_REF", "请先读取当前品名与属性组的详情，再查询属性。")
            options = self._full_template_options[reference]
            fields = {row["key"] for row in options["fields"] if row["kind"] != "unit"}
            if not isinstance(field, str) or field not in fields:
                raise LookupRejected("INVALID_ARGUMENTS", "属性须为该模板的非单位字段；单位请使用材料详情中的 units。")
            queries.append((reference, field, _query(item["query"], allow_empty=True)))
        with self._read_context("materials", "retrieve"):
            results = []
            for reference, field, query in queries:
                needle = _attribute_text(query)
                matches = []
                for row in self._full_template_options[reference]["values"]:
                    if row["field_key"] != field:
                        continue
                    texts = [_attribute_text(row[key]) for key in ("value", "color_card", "color_code", "color_name")
                             if isinstance(row.get(key), str) and row[key]]
                    if not needle or any(needle in text for text in texts):
                        matches.append((needle not in texts, row))
                matches.sort(key=lambda match: (match[0], _attribute_text(match[1]["value"]),
                                                str(match[1]["id"]), str(match[1].get("parent_id") or "")))
                values = [{key: row[key] for key in OPTION_KEYS if key in row} for _, row in matches[:20]]
                results.append({"options_ref": reference, "field_key": field, "query": query,
                                "values": values, "has_more": len(matches) > 20})
                self._pending_values.setdefault(reference, {}).update(
                    {_option_identity(row): deepcopy(row) for row in values})
        return {"results": results}

    def _search_production_history(self, arguments):
        _keys(arguments, ("query", "limit"))
        query, limit = _query(arguments["query"]), arguments["limit"]
        if type(limit) is not int or not 1 <= limit <= 10:
            raise LookupRejected("INVALID_ARGUMENTS", "历史查询条数须为1至10。")
        result = {"tasks": [], "boms": [], "tasks_has_more": False, "boms_has_more": False,
                  "restricted": [], "notice": HISTORY_NOTICE}
        try:
            with self._read_context("tasks"):
                rows = list(accessible_production_tasks(self.request, permission="production_tasks.view_productiontask").filter(
                    archived_at__isnull=True).filter(Q(task_number__icontains=query)
                    | Q(products__product_name_snapshot__icontains=query) | Q(products__product_code_snapshot__icontains=query)
                    | Q(products__item_number_snapshot__icontains=query)).distinct().order_by("-updated_at", "-id")[:limit + 1])
                for task in rows[:limit]:
                    products = list(task.products.order_by("line_number", "id").values(
                        "product_name_snapshot", "product_code_snapshot", "specification_snapshot")[:11])
                    result["tasks"].append({"id": str(task.pk), "task_number": task.task_number, "status": task.status,
                                            "products": products[:10], "products_has_more": len(products) > 10,
                                            "updated_at": task.updated_at.isoformat()})
                result["tasks_has_more"] = len(rows) > limit
        except LookupRejected as error:
            if error.code != "FORBIDDEN":
                raise
            result["restricted"].append("production_tasks")
        try:
            with self._read_context("boms"):
                rows = list(search_boms(accessible_boms(self.request), query).select_related("production_task").order_by(
                    "-updated_at", "-id")[:limit + 1])
                result["boms"] = [_bom_summary(bom) for bom in rows[:limit]]
                result["boms_has_more"] = len(rows) > limit
        except LookupRejected as error:
            if error.code != "FORBIDDEN":
                raise
            result["restricted"].append("boms")
        if len(result["restricted"]) == 2:
            raise LookupRejected("FORBIDDEN", "当前账号没有历史生产任务或BOM的读取权限。")
        return result

    def _get_bom_history(self, arguments):
        _keys(arguments, ("bom_id",))
        bom_id = _uuid(arguments["bom_id"])
        with self._read_context("boms", "retrieve"):
            bom = accessible_boms(self.request).select_related("production_task").filter(pk=bom_id).first()
            if bom is None:
                raise LookupRejected("NOT_FOUND", "BOM不存在或不在当前账号可见范围。")
            rows = list(BomLine.objects.filter(section__bom=bom).select_related("section").order_by(
                "section__line_number", "line_number", "id")[:151])
            fields = ("part_name", "material", "specification", "raw_material", "unit", "length_value",
                      "unit_consumption", "hardness", "original_material_length", "component_kind")
            lines = []
            for row in rows[:150]:
                lines.append({"id": str(row.pk), "section": row.section.title, "line_number": row.line_number,
                              **{key: getattr(row, key) for key in fields},
                              "material_catalog_id": str(row.material_catalog_id) if row.material_catalog_id else None,
                              "material_selection_snapshot": _selection(row.material_selection_snapshot),
                              "fabric_source_line_id": str(row.fabric_source_line_id) if row.fabric_source_line_id else None,
                              "source": {"sheet": bom.source_sheet_name, "row": row.source_row_number}})
            return {"bom": _bom_summary(bom), "lines": lines, "has_more": len(rows) > 150, "notice": HISTORY_NOTICE}

    def _get_production_crafts(self, arguments):
        _keys(arguments, ("query",))
        query = _query(arguments["query"], allow_empty=True)
        with self._read_context("boms", "material_selection_options"):
            rows = Craft.objects.filter(status="ACTIVE").filter(
                Q(craft_type="INTERNAL", plan_category__in=["CUTTING", "SEWING"])
                | Q(craft_type="EXTERNAL", outsourcing_code__in=["CUTTING", "SEWING", "EMBROIDERY", "SCREEN_PRINTING"]))
            if query:
                rows = rows.filter(name__icontains=query)
            rows = list(rows.order_by("craft_type", "name", "id")[:101])
            crafts = [{"id": str(row.pk), "name": row.name, "craft_type": row.craft_type,
                       "code": row.plan_category if row.craft_type == "INTERNAL" else row.outsourcing_code} for row in rows[:100]]
            self._pending_crafts.update({row["id"]: deepcopy(row) for row in crafts})
            return {"crafts": crafts, "has_more": len(rows) > 100}
