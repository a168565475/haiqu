# HAIQU ERP Project Brain

这是 HAIQU ERP 项目的知识库入口。它只负责说明项目背景、读取顺序、事实来源和当前状态；详细规则仍放在对应的正式文档、代码和验证记录中。

## 1. 新窗口读取顺序

开始新的开发任务时，按下面顺序读取：

1. [项目执行约定](../../AGENTS.md)
2. 本入口页
3. [正式设计规范](../../DESIGN.md)
4. 与任务相关的 PRD、开发报告和验收记录
5. 实际前端、后端、模型、迁移和 API 代码
6. 与当前任务对应的最新 QA 证据

旧聊天不能作为唯一事实来源。聊天中未确认的内容只能作为候选，不能直接当作项目规则。

## 2. 项目是什么

HAIQU ERP 面向户外用品外贸及工厂业务，逐步建设客户与销售、产品与物料、采购与库存、生产与委外、权限和基础配置等模块。

纳入建设范围不等于已经全部开发、验收或启用。完整财务和企业微信实际接入仍需专项确认；当前缺少的公司销售 SOP、客户分级、信用政策、汇率和毛利口径，也不能由知识库自行补齐。

详细边界见[业务范围与边界](business_scope.md)。其中区分当前 ERP 项目范围、历史 CRM 阶段和尚未确认的内容。

## 3. 当前技术事实

| 层 | 当前技术 | 事实来源 |
| --- | --- | --- |
| 后端 | Python 3.13、Django 5.2 LTS、Django REST Framework | 项目 README、`src/backend` |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Vue Router、Pinia、Axios | 项目 README、`src/frontend/package.json` |
| 数据与缓存 | PostgreSQL、Redis | `compose.yml`、后端配置 |
| 运行方式 | Docker Compose | `compose.yml`、部署说明 |

技术栈“讨论过”不等于已经采用；发生冲突时以实际配置、依赖文件和运行代码为准。

技术职责、请求流、认证权限和本地运行边界见[技术架构与运行边界](architecture.md)。

## 4. 事实来源规则

| 内容 | 优先事实来源 |
| --- | --- |
| 项目执行约定 | `AGENTS.md` |
| UI 设计规范和设计令牌 | `DESIGN.md`；存在已确认 Figma 节点时再核对 Figma |
| 前端实际行为 | `src/frontend` 中的组件、页面、路由和状态代码 |
| 数据结构 | Django 模型、迁移和数据库只读证据 |
| API 行为 | 后端视图、序列化器、路由、OpenAPI 和真实请求证据 |
| 已确认决定 | 用户明确确认的记录、正式决定文档 |
| 项目进度 | 对应任务、实施报告和验收记录；不能只看旧聊天 |
| 视觉证据 | 对应 QA 截图或浏览器记录；小样不能证明真实 ERP 已验收 |

知识库是索引、解释和长期记忆，不替代代码、模型、API 或设计规范。

## 5. 模块总表

下面登记已经能在代码中定位的模块、用途和入口。模块详细知识暂不创建空文件；只有出现实际规则、流程或验证证据时，才建立对应模块知识。

| 模块 | 主要用途 | 前端入口 | 后端入口 | 当前状态边界 |
| --- | --- | --- | --- | --- |
| [客户与 CRM](crm_customer_module.md) | 客户、联系人、沟通和客户业务资料 | `src/frontend/src/views/customers`、`contacts` | `src/backend/apps/customers`、`crm` | 已建立模块知识卡；PRD 对齐见 [清单](crm_prd_alignment.md) |
| [询盘](inquiry_module.md) | 询盘来源、产品需求和处理进度 | `src/frontend/src/views/inquiries` | `src/backend/apps/inquiries` | 已建立模块知识卡；删除保护和跨模块回写仍需按证据核对 |
| [报价](quotation_module.md) | 报价单、报价版本和报价相关记录 | `src/frontend/src/views/quotations` | `src/backend/apps/quotations` | 已建立模块知识卡；发送、接受和转单仍需按证据核对 |
| [样品](sample_module.md) | 样品申请、打样、费用、物流和客户反馈 | `src/frontend/src/views/samples`、`components/samples` | `src/backend/apps/samples` | 已建立模块知识卡；材料采购、到料、领料和库存扩展与 CRM 分层记录 |
| [产品与物料](product_material_module.md) | 产品资料、BOM、原料和物料业务 | `src/frontend/src/views/products`、`boms` | `src/backend/apps/products`、`boms`、`material_issues` | 已建立知识卡；产品/原料/BOM数量边界仍需按证据核对 |
| [采购](procurement_module.md) | 供应商、采购订单、采购来源和采购履约 | `src/frontend/src/views/procurement` | `src/backend/apps/procurement` | 已建立模块知识卡；采购到货和样品采购变更仍需按证据核对 |
| [库存](inventory_module.md) | 仓库、入库、库存余额、库存移动和出库 | `src/frontend/src/views/inventory` | `src/backend/apps/inventory` | 已建立模块知识卡；旧模式、公共库存和样品库存边界分开记录 |
| [销售订单](sales_order_module.md) | 销售订单、交付批次和订单完结 | `src/frontend/src/views/salesOrders` | `src/backend/apps/sales_orders` | 已建立模块知识卡；下游生产、BOM、采购边界单独记录 |
| [生产与委外](production_outsourcing_module.md) | 生产任务、车间作业和委外流程 | `src/frontend/src/views/production`、`workshop`、`outsourcing` | `src/backend/apps/production_tasks`、`production_scheduling`、`workshop_reporting`、`outsourcing` | 已建立知识卡；开发按 D-083 暂缓 |
| [权限与基础配置](access_control_module.md) | 角色、员工账号、团队、权限和基础资料 | `src/frontend/src/views/settings`、`components/access` | `src/backend/apps/access_control`、`core`、`preferences`、`reference_data` | 已建立模块知识卡；开关、资源范围和业务 API 仍需按矩阵核对 |

模块边界、业务规则、接口关系和“完成”判定以后按模块单独确认，不能只根据目录存在推断。建立模块知识卡时使用[模块知识卡模板](module_brain_template.md)，但不要为没有实际内容的模块创建空文件。

## 6. 当前项目状态

状态快照日期：2026-10-07。

### 已完成

- 设计规范：[`DESIGN.md`](../../DESIGN.md) 第10章是当前正式规则入口；基础项和第1—10批共50项通用规则已确认。
- 设计差异：第11—15批已登记源码差异和页面例外，记录见 [`qa/design_knowledge_review_20260930`](../../qa/design_knowledge_review_20260930)。
- Project Brain：已建立入口、业务范围、架构、模块知识卡模板和决定记录。
- Project Brain 状态队列：已建立[当前状态与待办队列](project_status_and_queue.md)，区分已确认规则、代码缺口、证据缺口和暂缓开发。
- 已确认决定：[`decisions.md`](decisions.md) 已记录 D-001 至 D-112，共 112 条；其中 102 条为当前有效，10 条暂缓。
- 客户与 CRM：已建立模块知识卡和 PRD 对齐清单；原 CRM PRD 保留为历史评审稿和目标参考，当前代码事实单独记录。
- 样品相关范围：样品费用、豁免、付款、物流、反馈、风险放行和样品物料流程已记录；样品采购、到料、领料、库存属于当前 ERP 扩展范围。
- 样品模块：已建立模块知识卡和[规则差异矩阵](sample_rules_gap_matrix.md)；代码状态、历史验收证据、用户细化规则和实现差异分开记录，不能把页面专项验收当作全流程完成。
- 报价与销售订单：已建立独立模块知识卡，报价接受、订单确认和下游生产采购边界分开记录。

### 当前进行中

- 已建立主要业务模块知识卡和样品规则差异矩阵；当前转入待办队列维护和高风险证据核对。
- 对代码事实、PRD、用户决定和实现差异分别记录；业务规则仍按“先提议、用户确认、再写入”的顺序建立。

### 暂缓

- 第16批业务型页面模式暂缓，不进入正式规范和知识库。
- 生产与委外当前暂不进入代码开发；只允许继续做事实盘点和知识记录，不能写成已实现。

### 尚未建立或尚未确认

- 产品与物料知识卡已建立；产品、原料、BOM 与采购库存的数量和引用边界仍需持续核对。
- 经验、研究、发布和工作日志尚未形成独立知识块；当前的任务进度、技术债和证据缺口先集中记录在[状态与待办队列](project_status_and_queue.md)，不重复拆文件。
- 历史聊天不能视为已全部扫描；当前知识库只依据已访问的项目文件、代码、现有记录和用户已确认决定。
- 设计规范确认不代表真实 ERP 页面已经全部同步或验收。
- 客户删除门禁、建档校验、权限和文件安全等差异目前只完成记录，尚未完成代码修复和运行验收。

### 下一步

- 材料需求版本、提交后编辑和采购单建立后的锁定边界已按 D-082 暂缓，不进入当前代码实施。
- 材料改造按 D-082 继续暂缓；生产与委外开发按 D-083 暂缓。权限知识卡已建立，后续只做矩阵核对和事实更新。
- 继续维护[当前状态与待办队列](project_status_and_queue.md)，优先补充证据缺口，不自动扩大代码开发范围。
- 再按模块核对代码、模型、API、PRD 和现有 QA 证据，并提出需要用户确认的规则。
- 对高风险代码差异单独确认改造范围，完成后再做测试、API 和浏览器验收。
- 需要纳入 Git 跟踪或提交时，另行确认版本控制范围。

状态只表示当前记录，不替代对应代码、API、数据库或浏览器验收结果。旧报告可能落后于当前代码，执行任务前必须回到事实来源复核。

## 7. 知识生命周期

每条进入知识库的内容都要标记状态：

- `draft`：正在讨论，未确认
- `confirmed`：用户已经明确决定
- `verified`：已经通过代码、Figma、API、数据库或浏览器证据验证
- `active`：当前仍适用
- `superseded`：被新决定替代，但保留历史和替代关系
- `deprecated`：不建议继续使用
- `archived`：历史记录，仅供追溯

未确认的候选不能写成 `active` 或 `verified`。冲突内容先保留旧值、新值、来源和日期，等待确认，不能静默覆盖。

## 8. 入口维护规则

- 项目目标、技术栈、模块入口、事实来源或当前重点变化时更新本页。
- 详细业务规则、设计参数、接口契约和踩坑经验写入对应知识块，本页只链接和概述。
- 没有长期用途、可以从代码自动重新生成或只有一次性像素测量的内容，不为了完整而新增文件。
- 每次任务结束时，只在确实产生长期价值的情况下提出知识库更新；一般进度不重复复制到多个文件。
- 重要产品、技术和知识库决定记录在[已确认决定记录](decisions.md)，详细规则仍回到各自事实来源。

最后更新：2026-10-07
