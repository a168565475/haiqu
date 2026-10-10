import re

from pypinyin import Style, lazy_pinyin, pinyin


_NON_SEARCH_CHARACTERS = re.compile(r"[^0-9a-z]+")


def _compact_latin(value):
    return _NON_SEARCH_CHARACTERS.sub("", str(value or "").casefold())


def build_pinyin_search(value):
    """生成仅供检索使用的全拼、分词全拼和首字母。"""

    source = str(value or "").strip()
    if not source:
        return ""

    syllable_options = [
        [token for token in (_compact_latin(item) for item in options) if token]
        for options in pinyin(source, style=Style.NORMAL, heteronym=True, strict=False)
    ]
    full_syllables = [options[0] if options else "" for options in syllable_options]
    initial_syllables = [
        _compact_latin(item)
        for item in lazy_pinyin(source, style=Style.FIRST_LETTER, strict=False)
    ]
    candidates = [
        "".join(full_syllables),
        " ".join(token for token in full_syllables if token),
        "".join(initial_syllables),
    ]

    # 管材名称中的“长”表示长度，但通用词库可能读作 zhang；同时保留两种读音便于兼容检索。
    alternate_full = list(full_syllables)
    alternate_initials = list(initial_syllables)
    has_length_alias = False
    for index, options in enumerate(syllable_options):
        if "zhang" not in options or "chang" not in options or index >= len(alternate_full):
            continue
        alternate_full[index] = "chang"
        if index < len(alternate_initials):
            alternate_initials[index] = "c"
        has_length_alias = True
    if has_length_alias:
        candidates.extend((
            "".join(alternate_full),
            " ".join(token for token in alternate_full if token),
            "".join(alternate_initials),
        ))

    return " ".join(dict.fromkeys(candidate for candidate in candidates if candidate))
