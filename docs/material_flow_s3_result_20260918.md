# 材料流程 S3 换算和库存基础实施结果

日期：2026-09-18。依据：业务方案 V1.3、用户已整体确认的 S2 技术清单 V1.0，以及本步“确认”授权。

结论：S3 已在独立代码副本和独立 PostgreSQL 中完成。24 项专项测试通过；相关四模块扩大回归存在已在改动前源码复现的 7 项原有失败，不能表述为全量回归通过。主项目业务源码未合入、业务数据库未迁移、旧数据未清理。S4 尚未开始。

## 1. 交付位置与隔离边界

- 原项目：`E:\workspace\_project\project001_haiqu_ERP_CRM`。这里只更新方案、报告及 QA 证据。
- 实施副本：`E:\workspace\_project\project001_haiqu_ERP_CRM_s3_isolated_20260918`，分支 `material-flow-s3`。
- 副本基线提交：`b1ddfbf5d0797505749899b6294d10628c6913e4`。副本由当前工作文件创建，包含原项目已有但尚未提交的后端文件，不是从旧主分支替代用户工作。
- 本步改动未提交、未推送；完整后端差异见 [s3_backend.patch](../qa/material_flow_s3_20260918/s3_backend.patch)，文件与哈希见 [manifest.json](../qa/material_flow_s3_20260918/manifest.json)。不要直接向正在运行的主项目应用补丁；后续按 S4—S9 顺序集成。
- 隔离容器：`haiqu-material-flow-s3-backend`、`haiqu-material-flow-s3-pg`、`haiqu-material-flow-s3-redis`。仅连接内部网络 `haiqu-material-flow-s3`，无宿主机端口发布，后端仅挂载实施副本。数据库数据目录使用临时内存存储；容器停止后不能依赖其数据留存。
- 基线复跑另用只读源码容器，结束后自动移除。现有业务容器未停止、重建或改挂载。
- [主源码哈希复核](../qa/material_flow_s3_20260918/main_source_comparison.json)记录检查数量和差异；本步无原项目业务源码变化。

## 2. 本步改了什么

下表路径均相对实施副本，不代表已经合入主项目。

| 文件 | 实际改动及结果 |
| --- | --- |
| `src/backend/apps/boms/material_flow_calculations.py` | 共用十进制换算：管材整数 mm、每根一次 50 mm、单根米数向上保留两位、采购 1% 余量后整根向上取整、原料支数须整根换算；面料按套向下取整并单列余米 |
| `src/backend/apps/boms/models.py` | BOM 部位独立身份、管材类型字段、裁片来源面料关联和每套耗米；缺资料保持空值，不推测旧管材参数 |
| `src/backend/apps/products/material_identity.py` | 裁片明确关联同一 BOM 的面料来源，拒绝自引用、跨 BOM、裁片套裁片和非米制面料；不按名称猜原料 |
| `src/backend/apps/inventory/models.py` | 新管材入库及批次余额同时记录根数、单根米数、总米数；流水保存出入前后根米；旧单数量库存保留原逻辑 |
| `src/backend/apps/inventory/pipe_stock_services.py` | 管材批次入账、发料基础事务，先校验整根/批次/长度/余额/额度后扣账；重复请求不重复扣，任一批次失败整体回滚 |
| `src/backend/apps/inventory/stock_services.py` | 旧单数量扣库入口排除新 PIPE 库存，防止将根误当米或支；新批次可按真实余额查询 |
| `src/backend/apps/material_issues/models.py`、`pipe_requirements.py` | 按生产任务、产品行和 BOM 部位建立支数额度；厂内领料与外发共享；来源变化重校验，使用后的身份/参数变化受限 |
| `src/backend/apps/material_issues/requirements.py` | 旧额度同步不覆盖新管材额度；管材提示定位到具体 BOM 行，避免阻塞无关面料、包材等类别 |

新增数据库迁移 5 个：`boms/0007_material_flow_fields.py`、`boms/0008_material_flow_constraints.py`、`inventory/0013_pipe_batch_quantities.py`、`inventory/0014_material_flow_constraints.py`、`material_issues/0003_component_allowance.py`。新增 0008/0014 用于数据库约束，未修改旧迁移。仅在隔离测试数据库执行。

旧 BOM 行生成各自不同的部位身份；旧库存保留数量和旧计量类型。**没有将旧管材换算成根/米，也没有自动清零任何业务库存。**

## 3. 结果示例与异常处理

订单 1000 件、单耗 2 支、切割长度 500 mm、每根切 6 支：单根 3.05 米，建议采购 337 根／1027.85 米，共享额度 2022 支。原料领取 2000 支会因不整根被拒绝；2004 支对应扣 334 根／1018.70 米。此整根限制不用于管材半成品领料。

面料外发 100 米、每套耗用 1.5 米：预计 66 套、余米 1.0000 米；余米不自动记损耗。外发回货和余料退回的业务接口仍属于 S6。

已覆盖空值、负数、小数支数/毫米、非有限数字、数值越界、超精度、不同单根长度、重复批次、选中批次库存不足、额度超用、重复请求载荷变化、来源变化以及并发抢同一额度。数据库另阻止半根余额、根米不一致和额度超用。

## 4. 验证证据与限制

| 验证 | 实际结果 |
| --- | --- |
| S3 最终专项 | **24/24 通过，退出码 0，96.404 秒**；见 [s3_tests_r5.log](../qa/material_flow_s3_20260918/s3_tests_r5.log) |
| 四模块扩大回归 | 206 项，198 通过、1 失败、7 错误，退出码 1；见 [s3_regression_r4.log](../qa/material_flow_s3_20260918/s3_regression_r4.log)。其中本次新增用例缺少测试员工必填字段，已补齐并在最终专项中通过 |
| 改动前源码对照 | 剩余 7 项原有失败全部复现：6 项 BOM 读取测试重复创建已存在的“个”单位；1 项塑料候选字段断言未包含已有 `item_type`、`item_type_display`；见 [s3_baseline_failures_r3.log](../qa/material_flow_s3_20260918/s3_baseline_failures_r3.log)。本步不修改这些原有测试或业务功能 |
| 迁移验证 | 实际退至 BOM 0006、库存 0012、领料 0002，再迁到新结构；旧余额 ID/数量不变、旧计量字段不转换、旧 BOM 行身份各自独立 |
| 并发与兼容 | 两个独立数据库连接竞争同一部位额度，只允许一笔成功；管材发料后，面料仍通过真实接口完成新建、提交和仓库确认，面料 100→95 米，管材余额保持不变 |
| 静态及迁移一致性 | Django check、makemigrations --check --dry-run、git diff --check 均退出码 0；见 [s3_static_checks.log](../qa/material_flow_s3_20260918/s3_static_checks.log) |
| 接口文档生成 | spectacular --validate 退出码 0、0 errors；有 565 条警告（183 类），不能称零警告；见 [s3_schema_check.log](../qa/material_flow_s3_20260918/s3_schema_check.log) |
| 独立代码审查 | 按 requesting-code-review 技能执行只读审查。发现并修复旧额度同步误判管材已领额度、管材拦截范围过宽两项问题；复审未发现新增严重问题。补测已覆盖普通面料实际出库与库存旧结构迁移 |

中间失败轮次也保留：复用测试库导致种子数据被事务测试清除，后续改为每轮唯一测试数据库；初始基线容器只读目录不能创建媒体目录，增加独立临时媒体挂载后完成基线复跑。这些轮次不计为通过证据。

未执行前端构建、1920×1080 页面验收、实际用户业务写入或生产环境完整链路验收。本步未改前端；新服务没有公开业务接口。后续 S5—S7 调用时仍须实现完整单据权限、状态校验、跨部位全单事务，以及按同一顺序锁定全部额度和批次。本步多批次原子操作不能替代全单接入验收。

## 5. 复核方法与依赖

沿用项目已有 Django、PostgreSQL、Redis 和后端 Docker 镜像，不新增运行依赖。以下命令针对已保留的隔离容器，禁止替换成业务容器执行；每次使用新的测试数据库名字。

```powershell
docker exec -e POSTGRES_DB=material_flow_s3_review_01 haiqu-material-flow-s3-backend python manage.py test apps.boms.tests.test_material_flow_calculations apps.boms.tests.test_material_flow_migration apps.inventory.tests.test_pipe_stock_foundation --noinput --verbosity 1
docker exec haiqu-material-flow-s3-backend python manage.py check
docker exec haiqu-material-flow-s3-backend python manage.py makemigrations --check --dry-run
```

## 6. 下一步待确认

S4 仅处理 BOM：字段更名、统一调用本步公式、单耗与裁片面料关联校验，所有分类移除底部编辑区并改为行右侧编辑弹窗；同步处理复制、导入、订单数量同步、预览和打印回归。仍在隔离环境开发，页面范围及验收口径须遵循批准方案；不进入采购、外发、领料页面或业务库清理。取得用户 S4 确认后再开始。
