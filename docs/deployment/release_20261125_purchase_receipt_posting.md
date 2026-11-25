# 采购收货、质检退货与应付发布

发布编号 `20261125-purchase-receipt-posting`。本次范围为普通生产采购与包材采购先收货入账、质检退货扣减库存与应付、收货回执重试。

## 发布前核对

- 后端基线 `20261125-outsourcing-print-pdf`，桌面网页基线 `20261125-outsourcing-pdf-preview`。本轮白名单与线上基线的 16 个既有后端文件逐项核对一致，增加一件库存服务和一条前向迁移。冻结源码包含 33 个改动文件。应付沿用线上汇总表和核价窗口，只合入收货、质检和可结算数量所需的变化。
- 线上预检时没有旧待检入库单。待执行迁移为 `inventory.0036_purchase_return_weight_only`，放宽旧库存和公共库存两张流水表对五金退货的约束。既有单据继续按实际记账凭证处理。采购提醒自动推送沿用线上当前关闭配置。
- 以线上现行权限规则对启用的普通员工账号做只读核对，有仓库收货和品质确认权限的各 5 个。采购应付的查看、核价、确认各为 0 个。系统事务中的自动生成和退货扣减沿业务流程执行，普通岗位进入采购应付仍取决于服务器角色配置。

## 发布准备结果

- 冻结源码 `f17e0299cf5d01b5fa20c7f289a1df3e3e31d792`。`npm run type-check`、`npm run test` 定向 42 项和 `npm run build` 通过。桌面构建的变更来源为三个目标页面及共享收货请求。对其他重建资源核对了组件作用域标识和压缩变量差异。
- 服务器从当前运行镜像继承构建两个候选镜像。候选清单 SHA-256 为 `9dc46c67a1695e3216e742b3784fc813a5b528a6547da452871ae5ed0cf25854`。候选容器只读确认唯一待迁移是 `inventory.0036_purchase_return_weight_only`，候选静态资源和后端文件的摘要通过核查。
- 隔离库已验证执行迁移成功，Django 系统检查、迁移一致性与未执行迁移检查通过。OpenAPI 0 错误、640 条警告。首轮测试脚本未能从指定流读取校验摘要，已改用原日志保留接口结果，并在同一冻结源码上单独重跑业务用例。
- 后端第二轮共 110 项，109 项通过。唯一失败为 `test_zero_quantity_public_raw_balance_is_hidden_from_inventory_list`。用例保留实际重量，只清零根数和米数。线上基线与候选版的该列表查询都保留有实际重量的余额，缺口与本次收货入账及质检退货无关。收货重试、库存和应付同步及质检冲减用例均通过。
- 切换前复核线上健康接口、运行镜像、候选清单和包摘要。`inventory.0036` 是线上当时唯一待执行的迁移。

## 线上切换结果

- 用户明确授权后执行 `migrate inventory 0036_purchase_return_weight_only`。迁移记录为一条，两张库存流水表的检查约束均已验证，迁移计划为空。切换前后两次只读检查的一般材料入库单与采购应付单总数均分别为 6 和 18。
- 后端、网页和通知进程切到 `20261125-purchase-receipt-posting`。运行文件、静态资源、采购合同和字体的摘要核对通过。通知进程与后端同一镜像，内存限制 512 MiB。数据库、缓存及文件扫描服务沿用原容器，移动端资源沿用原版本，采购提醒自动推送保持关闭。
- Playwright 后台只读核验返回公网健康 200，采购入库、入库记录、采购应付在匿名访问时跳转登录，两个业务接口匿名返回 401。入口和三个目标页面的静态资源摘要相符，页面错误为零。业务写入与岗位办理证据来自隔离测试。

## 临时资源登记

- 本机冻结源码、发布脚本、测试日志、浏览器临时目录和打包产物位于 `E:\workspace\_project\project001_haiqu_ERP_CRM\.tmp\release-20261125-purchase-receipt-posting`。前端依赖复用本机现有安装。Git 发布后按归属清理本次暂存。
- 隔离 PostgreSQL 网络 `haiqu-receipt-release-20261125`，临时数据库容器 `haiqu-receipt-release-20261125-db`，一次性测试容器 `haiqu-receipt-release-20261125-test`。Django 负责创建和删除 `test_haiqu_receipt_release_20261125`。容器不暴露端口，媒体、缓存和邮件与业务环境隔离，结束按任务标签清理。
- 服务器上传暂存 `/opt/haiqu-erp/incoming/20261125-purchase-receipt-posting`。发布上下文和审计回执分别位于 `/opt/haiqu-erp/releases/20261125-purchase-receipt-posting` 和 `/opt/haiqu-erp/deployment-logs/20261125-purchase-receipt-posting`，作为运行及审计证据保留。
- 测试器已删除专用测试库。核验容器和网络标签及数据库连接后，执行 `docker stop`、`docker rm`、`docker network rm`，复查测试容器与隔离网络均已清理。
- 代码和发布记录首次推送至 `ade1c467` 后，发布脚本按摘要删除三份服务器上传文件，复查上传目录已移除。Playwright 临时目录已移除。本机暂存目录的递归清理被自动审批以 `blocked by policy` 拒绝，复查该目录仍在。
