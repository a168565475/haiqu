# 2026-10-15 首批兑人民币汇率

本批是公开参考报价的一次性快照，写入既有“系统配置 → 基础资料 → 汇率”模块。没有定时任务、联网更新或全局本位币变更。

## 来源与口径

- 优先使用 [CFETS 中国外汇交易中心，经 Frankfurter 提供](https://frankfurter.dev/providers/cfets/) 的外币兑人民币直接报价，共 25 个币种。
- 其他币种使用 [Frankfurter v2 公开参考汇率](https://frankfurter.dev/) 返回的 CNY 报价，按 `1 / 报价` 换成“1 外币 = X 人民币”，Decimal 四舍五入保留 8 位。每条记录保留实际报价日期、来源版本和查询 URL，不把旧报价标成当天报价。
- 人民币直接按 1 换算，不建立 CNY/CNY 记录。这是参考换算率，不代表银行成交价。
- 截至本次读取，正式库有 178 个启用币种、0 条汇率记录。文件覆盖 158 个外币，另有 CNY 恒等换算。以下 19 个代码在该公开数据源中无报价：`BOV CHE CHW CLF COU MXV USN UYI UYW VED XAD XBA XBB XBC XBD XSU XTS XUA XXX`。它们保持未配置；涉及换算时提示维护，不默认成 1。

## 可复核文件

| 文件 | 内容 | SHA256 |
| --- | --- | --- |
| `exchange_rates_20261015.json` | 158 条规范化导入记录 | `8D2982BEB6B7C723BEF29ED3203D443B482C46EFA191F6E2F505830F274A8398` |
| `exchange_rates_20261015_cfets_direct.json` | 25 个币种的直接报价 | `5AA46BC9EA462DCA7D465FA81FA9B94D7B9D630C36EBA01173ADBED215DA733B` |
| `exchange_rates_20261015_cfets_raw.json` | CFETS 的 CNY 基准原始响应 | `3C976AF62F165F2BE07B02C33CFC7B605525E98D4782E1BF205A51030D5B8FD3` |
| `exchange_rates_20261015_frankfurter_raw.json` | 公开报价及提供者原始响应 | `5A5E91974FC5391D4CA90BAACCCA368E833C82178C243E6BAC54B289D3D88BA3` |

## 导入与复核

先把 JSON 文件复制到目标后端容器的临时目录；导入命令只读取文件，不访问外网。下例的员工编号必须替换为真实在职且有新增汇率权限的员工。

```powershell
docker cp docs/reference_data/exchange_rates_20261015.json haiqu-backend:/tmp/exchange_rates_20261015.json
docker compose exec -T backend python manage.py import_initial_exchange_rates /tmp/exchange_rates_20261015.json
# 上一行仅预览；确认目标数据库和写入授权后再执行：
docker compose exec -T backend python manage.py import_initial_exchange_rates /tmp/exchange_rates_20261015.json --apply --employee-code <真实员工编号>
```

命令先验证整个文件，再在同一事务中写入和记录审计。币种必须已经存在并启用；禁止同币兑换、非正数、超过精度或重复币种对。已有历史记录的币种对跳过，重复运行不会覆盖维护者的数据。未配置币种或无效记录会使整批失败，不会部分写入。

生产创建从唯一有效的兑 CNY 记录读取并冻结 8 位汇率、记录 ID、来源和日期；缺失或同时存在多条有效记录时阻止换算。旧任务不会因为基础资料更新而重新计算。

本文件说明数据与执行方法，不代表已经在正式数据库执行。实际目标、命令、行数和结果见本任务验收报告。

