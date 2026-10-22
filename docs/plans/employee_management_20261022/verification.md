# 员工与权限维护调整：验证记录

## 范围与实现

- 进度：考勤批次显示进度条与百分比，删除指定的关闭页面说明；员工整批读取使用不定进度条，不编造第三方接口未提供的百分比。
- 两个员工入口：行政 `/employees` 与权限员工页共用 `AccessManagementView`，统一列表、筛选、部门、角色、账号和多选删除；标题和操作按钮放进筛选卡片。
- 删除：角色、部门、员工可删除；有历史引用时移出列表并停止生效，无引用时永久删除。管理员和当前操作者不做身份拦截，删除当前员工会撤销登录会话。审计先记录，业务历史不级联删除。
- 删除接口：`POST /api/v1/access/{employees|roles|departments}/delete-preview/` 与 `delete-selected/`；服务端校验管理权限、每项 ETag、签名预览、If-Match、确认值及最多500项，事务执行并审计。
- 部门绑定：使用有效来源副本，取消每次选择ERP部门时全量重新读取企微；保留配置、来源、映射、目标组织版本和加锁后校验。
- 员工部门：多个来源部门指向相同ERP部门时合并归属，保留唯一主部门；新增“按映射补充部门”入口。已有归属仍保留，补充需要选择员工并保存。
- “主”改为“主部门”，表示来源明确的主要部门。读取弹窗正文顶部12px，首工具栏上边距0px。
- 过期副本现在显示阻断原因；本地主库当前使用线上导入副本，已于2026-10-22 20:15:57（北京时间）过期，且本地未配置企微，不能刷新或保存。没有擅自延长有效期或写入员工归属。

## 修改文件

后端：`apps/access_control/deletion_services.py`、`api/deletion_views.py`、`api/views.py`、`api/organization_views.py`、`api/serializers.py`、`services.py`、`organization_services.py`；`apps/wecom/department_mapping_services.py`、`department_assignment_selectors.py`。均位于 `src/backend/`。

前端：`api/access.ts`、`types/access.ts`、`components/access/DeleteManagementDialog.vue`、`DepartmentMaintenanceDialog.vue`、`views/settings/AccessManagementView.vue`、`views/employees/EmployeeListView.vue`、`EmployeeDirectoryDialog.vue`、`DepartmentMappingDialog.vue`、`views/attendance/WeComAttendanceView.vue`。均位于 `src/frontend/src/`。

测试：新增 `test_management_deletion.py`、`DeleteManagementDialog.spec.ts`；调整 `test_department_mapping.py`、`test_directory_departments.py`、`EmployeeDirectoryDialog.spec.ts`、`EmployeeListView.spec.ts`、`WeComAttendanceView.spec.ts`。

没有新增依赖、修改模型或Migration，没有发布服务器，没有修改AGENTS.md及原有并行任务文件。

## 已执行的检查

1. `docker compose exec -T -e POSTGRES_TEST_DB=test_employee_management_20261022_163c1 backend python manage.py test apps.access_control.tests.test_management_deletion apps.wecom.tests.test_department_mapping apps.wecom.tests.test_directory_departments apps.wecom.tests.test_imported_department_mapping apps.wecom.tests.test_directory_snapshots --noinput --verbosity 1`
   - 初轮102项：92通过，10失败。9项为新增测试账号未使用项目要求的特殊admin身份，修正测试身份后9项全部通过。
   - 另1项为原有 `DirectorySnapshotMigrationTests.test_actual_pre_snapshot_schema_blocks_directory_but_preserves_existing_lists`：断言只回退0005，但当前迁移链已有0006、0007、0008；未修改范围外迁移测试。该项仍失败，不能报告后端全绿。
2. 删除接口末轮补验：`docker compose exec -T -e POSTGRES_TEST_DB=test_employee_management_20261022_163c1 backend python manage.py test apps.access_control.tests.test_management_deletion --noinput --verbosity 1`，13项全部通过，39.745秒，退出码0。覆盖普通角色管理账号的真实Session+CSRF、无权限、缺版本、篡改令牌、无效选择、管理员删除、当前操作者删除、引用保留、永久删除、批量版本冲突与审计失败回滚。所有写入仅发生在独占测试数据库。合并本轮涉及的测试结果共105项通过，另有上述1项原有迁移测试失败。
3. 前端目标Vitest：`AccessManagementView.spec.ts`17项、`DepartmentMappingDialog.spec.ts`29项、`EmployeeListView.spec.ts`15项、`EmployeeDirectoryDialog.spec.ts`37项、`WeComAttendanceView.spec.ts`19项、`DeleteManagementDialog.spec.ts`4项，共121项最终通过。员工路由定位曾失败1项，修正筛选重置时机后已复验通过。
4. `npm run type-check`、`npm run build`：通过。构建仍提示已有大包和第三方纯函数注释警告。
5. `python manage.py check`：无问题；`python manage.py spectacular --validate --file /dev/null`：0错误、597条警告（211种），主要为现有全项目类型推断、枚举名称及操作ID警告。未将全项目Schema描述为无警告。
6. `git -c core.safecrlf=false diff --check -- src/backend/apps/access_control src/backend/apps/wecom src/frontend/src`：通过。

## 真实页面检查与边界

使用已有Chrome本地登录页做截图所要求的视觉诊断，1920×911视口；未伪造接口响应。两处员工入口均显示同一列表和操作；行政标题位于 `.employee-filters` 内，筛选卡片头内边距14px 16px 0px。检查252人列表、筛选单行、无匹配空列表；单行时容器clientHeight与scrollHeight均699，无额外纵向滚动。

读取弹窗实际DOM：正文顶部内边距12px，首工具条margin-top为0，控件高32px，表头/数据行高34px、单元格内边距0 10px；表头背景rgb(216,233,247)、单元格背景rgb(239,247,252)。截图中原标注的大块顶部空白已缩小。多个同名来源部门映射到同一个ERP部门的真实预览显示单个目标主部门。

批量删除只查看15人影响预览（包含admin），返回可确认状态，弹窗无横向溢出；随后取消，未点击真实删除确认。引用检查优先使用绑定/审计记录，避免导入员工逐人扫描所有业务表造成预览缓慢。

角色和部门的真实预览均返回“从列表移除并停止生效，保留历史记录”，随后取消。部门预览初次因传入整个部门对象被严格参数校验拒绝，已修正为仅传id/etag并在真实页面复验通过。

读取弹窗四边均由外层1px边框绘制，表格自身四边0px，首行内部下边框1px、末行末列0px，没有before/after重复描边。普通模式50行时可视宽度与内容宽度均1789px；筛选单行时可视尺寸与内容尺寸均1804×68px，无多余滚动条；空筛选有明确提示。关闭所有本次打开的弹窗并清空筛选，恢复员工列表。

未完成/未执行：独立headless登录态验收（没有可用storage state/凭据）；主库真实删除或保存员工归属；真实企微接口耗时测量；线上部署及验收。已有QA注册脚本依赖旧独占测试服务和账号，未将其直接运行到主库。当前证据为隔离后端/API测试、组件测试、构建和已登录真实页面只读检查，不能替代全部真实业务写入验收。

## 临时资源清理

唯一新建数据库：本地haiqu-postgres上的 `test_employee_management_20261022_163c1`。每轮创建前查询确切库名不存在，不使用keepdb；三轮均由Django测试退出销毁。末轮结束执行 `docker compose exec -T postgres psql -U haiqu -d postgres -Atc "SELECT datname FROM pg_database WHERE datname='test_employee_management_20261022_163c1';"`，退出码0且无记录，确认无残留。

无新增浏览器profile、会话导出、上传文件或备份；复用原有本地标签。源码、测试和本文为交付物保留。OpenAPI输出到 `/dev/null`，未留临时Schema文件。
