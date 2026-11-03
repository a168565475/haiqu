"""受控 XLSX 预处理：只读包内来源，不执行公式或访问外链。调用方必须先完成病毒扫描。"""

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
from urllib.parse import unquote, urlsplit
import warnings
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image


MIB = 1024 * 1024
LIMITS = {
    "file_bytes": 25 * MIB,
    "zip_entries": 2000,
    "expanded_bytes": 128 * MIB,
    "entry_bytes": 32 * MIB,
    "compression_ratio": 200,
    "sheets": 50,
    "cells": 100000,
    "images": 100,
    "image_bytes": 10 * MIB,
    "image_pixels": 20000000,
    "total_pixels": 100000000,
    "text_characters": 20000,
    "manifest_bytes": 2 * MIB,
}
NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
}
DISPIMG = re.compile(r'(?:_xlfn\.)?DISPIMG\(\s*"([^"]+)"', re.IGNORECASE)


class ManifestError(ValueError):
    """仅接受脚本内固定错误码，不携带不可信来源原文。"""


class NoDTD(ET.TreeBuilder):
    def doctype(self, name, public_id, system_id):
        raise ManifestError("XML_DTD_FORBIDDEN")


def parse_xml(data):
    # 使用解析器回调拒绝 DTD，避免 UTF-16 等编码绕过字节字符串检查。
    return ET.fromstring(data, parser=ET.XMLParser(target=NoDTD()))


def validate_package(archive):
    entries = archive.infolist()
    if len(entries) > LIMITS["zip_entries"]:
        raise ManifestError("ZIP_ENTRY_LIMIT")
    names = set()
    members = {}
    expanded = 0
    for entry in entries:
        name = entry.filename
        parts = PurePosixPath(name).parts
        if (not name or "\\" in name or "\x00" in name or ":" in name
                or name.startswith("/") or ".." in parts
                or posixpath.normpath(name) != name.rstrip("/")):
            raise ManifestError("ZIP_UNSAFE_PATH")
        if name.casefold() in names:
            raise ManifestError("ZIP_DUPLICATE_PATH")
        names.add(name.casefold())
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ManifestError("ZIP_SYMLINK_FORBIDDEN")
        if entry.flag_bits & 1:
            raise ManifestError("ZIP_ENCRYPTED_FORBIDDEN")
        if entry.is_dir():
            continue
        if (entry.file_size > LIMITS["entry_bytes"]
                or entry.file_size / max(entry.compress_size, 1) > LIMITS["compression_ratio"]):
            raise ManifestError("ZIP_ENTRY_EXPANSION_LIMIT")
        if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ManifestError("ZIP_COMPRESSION_UNSUPPORTED")
        if re.search(r"vbaproject|macrosheets|xl/activex/|xl/embeddings/", name, re.I):
            raise ManifestError("ACTIVE_CONTENT_FORBIDDEN")
        chunks = []
        size = 0
        with archive.open(entry) as source:
            while chunk := source.read(65536):
                size += len(chunk)
                expanded += len(chunk)
                if size > LIMITS["entry_bytes"] or expanded > LIMITS["expanded_bytes"]:
                    raise ManifestError("ZIP_ACTUAL_EXPANSION_LIMIT")
                chunks.append(chunk)
        if size != entry.file_size:
            raise ManifestError("ZIP_DECLARED_SIZE_MISMATCH")
        members[name] = b"".join(chunks)
    return members


def resolve_part(owner, target):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in target:
        raise ManifestError("RELATIONSHIP_TARGET_UNSAFE")
    decoded = unquote(parsed.path)
    if "\x00" in decoded or "\\" in decoded or ":" in decoded:
        raise ManifestError("RELATIONSHIP_TARGET_UNSAFE")
    part = posixpath.normpath(posixpath.join(posixpath.dirname(owner), decoded))
    if decoded.startswith("/"):
        part = posixpath.normpath(decoded.lstrip("/"))
    if part in ("", ".", "..") or part.startswith("../"):
        raise ManifestError("RELATIONSHIP_ESCAPES_PACKAGE")
    return part


def read_relationships(documents, members):
    relationships = {}
    for part, root in documents.items():
        if not part.endswith(".rels"):
            continue
        if part == "_rels/.rels":
            owner = ""
        else:
            directory, filename = posixpath.split(part)
            if posixpath.basename(directory) != "_rels":
                raise ManifestError("RELATIONSHIP_PART_INVALID")
            owner = posixpath.join(posixpath.dirname(directory), filename[:-5])
        mapped = {}
        for node in root:
            identifier, target = node.get("Id"), node.get("Target")
            if not identifier or target is None or identifier in mapped:
                raise ManifestError("RELATIONSHIP_ID_INVALID")
            item = {"id": identifier, "type": node.get("Type"), "part": part}
            if node.get("TargetMode") == "External":
                # 外部地址可能包含个人信息或凭据，只登记摘要，不请求目标。
                item.update(external=True, target_sha256=hashlib.sha256(target.encode()).hexdigest())
            else:
                resolved = resolve_part(owner, target)
                if resolved not in members:
                    raise ManifestError("RELATIONSHIP_INTERNAL_TARGET_MISSING")
                item.update(external=False, target=resolved)
            mapped[identifier] = item
        relationships[owner] = mapped
    return relationships


def read_images(members):
    media = [(part, data) for part, data in sorted(members.items()) if part.startswith("xl/media/")]
    if len(media) > LIMITS["images"]:
        raise ManifestError("IMAGE_COUNT_LIMIT")
    results = []
    total_pixels = 0
    for index, (part, data) in enumerate(media, 1):
        if len(data) > LIMITS["image_bytes"]:
            raise ManifestError("IMAGE_BYTE_LIMIT")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG"):
                    raise ManifestError("IMAGE_FORMAT_UNSUPPORTED")
                expected = {"PNG": {".png"}, "JPEG": {".jpg", ".jpeg"}}[image.format]
                if PurePosixPath(part).suffix.lower() not in expected:
                    raise ManifestError("IMAGE_EXTENSION_MISMATCH")
                pixels = image.width * image.height
                total_pixels += pixels
                if pixels > LIMITS["image_pixels"] or total_pixels > LIMITS["total_pixels"]:
                    raise ManifestError("IMAGE_PIXEL_LIMIT")
                if getattr(image, "n_frames", 1) != 1:
                    raise ManifestError("ANIMATED_IMAGE_UNSUPPORTED")
                image.load()
                results.append({
                    "id": f"image_{index:03d}", "part": part, "format": image.format,
                    "width": image.width, "height": image.height, "pixels": pixels,
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "output": f"images/image_{index:03d}{'.png' if image.format == 'PNG' else '.jpg'}",
                })
    return results


def all_text(node):
    return "".join(item.text or "" for item in node.iter(f"{{{NS['s']}}}t"))


def picture_reference(picture, owner, relationships, media_ids):
    properties = picture.find(".//xdr:cNvPr", NS)
    blip = picture.find(".//a:blip", NS)
    result = {"name": properties.get("name") if properties is not None else None, "owner": owner}
    for kind in ("embed", "link"):
        identifier = blip.get(f"{{{NS['r']}}}{kind}") if blip is not None else None
        relation = relationships.get(owner, {}).get(identifier) if identifier else None
        if identifier and relation is None:
            raise ManifestError("IMAGE_RELATIONSHIP_MISSING")
        result[kind] = relation
        if relation and not relation["external"]:
            if relation["target"] not in media_ids:
                raise ManifestError("IMAGE_RELATIONSHIP_NOT_MEDIA")
            result[f"{kind}_image_id"] = media_ids[relation["target"]]
    return result


def read_workbook(members, documents, relationships, images):
    workbook = documents.get("xl/workbook.xml")
    content_types = documents.get("[Content_Types].xml")
    if workbook is None or content_types is None:
        raise ManifestError("XLSX_WORKBOOK_MISSING")
    expected = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    if not any(node.get("PartName") == "/xl/workbook.xml" and node.get("ContentType") == expected
               for node in content_types):
        raise ManifestError("XLSX_CONTENT_TYPE_INVALID")
    shared_root = documents.get("xl/sharedStrings.xml")
    shared = [all_text(node) for node in shared_root] if shared_root is not None else []
    styles = documents.get("xl/styles.xml")
    formats = {node.get("numFmtId"): node.get("formatCode") for node in
               styles.findall("s:numFmts/s:numFmt", NS)} if styles is not None else {}
    cell_styles = styles.findall("s:cellXfs/s:xf", NS) if styles is not None else []
    media_ids = {image["part"]: image["id"] for image in images}
    cell_images = {}
    cell_image_root = documents.get("xl/cellimages.xml")
    if cell_image_root is not None:
        for picture in cell_image_root.findall(".//xdr:pic", NS):
            item = picture_reference(picture, "xl/cellimages.xml", relationships, media_ids)
            if not item["name"] or item["name"] in cell_images:
                raise ManifestError("CELL_IMAGE_ID_INVALID")
            cell_images[item["name"]] = item
    nodes = workbook.findall("s:sheets/s:sheet", NS)
    if len(nodes) > LIMITS["sheets"]:
        raise ManifestError("SHEET_COUNT_LIMIT")
    sheets = []
    nonempty = 0
    for sheet in nodes:
        relation = relationships.get("xl/workbook.xml", {}).get(sheet.get(f"{{{NS['r']}}}id"))
        if not relation or relation["external"] or not relation.get("type", "").endswith("/worksheet"):
            raise ManifestError("SHEET_RELATIONSHIP_INVALID")
        part = relation["target"]
        root = documents[part]
        if root.tag != f"{{{NS['s']}}}worksheet":
            raise ManifestError("WORKSHEET_XML_INVALID")
        cells = []
        for cell in root.findall("s:sheetData/s:row/s:c", NS):
            value, inline, formula = (cell.find(f"s:{key}", NS) for key in ("v", "is", "f"))
            if value is None and inline is None and formula is None:
                continue
            nonempty += 1
            if nonempty > LIMITS["cells"]:
                raise ManifestError("CELL_COUNT_LIMIT")
            raw = value.text if value is not None else None
            text = raw
            if cell.get("t") == "s":
                if raw is None or not raw.isdigit() or int(raw) >= len(shared):
                    raise ManifestError("SHARED_STRING_INDEX_INVALID")
                text = shared[int(raw)]
            elif inline is not None:
                text = all_text(inline)
            formula_text = formula.text if formula is not None else None
            if any(len(item) > LIMITS["text_characters"] for item in (text, formula_text) if item):
                raise ManifestError("SOURCE_TEXT_LIMIT")
            style_id = int(cell.get("s", "0"))
            if style_id < 0 or (cell_styles and style_id >= len(cell_styles)):
                raise ManifestError("CELL_STYLE_INVALID")
            number_format = cell_styles[style_id].get("numFmtId") if cell_styles else None
            item = {
                "ref": cell.get("r"), "type": cell.get("t", "n"), "raw_v": raw, "text": text,
                "formula": formula_text, "formula_attributes": dict(formula.attrib) if formula is not None else None,
                "cache": raw if formula is not None else None,
                "style": style_id, "num_format_id": number_format, "num_format": formats.get(number_format),
            }
            if formula_text and "DISPIMG" in formula_text.upper():
                match = DISPIMG.search(formula_text)
                identifier = match.group(1) if match else None
                picture = cell_images.get(identifier)
                resolved = bool(picture and (picture.get("embed_image_id") or picture.get("link_image_id")))
                item["dispimg"] = {"id": identifier, "picture": picture, "resolved": resolved}
            cells.append(item)
        pictures = []
        for drawing in root.findall("s:drawing", NS):
            drawing_relation = relationships.get(part, {}).get(drawing.get(f"{{{NS['r']}}}id"))
            if not drawing_relation or drawing_relation["external"]:
                raise ManifestError("DRAWING_RELATIONSHIP_INVALID")
            drawing_part = drawing_relation["target"]
            for anchor in documents[drawing_part]:
                for picture in anchor.findall(".//xdr:pic", NS):
                    item = picture_reference(picture, drawing_part, relationships, media_ids)
                    item["anchor_type"] = anchor.tag.rsplit("}", 1)[-1]
                    for end in ("from", "to"):
                        marker = anchor.find(f"xdr:{end}", NS)
                        item[end] = {node.tag.rsplit("}", 1)[-1]: int(node.text) for node in marker} if marker is not None else None
                    for end in ("pos", "ext"):
                        marker = anchor.find(f"xdr:{end}", NS)
                        item[end] = dict(marker.attrib) if marker is not None else None
                    pictures.append(item)
        comments = []
        for comment_relation in relationships.get(part, {}).values():
            if not comment_relation["external"] and comment_relation["type"].endswith("/comments"):
                comment_part = comment_relation["target"]
                for comment in documents[comment_part].findall("s:commentList/s:comment", NS):
                    text = all_text(comment)
                    if len(text) > LIMITS["text_characters"]:
                        raise ManifestError("COMMENT_TEXT_LIMIT")
                    comments.append({"ref": comment.get("ref"), "text": text, "part": comment_part})
        dimension = root.find("s:dimension", NS)
        sheets.append({"name": sheet.get("name"), "state": sheet.get("state", "visible"), "part": part,
                       "dimension": dimension.get("ref") if dimension is not None else None,
                       "merged_cells": [node.get("ref") for node in root.findall("s:mergeCells/s:mergeCell", NS)],
                       "cells": cells, "pictures": pictures, "comments": comments})
    properties = workbook.find("s:workbookPr", NS)
    return {"date1904": properties.get("date1904", "0") if properties is not None else "0",
            "sheets": sheets, "cell_images": cell_images}


def assign_source_ids(manifest):
    index = {}

    def register(item, kind, **location):
        locator = {"kind": kind, **location}
        key = json.dumps([manifest["source_sha256"], locator], sort_keys=True, separators=(",", ":"))
        source_id = "src_" + hashlib.sha256(key.encode("utf-8")).hexdigest()
        if source_id in index:
            raise ManifestError("SOURCE_LOCATOR_DUPLICATE")
        item["source_id"] = source_id
        index[source_id] = locator

    for sheet in manifest["sheets"]:
        register(sheet, "sheet_title", sheet_part=sheet["part"])
        for cell in sheet["cells"]:
            register(cell, "cell", sheet_part=sheet["part"], ref=cell["ref"])
            if "dispimg" in cell:
                register(cell["dispimg"], "dispimg_reference", sheet_part=sheet["part"], ref=cell["ref"])
        for position, picture in enumerate(sheet["pictures"]):
            register(picture, "drawing_picture", sheet_part=sheet["part"],
                     part=picture["owner"], picture_index=position)
        for position, comment in enumerate(sheet["comments"]):
            register(comment, "comment", sheet_part=sheet["part"], part=comment["part"],
                     ref=comment["ref"], comment_index=position)
    for image in manifest["images"]:
        register(image, "image_asset", part=image["part"])
    for identifier, picture in manifest["cell_images"].items():
        register(picture, "cell_image", part=picture["owner"], image_key=identifier)
    for relation in manifest["external_relationships"]:
        register(relation, "external_relationship", part=relation["part"], relationship_id=relation["id"])
    manifest["source_index"] = index


def encode_manifest(manifest):
    result = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
    for chunk in encoder.iterencode(manifest):
        encoded = chunk.encode("utf-8")
        if len(result) + len(encoded) > LIMITS["manifest_bytes"]:
            raise ManifestError("MANIFEST_SIZE_LIMIT")
        result.extend(encoded)
    return bytes(result)


def failure_record(error):
    return {"status": "failed", "error_type": type(error).__name__,
            "reason": str(error) if isinstance(error, ManifestError) else "INPUT_REJECTED"}


def build_manifest(path):
    path = Path(path)
    if path.suffix.lower() != ".xlsx" or path.name.startswith("~$"):
        raise ManifestError("INPUT_XLSX_REQUIRED")
    with path.open("rb") as source:
        data = source.read(LIMITS["file_bytes"] + 1)
    if not data or len(data) > LIMITS["file_bytes"]:
        raise ManifestError("INPUT_SIZE_LIMIT")
    if not data.startswith(b"PK\x03\x04"):
        raise ManifestError("INPUT_ZIP_SIGNATURE_INVALID")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entry_count = len(archive.infolist())
        members = validate_package(archive)
    documents = {part: parse_xml(value) for part, value in members.items()
                 if part.endswith((".xml", ".rels", ".vml"))}
    relationships = read_relationships(documents, members)
    images = read_images(members)
    workbook = read_workbook(members, documents, relationships, images)
    manifest = {"schema_version": "unit01-source-v1", "source_sha256": hashlib.sha256(data).hexdigest(),
                "source_bytes": len(data), "zip_entries": entry_count,
                "expanded_bytes": sum(map(len, members.values())), "limits": LIMITS,
                "untrusted_source": True, "formulas_evaluated": False,
                "scan_status": "NOT_PERFORMED_BY_THIS_SCRIPT", "images": images,
                "external_relationships": [rel for mapped in relationships.values() for rel in mapped.values() if rel["external"]],
                **workbook}
    assign_source_ids(manifest)
    encoded = encode_manifest(manifest)
    return manifest, encoded, members

