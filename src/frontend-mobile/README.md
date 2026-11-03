# 海趣车间手机端

基于用户选定的 [vue3-vant-mobile](https://github.com/vue-zone/vue3-vant-mobile) v3.14.1，来源和移植说明见 [UPSTREAM.md](UPSTREAM.md)。独立 Vue 3 / TypeScript / Vite / Vant / Pinia / UnoCSS 工程，共用海趣 ERP 后端，不依赖电脑端源码或布局。

范围：生产列表、领料申请、班组长多人报工、金工/车缝半成品入库、装配成品入库提交、相关记录。仓库确认出库和入库仍在电脑端 ERP。登录使用真实 ERP 账号密码、Django Session 和 CSRF，支持身份版本冲突处理，不保存登录 Token。

首页先读取 `GET /api/v1/workshop-mobile/context/` 返回的车间切换能力。具备领料或报工全车间查看范围的管理账号可切换金工、裁剪、车缝、装配四个 ERP 计划类别，默认金工，不显示“全部”；仅获指定车间授权的账号隐藏选项卡，合并显示其授权范围内计划。实际车间 ID 继续用于进入作业页面，切换能力不增加任何查看或写入权限。

手机端复用 ERP 企业微信认证：企业微信内打开 `/m/` 时，先核验现有 Session；尚未登录才通过 `/api/auth/wecom/start/?next=%2Fm%2F` 自动授权，成功回到手机端。普通浏览器保留 ERP 账号密码登录，不另建账号和权限体系。账号绑定、员工状态和授权范围仍由既有后端校验。

企业微信应用入口填写正式站点的 `https://erp.cnhitree.com/m/`（待本次代码部署后启用），不要填写本机 `8082`。复用 ERP 已配置的企业微信应用、可信域名和 `/api/auth/wecom/callback/` 回调；同源 `/api/`、Session Cookie 与 `/m/` 深链 HTML 回退须同时可用。入口配置不等于已发布或已完成真机登录验收。

授权失败进入 `/m/auth/wecom-error`，未分配有效权限进入 `/m/auth/waiting-role`；配置未就绪、绑定待确认、员工停用及网络问题均显示实际状态。安全业务深链通过 `next` 保留。自动授权每个浏览器会话最多尝试一次，成功登录后重置；Cookie/会话存储异常可用密码入口或明确重试。管理员切换身份时沿用当前 Session，保留返回管理员凭据时禁止自动覆盖，可从提示返回 ERP 恢复身份。

## 本机开发

Node 20.19+（20.x）或 22.12+（本次使用24），通过项目固定 pnpm10.27.0运行；无需改全局包管理器。

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM\src\frontend-mobile'
npx --yes pnpm@10.27.0 install --frozen-lockfile --ignore-scripts
npx --yes pnpm@10.27.0 dev
```

访问 http://localhost:8082/m/ 。API代理默认 http://localhost:8000，保持 `/api` 原路径；可通过进程环境 `VITE_PROXY_TARGET` 指向对应开发后端。不要配置公网代理目标。

首次安装后执行 `build` 会先生成文件路由/组件类型，再做类型检查；也可先启动一次 `dev` 生成类型。

```powershell
npx --yes pnpm@10.27.0 build
npx --yes pnpm@10.27.0 type-check
npx --yes pnpm@10.27.0 test
```

构建输出 `dist/`，生产部署需将其放在 `/m/`，配置该路径的 HTML 回退，并将同源 `/api/` 转发到既有后端。开发服务器不等于生产部署。

## Docker Compose

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
docker compose -f compose.yml -f compose.mobile.yml build frontend-mobile
docker compose -f compose.yml -f compose.mobile.yml up -d --no-deps frontend-mobile
```

附加文件只增加手机服务，默认监听本机127.0.0.1:8082。局域网试用时先核实可信局域网、现有防火墙与后端允许主机；设置 `MOBILE_HOST_IP=0.0.0.0` 后重建该服务绑定即可。不自动修改防火墙或开启公网入口。

## 使用与验证边界

- 员工须具备相应的领料查看/新增/提交、报工查看/新增和车间数据范围；手机入口不能代替后端授权。
- 进度是工序报工次数口径，缺少配置或权限时不显示成0%。
- 领料提交可能包含“草稿已保存、提交待核对”，按页面提示恢复同一笔，不重复建单。
- 报工网络结果不明时保留同一请求编号和内容；确认完成计划须明确选择。
- 装配计划的“成品入库”进入 `/m/finished-receipt?schedule_product_id=...`，沿用 `assembly-finished-receipts/preview/` 和提交接口，仅创建待入库单，仓库确认后增加库存。额度由后端按订单容差、装配最低累计报工、已提交数量共同核定。
- 入库选项通过 `GET /api/v1/workshop-mobile/finished-receipt-options/?schedule_product_id=...` 读取，只返回正常成品仓、库区、库位及剩余箱位；要求入库新增权限和同 ERP 的装配来源范围，无需扩大库存查看权限。网络结果不明时保持原编号、原内容核对；浏览器不能保存待核对请求时停止提交。
- 金工、车缝计划的“半成品入库”进入 `/m/semi-receipt?schedule_product_id=...&plan_category=METAL|SEWING`；裁剪不提供该入口。沿用 ERP 半成品查看、新增权限及来源范围，preview 返回实际候选明细、整数数量额度和半成品仓库区（zone_id，不是成品库位）。提交只生成待确认单，不直接增加库存。
- 半成品复用 `semi-finished-receipts/preview/`、提交及 `by-request/{request_id}/` 接口。金工按现行加工依据判断可入支数，车缝按套数额度；不自行补入后端未返回的物料。未知提交结果先按原编号回查，再按服务端结果处理原请求，禁止换新编号重复提交。
- 暂无离线写入、PWA缓存、手机仓库确认或发布到正式站点。
- 本次验证和真实流程缺口见 `qa/mobile_workshop_20261031/`。

匿名只读浏览器检查已登记：在项目根目录运行 `python qa/run.py workshop-mobile --read-only`。需要已有桌面工程的 `playwright-core` 和本机 Chrome/Edge；脚本后台运行，不登录、不写业务。普通角色登录、真实申请/报工和真机检查是独立的未覆盖项。
