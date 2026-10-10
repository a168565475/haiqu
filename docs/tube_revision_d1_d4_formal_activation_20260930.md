# D1-D4 管材外发正式激活记录

日期：2026-09-30

## 本次确认范围

本次按已确认的 D1-D4 方案，将隔离验收版的管材外发、管材半成品入库、喷塑整单回货、库存预留、报工数量门禁和统一外发列表合并到正式 ERP。未修改采购入库、面料流程或用户明确暂不处理的旧管材转换。

## 正式变更

- 后端补齐管材订单、明细、生命周期和最终回货凭证模型及 `0009`、`0010`、`0011` 迁移。
- 后端接入统一外发列表：材料来源分为原材料、未喷塑半成品、未入库半成品；保留旧流程标识，按来源与权限返回。
- 后端接入管材原料/公共半成品预留、生产领料与委外发料上限、报工最低工序和半成品入库上限。
- 前端接入管材外发新建、详情、喷塑整单回货、金工半成品入库、统一外发列表及库区选择。
- 修正来源权限：仅有金工来源查看权限的账号只显示“待外发材料”，不加载普通外发列表和普通筛选。
- 补齐仓库独立喷塑回货入口 `/inventory/semi-finished/tube-return`；内部计划金工半成品入库从计划行携带 `schedule_product_id` 与 `plan_category=METAL`。
- 正式 compose 开启 `TUBE_OUTSOURCING_ENABLED=True`。

## 数据与服务操作

- 正式数据库备份：`backups/haiqu_erp_d1_d4_activation_20260930_185242.dump`，文件大小 9,067,723 字节，`pg_restore --list` 可读取。
- 已执行并确认：`outsourcing.0009`、`0010`、`0011`。
- 正式后端已重建，健康状态为 healthy；前端开发服务保持 healthy。
- 本次浏览器验收只读，没有创建、发料、回货、入库或删除业务数据。

## 验证结果

- 后端 `manage.py check`：通过。
- `makemigrations --check --dry-run`：No changes detected。
- 前端 `npm run type-check`：通过。
- 前端相关 10 个测试文件：179/179 通过。
- 前端生产构建：通过（5301 modules transformed；仅保留既有 chunk 大小警告）。
- 正式 API：统一列表 options 与列表均 200；来源分组返回 RAW、TUBE_PUBLIC、TUBE_METAL、OLD_METAL、REWORK、UNSELECTED。
- 正式 1920×1080 浏览器：统一列表 15 列，表头 44px、行高 40px、控件 32px、列表滚动区域无溢出；页面错误和非 GET 请求均为 0。
- 正式页面入口：管材外发新建 200；仓库喷塑入库 200；内部计划金工半成品入库链接实际携带产品计划与 METAL 参数并可打开。
- 后端专项测试：除并发锁测试外整组运行到 161 项；并发锁测试单独 1/1 通过。整组唯一异常是 Django `TransactionTestCase` 的序列化回滚夹具恢复时重复写入 `admin.logentry`，不是业务断言失败，已保留为测试基础设施问题。

## 截图证据

- `qa/tube_revision_d4_list_implementation_20260930/screenshots-final/formal-8080-outsourcing.png`
- `qa/tube_revision_d4_list_implementation_20260930/screenshots-final/formal-inventory_semi-finished_tube-return.png`

## 当前边界

正式库当前已有的示例外发记录仍显示旧流程记录；这不代表新管材数据未启用。新管材入口和统一列表已启用，后续可按用户要求继续进行业务试跑。旧管材历史转换仍未做。
