# 新版打样申请与厂长审核接口接通

范围：按用户“打通”的授权，接通已完成 Figma 页面对应的创建申请、厂长确认/退回、补充重提。没有扩展旧版财务/PMC流程，也没有实现材料提交仓库/采购接口。

## 使用方式

1. 打样申请列表 → 新建打样申请 → 提交厂长确认。系统生成 SRQ 编号并进入 DIRECTOR_REVIEW。
2. 有 `samples.review_sample_application` 权限的有效员工在厂长确认页处理；该独立权限由系统管理员授予对应厂长账号，未批量授予普通业务员。超级管理员具有该权限。
3. 退回必填意见，状态 APPLICATION_RETURNED。符合客户范围和来源权限的申请人/业务员在列表“更多 → 补充并重提”修改原单，不产生新编号。
4. 确认可做进入 MATERIALS_PENDING。列表“查看”交接现有材料需求页；后续材料保存、提交仓库仍未接通。

## 接口契约

- `POST /api/v1/sample-requests/applications/`：JSON `{payload: {...}}` 或 multipart 的 JSON `payload` + 可选 `reference_image`。
- `POST /api/v1/sample-requests/{id}/application-resubmit/`：同提交字段，必须携带 If-Match。
- `POST /api/v1/sample-requests/{id}/director-review/`：`{decision: "approve" | "return", note: string}`，必须携带 If-Match。
- 新增 `application_actions` 明确是否新版申请、是否可审核/重提；详情返回 `reference_image` 与 `director_note`；统计返回 `pending_director`。
- 创建要求稳定 UUID `idempotency_key`；相同键、相同内容重试返回原申请；键已占用而内容不同返回 409。服务端事务锁处理并发创建、状态变更，过期/缺失版本分别返回 412/428。
- 基础信息、产品、五项可选尺寸、要求与数量落入已有 SampleRequest/SampleProduct/SampleItem。数量用一行实际申请记录保存，不补造色卡、任务单图片或打样信息明细。参考图片独立关联 BusinessFile，经现有 ClamAV 扫描后保存，最多一张 JPG/PNG、5MB。
- 来源创建复用当前来源资格及客户校验，并要求来源模块查看权限；重提保留原来源类型、记录、产品及报价版本快照，不因后续报价升级而失效。权限撤回后动作关闭。
- 提交、退回、重提和确认均写现有审计与客户时间线，重复退回轮次保留各次记录。

## 修改范围

- 后端新增 `application_services.py`、`api/application_serializers.py`、`api/application_views.py`、`tests/test_application_api.py`、迁移 `0021_application_director_flow.py`。
- 接入 `models.py`、`selectors.py`、`services.py`、`form_services.py`、`api/views.py`、`api/serializers.py`。只追加新版入口、字段及状态，不覆盖既有改动。
- 前端接入 `api/sampleApplication.ts`、相关 types、创建页、厂长页、列表、申请摘要图片和状态映射；更新专项测试。
- 复用现有申请分区、状态标签、未保存保护、客户端 UUID、图片扫描、审计、Session/CSRF、ETag。没有新增依赖或普通 CSS。

## 部署与验证

- 迁移前备份：`backups/haiqu_before_sample_application_20260910_1443.dump`（2,263,375 bytes）。只应用 `samples.0021_application_director_flow`，迁移成功。
- `manage.py test apps.samples.tests.test_application_api apps.samples.tests.test_sample_api --keepdb --noinput --verbosity 1`：45 项通过，包含旧版接口回归、权限、来源伪造、版本升级重提、图片访问、幂等、ETag、Session/CSRF。
- 前端类型检查与生产构建通过；构建仍提示已有 PURE 注释与大包警告。项目没有 lint 脚本。
- 前端最终专项包含 SampleListView、samplePresentation、SampleDirectorReviewView、SampleApplicationCreateView、sampleApplication 校验与 API，共 6 文件 42 项通过。原列表“厂长未开放”测试已更新为真实 pending_director 统计和 DIRECTOR_REVIEW 筛选验证。
- OpenAPI 校验通过，0 错误；全项目仍有 452 条警告（157 个不同警告）。迁移漂移检查 `No changes detected`，`migrate --check` 通过。
- `qa/sample_application_flow.cjs` 在 1920×1080 通过：真实前端 + 独立 Django 服务 + `qa_sample_application_20260910` 测试库；4 次样品写请求分别为创建 201、退回 200、重提 200、确认 200。无接口假响应，参考图片实际扫描及读取成功，浏览器 errors=[]。
- 浏览器验证数据与上传文件均隔离于业务库；测试上传为单像素 PNG，仅用于验证链路。不能将截图中的示例数据视为真实业务单。
- 截图与机器证据：`outputs/sample_application_flow_20260910/`，已目视核对待审核页、补充页的 1920 布局。
- 独立审查提出的来源权限、来源类型伪报和重提权限不一致问题已修正，并经复核无新增阻断问题。
- 已运行实际业务服务的厂长页只读脚本，真实读取、终态门禁、错误重试通过，无业务写请求。隔离验收容器已停止；独立验收数据库保留，临时容器内测试上传随容器移除，不影响业务图片。
