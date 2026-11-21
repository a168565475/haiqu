# 采购入库分区与统一入库记录上线

2026-11-21 更新海趣 ERP，版本 `20261121-receiving-records`，线上源码 `131d2606baddb6a5023be0c3f27843ceebb4968b`。最终运行清单 SHA-256 为 `f1d169d7e6b6e91c8aa21388796c4bab9d6827f9b9e2a2a6709ccd5bd4d419de`。

- **采购入库。** 第一列是生产任务单号，可按该单号搜索。右侧三个点提供详情与账号有权办理的材料分区入口。三个入口按管材、五金件/塑料件/包材、面料/辅料命名，入库明细和提交均按现有角色授权限制。
- **入库记录。** 采购收货和材料收发的入库共用仓库菜单中的记录页。采购每次收货生成一条挂在原采购批次下的记录。质检从记录页办理，更新原记录。部分退货仍有合格料时显示「已入库」，全退显示「全部退货」。列表显示分区、品名、货号、供应商和质检时间。产品规格、颜色、材质从列表移除，查看详情仍展示材料明细。未记分区的历史记录显示「未登记」。

## 数据库与线上验证

- 先用 `pg_dump` 备份入库表、角色授权表与资源授权表的结构，并备份角色授权数据，用 `pg_restore --list` 检查内容。备份和审计保存在服务器 `/opt/haiqu-erp/deployment-logs/20261121-receiving-records` 私有目录。
- `manage.py migrate` 实际执行了 `access_control.0012_purchase_receiving_material_scope` 和 `inventory.0034_purchase_inbound_material_section_updated`，执行后待迁移为空。角色授权前后逐行摘要一致，未新增正式仓管账号或分区授权。
- 服务器通过 Django `check`、`makemigrations --check --dry-run`、OpenAPI 校验（0 个错误，685 条生成警告）。测试库 67 项中 57 项通过。10 项既有委外权限测试均在准备数据时遇到五金铆钉用量解析失败。用上一版源码和独立本地库复现了相同的 10 项失败。
- 前端定向 Vitest 154 项通过。`vue-tsc -b` 与 `VITE_API_BASE_URL=same-origin` 的 Vite 生产构建通过。
- 首次切换时桌面资源目录权限导致 JavaScript 和 CSS 返回 404。恢复目录读取后重新构建网页镜像，并按 Nginx 用户检查文件可读性。后台浏览器最终通过 TLS、登录页、同源请求、桌面 4 个脚本哈希、手机入口哈希及匿名接口权限检查。运行中的 26 个后端增量文件和 650 个网页文件通过 SHA-256 校验。数据库、缓存、文件扫描和通知进程延续上一版运行实例。
- 通过只读探针核对线上采购入库列表、生产任务单号搜索和统一入库记录列表。上线时采购收货与材料收发均没有入库记录，未在线上创建用于质检的业务单。

## 临时资源

本地独立工作树和构建文件登记在 `qa/.tmp/release_20261121_receiving_records`。Django 测试库 `test_haiqu_receiving_release_20261121` 由测试运行器删除。基线对照库 `haiqu_receiving_release_baseline_20261121` 在试运行 PostgreSQL 实例中经归属与零连接检查后删除。两个容器使用 `--rm`。公网浏览器临时目录在关闭浏览器后删除并复查。

源码提交经 `git push` 和 `git ls-remote` 核实后，服务器上传文件按清单逐一删除，再用 `rmdir` 删除 `/opt/haiqu-erp/incoming/20261121-receiving-records`。被替换的本次早期网页镜像按准确镜像 ID 删除。服务器运行目录、旧版可回退镜像、授权备份和审计保留。独立工作树用 `git worktree remove --force` 清理，剩余临时文件在发布说明同步后按登记路径删除。
