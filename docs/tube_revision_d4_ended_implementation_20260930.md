# D4 已结束详情及只读入库凭证开发结果

日期：2026-09-30。用户已确认本页及窗口图稿。本步在隔离 S3 系统开发完成，主 ERP 尚未同步。

## 按什么要求改、前后有什么变化

按已确认的 `tube_revision_d4_ended_design_review_20260930.md` 和冻结图源 `D4EndedReviewApp.vue` 实施。

| 要求 | 改前 | 本步结果 |
| --- | --- | --- |
| 一单一次回货登记后看最终结果 | 已结束详情主要显示实发量 | 同表展示实发、实收、差额、原因及库区 |
| 原材料不另起换算表 | 原表有管材根米，但没有最终回货结果 | 17 列同表显示，保留发出时切割支数、原材料长度、扣根与扣米，不按当前 BOM 补算 |
| 另两来源直接按支 | 仍是普通外发详情 | 未喷塑半成品、未入库半成品分别为 13 列，只显示支数及最终结果 |
| 允许少回或全 0，一单结束 | 无完整的最终实收展示 | 全部部位和 0 行保留；0 行未入库；整单 0 显示未新增库存 |
| 来源详情用弹窗，只读 | 没有最终凭证窗口 | 1640px ERP 窗口显示最终凭证，只查看和关闭 |
| 不再关联采购批次 | 原公共库存规则已实现 | 本步沿用公共库存，不引入采购批次或新档案 |
| 按确认稿和 ERP 组件开发 | 旧详情样式 | 表头 44px、行 40px、控件 32px、左右留白 10px、外围四边单层 1px、圆角 5px、主题色 #c84e28；数字右对齐，长表内部滚动 |

顶部生产资料明确标记“当前订单量”，避免把当前关联资料称为全量冻结历史；回货属性、实发、实收、差额、原因、颜色、加工厂及库区取最终凭证。

## 读路径、历史对应及权限

首读现有 `GET /api/v1/tube-outsourcing-orders/{id}/receipt-preview/`。已结束直接取响应中的原单和最终凭证，不先调用普通详情，不查当前最低报工。

非终态或首次预览拒绝回货查看时，沿原普通详情读取与权限校验。若两次读取之间单据刚完成回货，再读取最终凭证并重新授权；再次 403 时隐藏旧数据。500、404、超时和其他错误不回退到另一条路径掩盖失败。

原单与凭证按 `order_line_id` 对应，不按部位名称、加工厂名称或数组顺序。原材料根米取对应原单历史字段。错单、重复、缺行、外来行、数量或汇总不一致、关键历史字段缺失时提示核对并禁用完整凭证；未知值显示“—”，不默认为 0。

为覆盖读取过程中刚完成回货的并发窗口，隔离后端 selector 只增加了一条状态判断：

```diff
-    basis = metal_component_limits(order.product_line) if order.source_kind == 'METAL' and include_metal_basis else None
+    basis = metal_component_limits(order.product_line) if order.source_kind == 'METAL' and include_metal_basis and order.status != 'COMPLETED' else None
```

待发、加工中和取消状态仍沿原报工依据逻辑。没有修改库存服务、数量额度、工序、发出及入库规则、模型、迁移或写接口。

已结束预览依现有查看或回货权限，分别检查该权限能否覆盖原单工艺，不能拼接授权。前端路由仍要求登录。仅回货权限用户可通过已有详情链接查看，侧栏及统一列表的入口接入仍属后续步骤，未在本页扩展角色授权。

## 修改范围

隔离原文件修改 3 份：详情 Vue、原详情测试、后端 selector。新增隔离文件 5 份：已结束显示组件、局部样式、凭证对应校验工具、已结束页面测试、已结束后端只读测试。

本轮 3816 个文件基线核查：主系统源码、已有已批准图稿、继承 ERP 组件未变化；无删除，无非授权隔离文件变化。旧文件备份、授权记录及本轮测试证据位于 `qa/tube_revision_d4_ended_implementation_20260930`。

## 验证结果

- 前端相关 6 个测试文件，134 项通过。其中本页及原动作测试共 61 项，覆盖三来源、历史根米、同名乱序的稳定编号对应、冻结属性、0 与未知值区别、缺失和错误凭证、原单明细结构损坏、刷新竞态、权限与非终态兼容。
- 前端类型检查、生产构建退出码均为 0。生产构建保留既有较大资源包警告；本步不扩大到资源拆分。
- 后端新增 4 项及现有权限 9 项，共 13 项通过。修前测试准确复现已结束 METAL 动态查询，修后一行状态保护消除此问题。仅使用 `test_tube_s3_d4_ended_reads_20260930` 独立测试库，不向演示业务库或主库造单。
- 系统检查无问题，模型迁移漂移检查及已应用迁移检查通过；本步没有新增或执行业务库迁移。
- 真实 Chrome，1920×1080；三真实来源详情和只读窗口、11 组浏览器模拟边界、8 组尺寸测量，21 张截图通过。其中 7 张为真实读取（含待发回归），14 张为明确标识的 GET 拦截布局或异常验证。
- 页面错误 0，业务非 GET 请求 0；已结束页面只读取凭证预览。三张已结束原单与保留待发原单查看前后业务响应一致。
- 独立代码复核未发现未决严重、重要或次要问题；复核边界仅为本页和只读保护。

浏览器早两轮检查发现局部留白被旧样式覆盖为 16px、数量表头仍左对齐。通过提高已结束页及凭证窗口局部样式优先级修正；没有全局覆盖或放宽验收断言，最终按原规范复验通过。首次类型检查的元组类型提示也已修正并重新检查。

主要命令：

```powershell
# 工作目录：qa/tube_revision_s3_20260929/frontend
& 'D:\Program Files\nodejs\node.exe' '.\node_modules\vue-tsc\bin\vue-tsc.js' -b
& 'D:\Program Files\nodejs\node.exe' '.\node_modules\vite\bin\vite.js' build
& 'D:\Program Files\nodejs\node.exe' '.\node_modules\vitest\vitest.mjs' run src/views/outsourcing/TubeOutsourcingDetailView.spec.ts src/views/outsourcing/TubeOutsourcingEndedView.spec.ts src/views/outsourcing/TubeOutsourcingFormView.spec.ts src/views/inventory/TubeCoatingReceiptView.spec.ts src/utils/tubeOutsourcing.spec.ts src/api/tubeReceipts.spec.ts --reporter=dot
# 上述过滤实际匹配6个现有测试文件，134项。
docker exec -e TUBE_TEST_DATABASE=test_tube_s3_d4_ended_reads_20260930 haiqu-tube-s3-20260929-backend-1 python /qa/run_tests.py apps.outsourcing.tests.test_tube_ended_reads apps.outsourcing.tests.test_tube_receipts_api.TubeReceiptScopeTests apps.outsourcing.tests.test_tube_actions_api.TubeActionsScopedTests
docker exec haiqu-tube-s3-20260929-backend-1 python manage.py check
docker exec haiqu-tube-s3-20260929-backend-1 python manage.py makemigrations --check --dry-run
docker exec haiqu-tube-s3-20260929-backend-1 python manage.py migrate --check
```

沿用现有依赖，无需安装新包。前端全项目测试、统一列表、旧历史接续、主系统迁移及生产部署没有在本步执行，不将相关专项测试描述为全量验收。

## 实际入口与下一步

截图合集：http://127.0.0.1:8104/d4-ended-implementation.html

实际隔离页面（需已登录隔离系统）：

- 原材料，发 20 收 20 差 0：http://127.0.0.2:8105/workshop/outsourcing/tube/df4f905f-632d-4eeb-93c1-780abb8a7310
- 未喷塑半成品，发 20 收 18 差 2：http://127.0.0.2:8105/workshop/outsourcing/tube/5202c8dd-deb2-4a28-9415-2a95b02c4aa4
- 未入库半成品，发 20 收 0 差 20：http://127.0.0.2:8105/workshop/outsourcing/tube/1d183961-82c0-4d2e-874b-cff425951e5b

下一页是统一外发列表接入新管材单，先提交设计细节和业务变化，用户确认图稿后开发。旧历史转换、旧写入口清理、主 ERP 启用仍待各自后续批准步骤。
