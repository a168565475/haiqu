# 企业微信第一阶段前端实施记录

日期：2026-10-19。分支：`codex/wecom-phase1`。执行依据：`docs/superpowers/plans/2026-10-19-wecom-phase1.md` 与已批准的 `qa/wecom_phase1_20261019/preview.html`。本报告仅覆盖前端子任务，不替代主任务后端、真实 API、页面视觉和企业微信工作台验收报告。

## 实施结果

- `/settings/wecom`：接入配置、员工绑定两个标签；配置与状态来自真实 API，没有预置员工或配置成功替身。
- CorpID、AgentId、ERP 地址沿用批准预览只读展示；保存 Secret 和登录开关使用配置 ETag。检查连接只能针对已保存配置，检查结果明确不等于真实工作台登录通过。
- 消息回调凭据独立区域包含 Token、EncodingAESKey，默认折叠，摘要始终显示两项配置状态；本期仅保存，不提供消息事件或模板操作。
- 密钥均为密码输入，不回填已保存值；提交后立即清空，空白通过 API 层省略以保留旧值。没有 LocalStorage、日志或 URL 凭据存储。
- 绑定弹窗使用 AppWindowDialog；员工来自真实候选 API，显式确认身份后携带员工 ETag 提交。409 保留冲突说明且不覆盖/合并，412 要求重新读取员工。绑定记录只读取本模块审计。
- 新增管理员导航入口；绑定列表跳转原权限管理，角色不在企微页另建。
- 启用开关旁说明“先完成已有员工绑定，再启用工作台入口”。
- `/auth/waiting-role` 不使用 ERP 业务壳，保留会话、允许检查授权和退出。授权后回首页，退出失败不清空账号或伪装成功。
- `/auth/wecom-error` 仅使用6个固定公开错误码映射，未知查询值显示通用说明，不回显查询内容。已有会话可显式退出，失败继续保留。
- `AuthUser.waiting_for_role` 为可选字段；路由守卫限制待授权账号，普通密码账号保持原流程。窄响应拦截器只处理 `/api/v1/` 的 `403/WECOM_ROLE_REQUIRED`，刷新会话后进入等待；并发拒绝共用刷新，刷新失败保留受限身份，认证接口自身不递归触发。
- API 错误展示保留已知 JSON envelope 的安全 message 和已知 field_errors；未知响应、HTML 错误页和500仍使用通用说明。字段和审计均通过 Vue 文本转义渲染，没有 v-html。

## 修改文件

新增：

- `src/frontend/src/types/wecom.ts`
- `src/frontend/src/api/wecom.ts`、`wecom.spec.ts`、`wecomSession.ts`、`wecomSession.spec.ts`
- `src/frontend/src/router/wecomGuard.ts`、`wecomGuard.spec.ts`
- `src/frontend/src/views/settings/WeComSettingsView.vue`、`WeComSettingsView.spec.ts`
- `src/frontend/src/views/auth/WaitingRoleView.vue`、`WeComErrorView.vue`、`WeComAuthViews.spec.ts`、`wecom-auth.scss`

局部修改：

- `src/frontend/src/App.vue`
- `src/frontend/src/router/index.ts`
- `src/frontend/src/stores/auth.ts`、`auth.spec.ts`
- `src/frontend/src/types/auth.ts`
- `src/frontend/src/components/navigation/AppSidebar.vue`、`AppSidebar.spec.ts`

未修改预览、后端、项目 AGENTS、全局主题及原有脏文件。工作期间观察到其他并行任务继续修改不同文件，未覆盖或清理。未新增依赖、暂存、提交或部署。

## 实际验证

运行目录：`E:\workspace\_project\project001_haiqu_ERP_CRM\src\frontend`。

```powershell
npm run test -- src/stores/auth.spec.ts src/api/wecom.spec.ts src/views/settings/WeComSettingsView.spec.ts src/router/wecomGuard.spec.ts src/api/wecomSession.spec.ts src/views/auth/WeComAuthViews.spec.ts src/components/navigation/AppSidebar.spec.ts
npm run type-check
```

最终定向 Vitest：7文件、93项通过，退出码0（18.75秒）；类型检查 `vue-tsc -b` 通过，退出码0。修改旧文件的 `git diff --check -- <本任务精确文件列表>` 通过；仅有仓库既定 LF/CRLF 提示。

行为覆盖：等待会话保持/授权刷新，普通403不拦截，企微403并发刷新和网络失败，认证接口防循环，六个公开码及未知输入，旧账号门禁，Secret/Token/AES状态及清空，空白保留，ETag传递与更新，配置412，绑定明确确认与409，无管理权限，空列表与读取失败，审计空态，管理员导航可见性。

测试先行证据：新增“待授权账号保持登录”断言先失败（getter尚不存在），实现后通过；“保留未迁移/加密密钥/绑定冲突原因及字段错误”2项先失败，错误适配修复后通过。新增导航用例曾因其测试路由表缺少已有邮件账户路由失败，补齐测试环境后通过。

最后仅补充窄屏折叠区排版，未增加功能；完整生产构建和视觉检查交由主任务统一执行，避免并行重复构建。

### 真实页面检查后的标题局部修复

主任务实际页面测得桌面和 390px 视口的标题均为 34px。源码根因为 `PageContainer.vue` 的 `h1` 规则以 `!important` 固定 34px/44px，同时 `settings-theme.scss` 的 ID 级选择器把标题设为衬线字体、600 字重。原本企业微信页的 scoped 规则没有覆盖这两层。

仅在 `WeComSettingsView.vue` 的 scoped 样式内，以 `#erp-main-content .wecom-page h1` 局部恢复批准的 `var(--erp-font-body)` 无衬线字体、700 字重、桌面 36px/44px；小于等于 640px 的同范围规则恢复 28px/38px。不改页面容器、全局主题或其他页面。

新增桌面/窄屏两项源样式回归断言，先确认 2 项失败、原 6 项通过，修复后运行 `npm run test -- src/views/settings/WeComSettingsView.spec.ts`：8/8 通过，退出码 0；随后 `npm run type-check` 通过，退出码 0。源码断言不能证明浏览器的最终计算样式，实际多视口复验由主任务继续执行。

主任务最终复验：实际 headless 页面 40 项全部通过，10 张最终截图；计算样式已确认桌面 36px/44px、700 字重、无衬线字体，390px 为 28px/38px。最终生产构建再次通过（37.11 秒）。标题修复之前全量 Vitest 使用 `--maxWorkers=2` 为193文件1546项通过；标题修复之后执行上述组件8项与类型检查，没有重复全套。统一QA结果为PASS_WITH_GAPS，不能替代真实企业微信身份链路、业务库或公网部署验收。

## 验收边界与资源

- 本子任务未运行后端测试、主库迁移、真实写库、企业微信私有 API 或部署。
- 单元测试使用内存中的 API 替身，仅验证前端行为，不等于真实登录/真实绑定验收。
- 尚未在本子任务运行真实浏览器截图、DOM/计算样式、边框/滚动/多视口验证；不能声明已通过完整视觉门禁。主任务已接手隔离真实 API 的页面验收。
- 既有主题依赖及 AppWindowDialog 沿用项目版本；没有安装运行环境或依赖。
- 没有创建独立测试数据库、上传副本、导出文件、浏览器临时目录或临时服务；测试组件均卸载，响应拦截器和内存适配器在测试结束复原。未清理来源不明的现有工具缓存。新增源码、测试与本报告属于交付物保留。
