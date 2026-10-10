"""从已下载的官方源文件生成可审计、可离线迁移的基础资料快照。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


SNAPSHOT_DATE = "2026-08-26"
CLDR_VERSION = "48.2"


class M49TableParser(HTMLParser):
    TABLE_IDS = {"downloadTableEN", "downloadTableZH"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = defaultdict(list)
        self.current_table = None
        self.current_row = None
        self.current_cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") in self.TABLE_IDS:
            self.current_table = attributes["id"]
        elif self.current_table and tag == "tr":
            self.current_row = []
        elif self.current_row is not None and tag in {"td", "th"}:
            self.current_cell = []

    def handle_data(self, data):
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if self.current_cell is not None and tag in {"td", "th"}:
            self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.current_cell = None
        elif self.current_table and tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.tables[self.current_table].append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.current_table:
            self.current_table = None


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cldr_territory_names(cldr_zh_path: Path):
    root = ElementTree.parse(cldr_zh_path).getroot()
    return {
        node.get("type"): node.text
        for node in root.findall(".//localeDisplayNames/territories/territory")
        if node.get("type") and not node.get("alt") and node.text and node.text != "↑↑↑"
    }


def build_countries(m49_html_path: Path, cldr_zh_path: Path, output_dir: Path):
    parser = M49TableParser()
    parser.feed(m49_html_path.read_text(encoding="utf-8-sig"))

    english_rows = parser.tables["downloadTableEN"]
    chinese_rows = parser.tables["downloadTableZH"]
    if not english_rows or not chinese_rows:
        raise ValueError("联合国 M49 页面缺少英文或中文数据表。")

    english_by_alpha3 = {row[11]: row for row in english_rows[1:] if len(row) >= 15 and row[11]}
    chinese_by_alpha3 = {row[11]: row for row in chinese_rows[1:] if len(row) >= 15 and row[11]}
    if len(english_by_alpha3) != 248 or set(english_by_alpha3) != set(chinese_by_alpha3):
        raise ValueError("联合国 M49 国家数量或中英文代码集合异常。")

    records = []
    for english_row in english_by_alpha3.values():
        chinese_row = chinese_by_alpha3[english_row[11]]
        records.append(
            {
                "code": english_row[10],
                "alpha3_code": english_row[11],
                "numeric_code": english_row[9],
                "chinese_name": chinese_row[8],
                "english_name": english_row[8],
                "sort_order": 0,
                "extra_data": {
                    "global_code": english_row[0],
                    "region_code": english_row[2],
                    "region_name": english_row[3],
                    "subregion_code": english_row[4],
                    "subregion_name": english_row[5],
                    "intermediate_region_code": english_row[6],
                    "intermediate_region_name": english_row[7],
                    "least_developed": english_row[12].lower() == "x",
                    "land_locked_developing": english_row[13].lower() == "x",
                    "small_island_developing": english_row[14].lower() == "x",
                },
            }
        )

    # UN M49 不单列 TW；ISO 3166-1 当前集合包含 TW/TWN/158，故显式补齐并记录来源。
    territory_names = cldr_territory_names(cldr_zh_path)
    records.append(
        {
            "code": "TW",
            "alpha3_code": "TWN",
            "numeric_code": "158",
            "chinese_name": territory_names.get("TW", "台湾"),
            "english_name": "Taiwan (Province of China)",
            "sort_order": 0,
            "extra_data": {
                "m49_not_separately_listed": True,
                "supplemental_code_source": "ISO 3166-1 / UNECE Recommendation 3",
                "name_source": f"Unicode CLDR {CLDR_VERSION}",
            },
        }
    )
    records.sort(key=lambda row: row["code"])
    for sort_index, record in enumerate(records, start=1):
        record["sort_order"] = sort_index * 10

    write_json(
        output_dir / "countries_un_m49_2026-08-26.json",
        {
            "schema_version": 1,
            "source": {
                "standard": "ISO 3166-1 codes via UN M49",
                "publisher": "United Nations Statistics Division",
                "url": "https://unstats.un.org/unsd/methodology/m49/overview/",
                "snapshot_date": SNAPSHOT_DATE,
                "raw_sha256": file_sha256(m49_html_path),
                "supplemental_iso_record": {
                    "code": "TW",
                    "source": "https://unece.org/trade/cefact/unlocode-code-list-country-and-territory",
                    "display_name_source": f"Unicode CLDR {CLDR_VERSION} zh",
                },
            },
            "records": records,
        },
    )


def cldr_currency_names(cldr_zh_path: Path):
    root = ElementTree.parse(cldr_zh_path).getroot()
    result = {}
    for currency in root.findall(".//numbers/currencies/currency"):
        code = currency.get("type")
        display_name = next(
            (
                node.text
                for node in currency.findall("displayName")
                if not node.attrib and node.text and node.text != "↑↑↑"
            ),
            "",
        )
        symbol = next(
            (
                node.text
                for node in currency.findall("symbol")
                if not node.attrib and node.text and node.text != "↑↑↑"
            ),
            "",
        )
        result[code] = {"chinese_name": display_name, "symbol": symbol}
    return result


def build_currencies(iso4217_xml_path: Path, cldr_zh_path: Path, output_dir: Path):
    root = ElementTree.parse(iso4217_xml_path).getroot()
    published_date = root.attrib.get("Pblshd", "")
    localized_names = cldr_currency_names(cldr_zh_path)
    grouped = {}

    for row in root.findall("./CcyTbl/CcyNtry"):
        code = (row.findtext("Ccy") or "").strip()
        numeric_code = (row.findtext("CcyNbr") or "").strip()
        if not code or not numeric_code:
            continue
        english_name = (row.findtext("CcyNm") or "").strip()
        minor_unit_raw = (row.findtext("CcyMnrUnts") or "").strip()
        entity_name = (row.findtext("CtryNm") or "").strip()
        decimal_places = int(minor_unit_raw) if minor_unit_raw.isdigit() else 0
        if code not in grouped:
            localized = localized_names.get(code, {})
            grouped[code] = {
                "code": code,
                "numeric_code": numeric_code,
                "decimal_places": decimal_places,
                "symbol": localized.get("symbol", ""),
                "chinese_name": localized.get("chinese_name") or english_name,
                "english_name": english_name,
                "entities": [],
                "minor_unit_raw": minor_unit_raw,
            }
        current = grouped[code]
        if (
            current["numeric_code"] != numeric_code
            or current["decimal_places"] != decimal_places
            or current["english_name"] != english_name
        ):
            raise ValueError(f"ISO 4217 币种 {code} 的重复记录不一致。")
        current["entities"].append(entity_name)

    records = []
    for sort_index, code in enumerate(sorted(grouped), start=1):
        item = grouped[code]
        records.append(
            {
                "code": item["code"],
                "numeric_code": item["numeric_code"],
                "decimal_places": item["decimal_places"],
                "symbol": item["symbol"],
                "chinese_name": item["chinese_name"],
                "english_name": item["english_name"],
                "sort_order": sort_index * 10,
                "extra_data": {
                    "entities": sorted(set(item["entities"])),
                    "minor_unit_raw": item["minor_unit_raw"],
                    "name_source": f"Unicode CLDR {CLDR_VERSION}",
                },
            }
        )

    write_json(
        output_dir / "currencies_iso4217_2026-01-01.json",
        {
            "schema_version": 1,
            "source": {
                "standard": "ISO 4217 List One",
                "publisher": "SIX Group, ISO 4217 Maintenance Agency",
                "url": "https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml",
                "published_date": published_date,
                "raw_sha256": file_sha256(iso4217_xml_path),
                "display_name_source": f"Unicode CLDR {CLDR_VERSION} zh",
                "display_name_source_sha256": file_sha256(cldr_zh_path),
            },
            "records": records,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--m49-html", required=True, type=Path)
    parser.add_argument("--iso4217-xml", required=True, type=Path)
    parser.add_argument("--cldr-zh", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_countries(args.m49_html, args.cldr_zh, args.output_dir)
    build_currencies(args.iso4217_xml, args.cldr_zh, args.output_dir)


if __name__ == "__main__":
    main()
