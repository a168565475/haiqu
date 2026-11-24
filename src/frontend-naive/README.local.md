# Naive UI 模板本机运行

本目录为官方 SoybeanAdmin **完整示例版**，与 `../frontend` 独立。

- 来源：<https://github.com/soybeanjs/soybean-admin>，`example` 分支。
- 固定提交：`b23be2f177520235345961fe16be9ea460044f0d`。
- 模板版本：2.3.0；Naive UI：2.45.3；Vue：3.5.43。
- 源码归档 SHA256：`A79577F63203934BE7D1567F5463458B29452E524D05A350FD84FF6A06D52015`。
- 本机地址：<http://127.0.0.1:8081>。
- 运行方式：生产构建静态文件，由独立 Docker Compose 项目 `soybean-naive-local` 的 Nginx 服务提供。

## 启动与停止

需要 Docker Desktop 正常运行。构建需要 Node.js（本次使用 24.19.0）、Corepack 和项目指定的 pnpm 12.10.1。

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM\src\frontend-naive'
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
corepack pnpm --version
corepack pnpm install --frozen-lockfile --ignore-scripts --registry=https://registry.npmjs.org
corepack pnpm typecheck
corepack pnpm build
docker compose -f compose.local.yml config --quiet
docker compose -f compose.local.yml up -d --wait
```

保留上游锁文件。安装时跳过生命周期脚本，防止模板的 `prepare` 自动配置父级 ERP 仓库的 Git hooks；本任务不修改父仓库 hooks。

2026-11-24 协作同步检查：冻结依赖安装和生产构建通过；现有 `vue-tsc` 与锁定的 `typescript-native-bridge` 整项目类型检查出现声明解析错误，原目录可复现，尚未解决。具体检查范围和结果见 `../../docs/collaboration_sync_20261124.md`，不能把构建通过等同于类型检查通过。

已有 `dist` 时，只需最后一条启动命令。Docker 运行期间服务会自动重启；修改源码后需要重新构建。

```powershell
docker compose -f compose.local.yml ps
docker compose -f compose.local.yml logs --tail 50
docker compose -f compose.local.yml stop
docker compose -f compose.local.yml start
```

此配置仅监听本机 `127.0.0.1:8081`。不要在父目录执行无 `-f` 的 Compose 命令来管理本模板，父目录 Compose 管理的是原 ERP。

## ERP 登录与数据范围

打开 <http://127.0.0.1:8081/login?redirect=/customers>，直接使用现有 ERP 用户名和密码登录。登录后返回本前端的客户列表；有效的站内返回地址会保留，外部地址、旧8080地址、登录页自身和不存在的页面回退到客户列表。

真实认证使用 `/erp-api/auth/me/`、`login/`、`logout/`，由浏览器 Cookie 保存 Django Session；登录和退出保留 CSRF 校验，不保存密码或本地 Token。刷新和页面导航会核对真实登录状态，退出失败会提示并允许重试。两套前端共用同一浏览器会话，在8081退出也会让该浏览器中的8080 ERP退出。

`/demo-api` 不向外部演示服务转发浏览器 Cookie，也不接收其 Set-Cookie，防止本机 ERP 会话泄漏或被覆盖。同一浏览器中，127.0.0.1 的 8080 与 8081 页面仍共享 ERP Session。

已移除演示快捷账号、短信、注册、找回密码入口，并拦截旧 `/demo-api/auth/login` 等认证路径；ERP 凭据不会发送到演示服务。其他示例接口仍通过 `/demo-api` 访问上游公开演示服务，需要联网，不代表真实业务功能；演示请求失败不会清除 ERP 登录态。

上游部分高级示例可能依赖其他服务、第三方资源或配置，示例菜单存在不代表全部功能已验收。

最初模板部署记录：`../../docs/deployment/frontend_naive_local_20261016.md`；当前认证行为和验收见 `../../docs/deployment/naive_erp_login_20261016.md`。

## 客户列表

侧栏“客户管理 → 客户列表”对应 <http://127.0.0.1:8081/customers>。字段来自现有 ERP，控件、布局、主题和交互沿用本模板；提供搜索、筛选、分页、名称排序、刷新和列设置。点击客户名称或右侧固定“操作”列的“查看详情”进入本站客户详情，返回列表保留筛选、排序和页码。

原 ERP 后端需在本机 8000 端口运行。客户页面通过独立 `/erp-api` 代理读取真实列表与字典，权限与可见客户范围仍由后端决定。未登录访问客户页会进入本应用登录页；会话失效时，可点击“前往登录”，成功后自动返回客户列表。请统一使用 `127.0.0.1`，不要与 `localhost` 混用。

`/erp-api` 只允许认证 login/logout 的 POST，以及已接入业务列表、选项、客户及询盘详情、只读子资源、询盘导出和登录状态的 GET/HEAD；其他业务路径不开放。模板演示令牌不会发往 ERP，ERP Cookie 不会转发至演示服务。客户页面不提供新建、编辑、删除或导出。Nginx 保留原始 Host/Origin 以执行同源 CSRF 校验；本配置只用于当前本机 HTTP 入口。

## 客户管理与客诉列表

一级菜单为“客户管理”，二级依次为客户列表、客诉管理、询盘管理、报价管理、销售订单、任务中心、分析中心。当前前三项接通真实ERP；后四项标注待接入并禁用，没有占位路由，也不会跳往原8080前端。一级标题是展开分组，不是业务页面。

“客诉管理”对应 <http://127.0.0.1:8081/complaints>。沿用模板搜索卡片、表格、标签、分页和列设置，读取原ERP的9个列表字段及6项筛选；默认50条，可选择20/50/100条，筛选与分页保存在URL。提供刷新、当前页CSV导出、错误重试与过期页码返回第一页。后端不支持列表排序，因此不提供排序操作。

客诉统计卡及分析区待用户确认后再加入；新建、详情、编辑、更新进展本轮未接入。接口为 `/erp-api/v1/complaints/` 与 `options/`，沿用真实Session、权限及客户可见范围。修改Nginx配置后先执行 `docker compose -f compose.local.yml exec -T web nginx -t`，通过后执行同命令的 `nginx -s reload`。

客诉与菜单边界测试：`corepack pnpm exec tsx --test src/service/api/complaints.test.ts src/views/complaints/shared.test.ts src/store/modules/route/customer-menu.test.ts`。新增views路由由Vite构建插件自动生成；`pnpm gen-route`是交互式创建页面脚手架，不能用它替代构建生成既有页面的路由类型。验收记录见 `../../docs/deployment/naive_customer_management_complaints_20261016.md`。

新增代码检查：

```powershell
corepack pnpm exec tsx --test src/views/customers/shared.test.ts src/service/api/customers.test.ts src/service/api/erp-auth.test.ts src/router/login-redirect.test.ts
corepack pnpm typecheck
corepack pnpm build
docker compose -f compose.local.yml exec -T web nginx -t
docker compose -f compose.local.yml exec -T web nginx -s reload
```

客户列表验收与修改范围见 `../../docs/deployment/naive_customer_list_20261016.md`。这些代理规则用于当前 Nginx 部署；上游默认开发服务器没有配置 ERP 代理。

## 询盘列表

“客户管理 → 询盘管理”对应 <http://127.0.0.1:8081/inquiries>。使用现有Naive搜索卡片、数据表格、标签、分页和列设置，接入旧ERP的11个业务列；金额按后端产品目标单价乘数量、分币种汇总，时限使用后端当前工作计时结果，保留未分配、缺价及无计时状态。

当前接入9项可见筛选：关键词、状态、来源、国家/地区、负责人、优先级、处理时限、预估金额、产品关键词。接收日期范围控件待用户确认后再加入；原日期、分配状态、已转报价和排序参数保持URL兼容，不额外增加旧页未展示的控件。

默认按接收时间倒序，默认50条/页，可选择20/50/100。导出调用原ERP按当前已应用筛选导出全部可见询盘的CSV接口，最多5000条，超限或权限错误由后端拒绝并在页面提示，不改为当前页导出。

列表开放 `/erp-api/v1/inquiries/`、`options/`、`export/` 的GET/HEAD。点击询盘编号或右侧固定“操作”列中的“查看详情”进入本站详情，返回列表时保留筛选、排序与分页参数。操作列保持可见；移动端取消编号列左侧固定，避免挤占右侧按钮。新建、分配、优先级设置、创建报价、标记无效、删除及旧看板尚未接入。列表初次验收见 `../../docs/deployment/naive_inquiry_list_20261016.md`。

## 询盘详情

详情路径为 `/inquiries/:id`，侧栏保持“询盘管理”选中，不增加独立菜单。保留旧ERP认可的布局：顶部标题与六步状态、左侧需求摘要/产品/附件/沟通时间轴，右侧处理时限/负责人/下一步与相关任务/基础信息与关联单据。桌面右栏524px，窄屏按原信息顺序堆叠；控件、标签和弹窗沿用Naive主题。

当前接入真实只读详情、时间轴分页、相关任务、处理规则与历史、分配历史、产品图片及附件下载。新增代理范围为 `/erp-api/v1/inquiries/:id/` 及其 `timeline/`、`tasks/`、`files-download/`、`files/:fileId/download/`，以及 `/erp-api/v1/inquiry-items/:id/product-image/`，均仅允许GET/HEAD。权限、附件扫描状态和可见范围由ERP后端执行，页面遵循记录权限；局部读取失败可独立重试。

“查看客户”进入本站已接入的客户详情。写操作和未接入的任务、报价、销售订单等详情入口明确禁用并提示待接入，不跳转旧8080页面。旧窗口最大化、最小化、自由缩放及富文本录入尚未加入。刷新会重新核对ERP登录身份，登录后保留本站详情和列表返回目标。

```powershell
corepack pnpm exec tsx --test src/service/api/inquiry-detail.test.ts src/views/inquiry-detail/shared.test.ts src/views/inquiry-detail/navigation.test.ts
corepack pnpm typecheck
corepack pnpm build
docker compose -f compose.local.yml exec -T web nginx -t
docker compose -f compose.local.yml exec -T web nginx -s reload
```

真实数据验收脚本为 `../../qa/naive_inquiry_detail_readonly.cjs`，从项目根执行 `node qa/naive_inquiry_detail_readonly.cjs`，账号通过进程环境变量 `QA_USERNAME`、`QA_PASSWORD` 提供。脚本默认headless，仅允许本机普通登录写请求，结束清理自己的浏览器临时目录。实际覆盖范围与未覆盖数据状态见 `../../docs/deployment/naive_inquiry_detail_20261016.md`。

## 客户详情

详情路径为 `/customers/:id`，侧栏保持“客户列表”选中，不新增菜单项。保留旧ERP的九页签顺序：概览、联系人、时间轴、任务、询盘、报价、样品、订单、客诉；使用Naive卡片、表格、页签、标签及筛选控件。概览保留客户名片、互动时间轴、下一步动作与客户健康分区，窄屏按顺序堆叠。

九页签均查询真实ERP数据。联系人支持查询、状态筛选与分页；时间轴支持事件类型、日期范围、加载更多及“筛选已加载记录”；六类业务记录支持后端已有的筛选与分页，始终限定当前客户。客户关联询盘可进入本站询盘详情。各区独立加载和报错，会话失效时清除旧内容并提示重新登录；返回客户列表仅接受本站客户列表地址。

新增只读代理：`/erp-api/v1/customers/:id/` 及其 `summary/`、`contacts/`、`timeline/`、`entities/`，`/erp-api/v1/customer-entities/:id/addresses/`，以及 `tasks/`、`quotations/`、`sample-requests/`、`sales-orders/` 列表与各自 `options/`，全部仅允许GET/HEAD。认证、数据范围及权限继续由ERP后端校验。

记录沟通、新建、编辑、转移、任务完成等写操作尚未接入。毛利率、应收余额没有可用接口，显示“未接入”；缺失信用快照显示“—”，不当作零值。订单接口没有负责人和日期筛选，因此不提供这两个控件。旧窗口最大化、最小化和自由缩放尚未加入。

```powershell
corepack pnpm exec tsx --test src/service/api/customer-detail.test.ts src/views/customer-detail/shared.test.ts src/views/customer-detail/navigation.test.ts
corepack pnpm typecheck
corepack pnpm build
docker compose -f compose.local.yml exec -T web nginx -t
docker compose -f compose.local.yml exec -T web nginx -s reload
```

真实只读验收从项目根执行 `node qa/naive_customer_detail_readonly.cjs`，进程环境变量使用 `QA_USERNAME`、`QA_PASSWORD`。脚本默认headless，仅允许本机认证登录写请求，结束清理独占浏览器临时目录。实际结果及数据覆盖缺口见 `../../docs/deployment/naive_customer_detail_20261016.md`。
