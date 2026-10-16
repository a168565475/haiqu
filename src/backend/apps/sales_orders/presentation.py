import re


def specification_display(line):
    """仅剥离已由独立字段证实的旧拼接尾缀，不改变业务快照。"""
    text = getattr(line, "customer_specification_snapshot", "") or line.specification_snapshot or ""
    color = (getattr(line, "customer_color_snapshot", "") or getattr(line, "color_snapshot", "")
             or getattr(getattr(line, "product_color", None), "color_name", ""))
    known = {"颜色": color.strip(), "材质": (line.material_snapshot or "").strip()}
    while match := re.search(r"[；;]\s*(颜色|材质)\s*[:：]\s*([^；;]*)$", text):
        value = known[match[1]]
        if not value or match[2].strip() != value:
            break
        text = text[:match.start()].rstrip()
    return text
