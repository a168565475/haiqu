# 管材按根收货与分表上线

本次暂存和冻结工作树 `E:/workspace/_project/project001_haiqu_ERP_CRM/qa/.tmp/release_20261121_pipe_receiving_ui` 用于验收与打包，Git 同步后按确切目录清理。服务器上传暂存 `/opt/haiqu-erp/incoming/20261121-pipe-receiving-ui`，切换及 Git 核对后按文件清单删除。正式发布及审计目录 `/opt/haiqu-erp/releases/20261121-pipe-receiving-ui` 和 `/opt/haiqu-erp/deployment-logs/20261121-pipe-receiving-ui` 留作运行与回退。

后端验收用本机 Docker 容器 `haiqu-release-pipe-receiving-tests-20261121` 和本机隔离 PostgreSQL 容器 `haiqu-receiving-abc-trial-20261121-postgres-1` 内的 `test_haiqu_release_pipe_receiving_20261121`。Django 标准测试自动删除该库，容器由 `--rm` 清理。临时设置及日志都在上述本次暂存目录。

## 发布范围

- 采购入库与品质确认按材料类别分表。五金件、塑料件、包材共用入口，面料、辅料共用入口。只显示本单有明细的材料类别，属性各列展示，颜色列 192 px，数量列放在属性之后。
- 新的生产采购管材收货和退货填整根。供应商应付按采购批次约定的公斤数和合格根数折算。已有按公斤收货的批次继续按原口径办理。
- 电脑和手机领料按当前产品的剩余需求判断。超量时列出物料和差额，确认后才提交。

## 构建与只读检查

- 源码提交 `3e75e0f268c92122053db0d5c479ba9f4ea39d7a`。服务器发布清单 SHA-256 为 `8f4c607b7b87ef4264aaf6890e48f3a67191f8bff01ae70f39082837648d90bf`。
- 桌面 Vitest 定向用例 256 项通过，手机 Vitest 全套 420 项通过。两端生产构建及类型检查通过。
- 服务器 Django 系统检查和迁移漂移检查通过。OpenAPI 0 个错误，637 条生成警告。迁移计划为空。校验了 20 个后端增量文件、596 个桌面资源和 55 个手机资源，并用 Nginx 运行账号确认网页资源可读。
- 服务器候选应用只读查看了实际采购单中的 20 条明细，其中 4 条符合按根收货条件。入库记录探测结果为空，因此记录明细的业务验证使用本机的隔离测试库。
- 隔离 PostgreSQL 的 Django 定向回归 88 项全部通过，用例覆盖收货分区权限、实收整根、质检退货、采购跟踪、应付折算、历史公斤批次和按产品计算领料余量。Django 自动删除本次测试库，Docker 移除了测试容器，已复查两者不存在。

## 上线结果

- 版本 `20261121-pipe-receiving-ui` 已切换，后端和 Web 容器健康。数据库、Redis、文件扫描和通知进程沿用原容器。切换前再次确认迁移计划为空。
- 公网健康检查、电脑和手机的登录页均通过。公网比对了 4 个入口页面和 6 个业务资源的 SHA-256。5 个业务接口对未登录请求均返回 401。发布过程对服务器业务数据执行只读检查。
- 运行目录、审计日志和可回退镜像保留。服务器审计目录为 `/opt/haiqu-erp/deployment-logs/20261121-pipe-receiving-ui`。
