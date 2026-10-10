# 标准基础资料快照

本目录中的 JSON 文件是数据库迁移使用的离线、版本化资源。生产迁移不得联网下载数据。

- `countries_un_m49_2026-08-26.json`：联合国统计司 M49 中公开的 ISO Alpha-2、Alpha-3、数字码及中英文名称。M49 不单列 `TW`，该条按 ISO 3166-1 / UNECE Recommendation 3 补齐，中文短显示名来自 Unicode CLDR 48.2。
- `currencies_iso4217_2026-01-01.json`：SIX Group 作为 ISO 4217 维护机构发布的 List One。中文显示名和符号来自 Unicode CLDR 48.2，不改变 SIX 的代码、数字码和小数位。
- `incoterms_2020.json`：ICC Incoterms 2020 的 11 个代码及运输范围。中文名称仅用于系统显示，不替代 ICC 正式规则文本。

原始网页或 XML 只用于人工刷新快照，不随项目发布。刷新时运行：

```powershell
python build_standard_snapshots.py --m49-html <m49页面文件> --iso4217-xml <list-one.xml> --cldr-zh <zh.xml> --output-dir .
```

生成器会校验国家数量和重复币种的一致性，并在快照元数据中记录原始文件 SHA-256。
