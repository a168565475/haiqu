# haiqu ERP 统一 QA 入口实施设计计划

> 本文件保留第二阶段设计约束，并记录后续最小实现状态；它不是业务代码改造清单。

**Goal:** 在不删除或改写历史 QA 脚本的前提下，设计一个能够按业务模块调用已登记脚本、统一收集结果并默认保护数据库的 QA 入口。

**Architecture:** 当前由一个 Python 标准库 CLI `qa/run.py` 读取显式注册表，按注册顺序以无 shell 注入的子进程调用旧的 Node/Python 脚本。注册表保存脚本分类、风险级别、前置条件、账号变量、浏览器模式和证据路径；入口只做编排、门禁、日志采集和报告汇总，不把历史脚本改造成另一套测试框架。

**Tech Stack:** Python 3.13 标准库（统一入口）、Node.js（现有 `.cjs/.js` 脚本）、项目已有 `playwright-core` 或经过确认的 Playwright 运行时、Markdown/JSON 报告；不新增 Playwright 测试框架，不要求 `@playwright/test`。

**Spec:** `docs/QA_ANALYSIS_REPORT.md`、项目 `AGENTS.md` 第 2、3、5、7 节，以及本轮用户提出的第二阶段要求。

> **实施状态（2026-10-13）：** 用户已确认设计并进入实现。`qa/run.py`、`qa/runner_manifest.json` 和 runner 契约测试已创建；现有脚本仍未被重写。真实领料写入继续不纳入默认 `all`，本次专项验收在用户明确授权后以独立无头脚本完成。

## 全局约束

- 不删除、重命名、重写或自动改造任何历史 QA 脚本。
- 旧脚本必须仍可用原命令独立运行；统一入口只是调用者，不是新的业务逻辑层。
- 未经明确授权，不执行会向开发库或真实业务库写入的脚本；`all` 默认不包含写库步骤。
- 未登记、风险为 `UNKNOWN`、浏览器模式未确认或前置条件缺失的脚本不得被入口“猜测运行”。
- 账号、密码、Session Cookie、数据库连接串和真实业务数据只从环境或外部安全配置读取，绝不写入注册表和报告。
- 设计阶段不改业务代码；当前实现阶段只允许新增/修改 QA 入口、注册表、QA 规范和 runner 测试，不改业务代码。
- `qa/` 的历史证据和运行产物继续忽略；当前已增加只针对 `qa/run.py`、注册表和契约测试的精确 Git 例外，不放开其他 QA 文件。

## Review Focus

以下边界必须在实现阶段由自动化检查固定下来：

1. **未登记脚本或路径失效**：应返回 `UNKNOWN`/配置错误，不能按文件名通配执行。对应测试：`--list`、失效路径 dry-run。
2. **账号或地址缺失**：应返回 `BLOCKED`，不应启动浏览器或泄露秘密。对应测试：缺少必需环境变量时的预检。
3. **写库风险**：默认应跳过或拒绝 `isolated-write`、`real-write`，不能因脚本名含 `readonly` 就放行。对应测试：无授权运行 `all` 和显式写库条目。
4. **浏览器模式不明确**：日常入口只接受已确认的 headless 条目；模式 `UNKNOWN` 应阻断。对应测试：注册表校验和阶段 3 的 headless 门禁。
5. **子进程失败及证据缺失**：应保留 stdout/stderr、退出码和已有截图/JSON 路径，并在统一报告中标出失败类别。对应测试：非零退出、超时和不存在的证据文件。

## 1. 当前事实与设计边界

### 1.1 已确认事实

| 事实 | 对设计的影响 |
| --- | --- |
| `qa/` 有大量历史目录和脚本；本次静态盘点得到 793 个 `.cjs`、97 个 `.js`、20 个 `.mjs`、13,820 个 `.py` 文件，其中很多是源码副本、浏览器配置或证据文件 | 不能把目录扫描结果当作测试套件；必须采用显式白名单 |
| 未发现 `playwright.config.*`、标准 `e2e/` 目录、`@playwright/test` 配置或统一 E2E 命令 | 入口必须兼容现有脚本，不能假设 Playwright Test runner 生命周期 |
| CJS 中 496 个直接启动浏览器的脚本静态出现 `headless: true`，未发现 `headless: false`；但另有脚本的启动模式无法仅由统一扫描确认 | “多数已后台运行”不等于所有脚本已经被统一门禁；模式未知的条目必须先复核 |
| `src/frontend/package.json` 有 `playwright-core`，没有 `playwright` 或 `@playwright/test`；部分脚本 `require('playwright')` | 注册表要记录运行时来源，入口不能在运行时偷偷安装依赖 |
| 根目录无 `package.json`、无统一 `qa`/`e2e` script；`scripts/` 不是现成 QA 入口 | Python CLI 应从项目根目录启动，调用旧命令而不是依赖 npm script |
| `AGENTS.md` 明确要求真实数据库/API 验收、写库 QA 需授权，并把统一浏览器入口标为 UNKNOWN | 默认安全模式和“UNKNOWN 阻断”是硬约束 |
| `qa/`、`output/` 被忽略；历史证据与源码副本混在一起 | 运行产物默认放在本地忽略目录；正式纳入版本控制的入口需精确例外 |

### 1.2 设计不解决的问题

- 不在本阶段重新分类 793 个脚本，也不替每个历史场景猜测业务前置数据。
- 不在入口中补造测试账号、数据库种子、迁移或业务 API。
- 不把 MCP 浏览器调用封装进本地 runner；MCP 仍是失败定位和特殊视觉场景的可视化工具。
- 不把截图、历史报告或一次人工通过当作 API/数据库自动验收结果。

## 2. 目标命令契约

当前入口提供以下稳定命令：

```text
python qa/run.py --list
python qa/run.py production
python qa/run.py quotation
python qa/run.py inquiry
python qa/run.py all
python qa/run.py production --dry-run
python qa/run.py production --read-only
```

### 2.1 参数语义

| 参数 | 语义 | 默认行为 |
| --- | --- | --- |
| `module` | `production`、`quotation`、`inquiry` 或 `all` | 必填；未知模块返回用法错误 |
| `--list` | 列出已登记条目、分类、风险和启用状态 | 不启动任何子进程 |
| `--dry-run` | 只做注册表、路径、运行时和环境变量预检并打印解析后的 argv | 不启动浏览器、不访问 API/数据库 |
| `--read-only` | 只允许风险为 `read-only` 的条目 | 写入或未知条目标为 `BLOCKED`，不强行执行 |
| `--report-dir PATH` | 指定本次 JSON/Markdown 报告目录 | 默认 `output/qa-runs/<run-id>/`，不写入 `docs/` |
| `--timeout SECONDS` | 覆盖单条脚本的最大运行时间 | 仅允许缩短或在安全上限内覆盖注册值 |
| `--continue-on-failure` | 某条独立只读用例失败后继续其他用例 | 基础设施/配置错误仍应阻止后续不安全步骤 |
| `--allow-db-write` | 明确允许执行注册为 `isolated-write` 的条目 | 未提供时隔离库写入条目不运行 |
| `--allow-real-db-write` | 明确允许执行注册为 `real-write` 的条目，并配合环境确认变量 | 未提供时真实业务库写入条目不运行；`real-write` 不由 `all` 自动解锁 |

`--headed`、`--mcp` 或“打开 Chrome 观察”不属于日常入口命令。可视定位应由单独的调试步骤发起，并且不改变普通入口的默认行为。

### 2.2 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 所有实际执行的条目通过，且没有未处理的阻断 |
| `1` | 至少一条已执行用例失败、超时或进程异常退出 |
| `2` | CLI 参数、注册表格式或运行时配置错误 |
| `3` | 前置条件缺失、账号/地址缺失或安全门禁阻断 |
| `4` | 请求的模块没有已登记条目，或条目仍为 `UNKNOWN` |

退出码只反映自动化过程，不宣称业务功能在未执行的范围内通过。

## 3. 文件布局与职责（当前实现）

| 文件 | 状态 | 单一职责 |
| --- | --- | --- |
| `qa/run.py` | 已创建（最小实现） | CLI 参数解析、注册表加载、headless/风险预检、子进程调度、结果归一化和报告写出 |
| `qa/runner_manifest.json` | 已创建（首批候选） | 可审查的脚本白名单、模块顺序、风险、前置条件、账号变量和证据约定；不含秘密 |
| `qa/test_run.py` | 已创建 | runner 的路径安全、headless、环境隔离和报告脱敏契约测试 |
| `output/qa-runs/<run-id>/` | 运行时生成 | stdout、stderr、JSON/Markdown 汇总和脚本产生的临时索引；不纳入源码提交 |
| `docs/QA_RUNNER_DESIGN.md` | 本阶段新增 | 保存设计、门禁、未决问题和实施验收标准 |

### 3.1 关于 `qa/` 被忽略

历史 `qa/` 文件和运行产物继续被忽略；`.gitignore` 已增加精确例外，仅保留 `qa/run.py`、`qa/runner_manifest.json` 和 `qa/test_run.py` 作为可跟踪入口源码。旧脚本没有被删除或改写。

## 4. 注册表设计

注册表只登记“已经逐个读过、已确认可以在该环境运行”的脚本；不按 `*_e2e.cjs`、目录名或日期自动发现。

### 4.1 最小字段

```json
{
  "version": 1,
  "modules": {
    "production": [
      {
        "id": "production-scheduling-business",
        "path": "qa/production_scheduling_business_e2e.cjs",
        "runtime": "node",
        "args": [],
        "category": "business",
        "risk": "real-write",
        "database_target": "UNKNOWN",
        "browser_mode": "headless",
        "account_required": true,
        "required_env": [
          "PRODUCTION_SCHEDULING_QA_BASE_URL",
          "PRODUCTION_SCHEDULING_QA_BROWSER_PATH"
        ],
        "cwd": ".",
        "timeout_seconds": 300,
        "enabled": false,
        "order": 10,
        "artifacts": ["qa/production_scheduling_business_e2e*.json"]
      }
    ]
  }
}
```

字段约束：

- `id` 在全注册表唯一；`path` 必须是项目根目录下的相对路径，并拒绝 `..` 越界。
- `runtime` 仅允许 `node`、`python`；Node 条目由 `node` 执行，Python 条目优先使用当前解释器（`sys.executable`）。
- `category` 使用第一阶段报告的分类：`business`、`page`、`visual`、`data_init`、`api_helper`、`evidence`。
- `risk` 仅允许 `read-only`、`isolated-write`、`real-write`、`unknown`。`database_target` 需同时说明主开发库、专项隔离库、快照或 `UNKNOWN`。
- `browser_mode` 允许 `none`、`headless`、`headed`、`unknown`。日常模块入口只接受 `none` 或已确认的 `headless`；`headed`/`unknown` 必须阻断并报告原因。
- `account_required` 和 `required_env` 只描述是否需要账号及变量名，不保存变量值；报告只列变量名和“已提供/缺失”。
- `enabled=false` 是默认值，直到该条目完成路径、运行时、前置数据、写入范围和结果文件审查。
- `artifacts` 是证据路径模式，不代表文件一定存在；入口应记录“声明但缺失”，不能伪造通过。

### 4.2 模块与候选条目

下面是从当前目录核对出的候选及首批登记示例；是否扩大真实业务回归范围仍需逐项确认：

| 模块 | 已发现的候选 | 当前处理 |
| --- | --- | --- |
| `production` | `qa/production_scheduling_business_e2e.cjs`、`qa/production_tasks_1920_e2e.cjs`、`qa/product_material_1920_e2e.cjs`、`qa/material_issue_v1_1920_e2e.cjs`、`qa/material_inventory_1920_e2e.cjs`、`qa/production_data_e2e.cjs` | 逐个确认真实写入范围、账号、数据前置和浏览器模式后再登记；业务写入条目默认禁用 |
| `quotation` | `qa/quotation_create_dialog_e2e.cjs`、`qa/quotation_flow_confirmed_1920_e2e.cjs`、`qa/quotation_downstream_mapping_20260914_e2e.cjs`、`qa/quotation_comments_20260914_e2e.cjs`、`qa/quotation_sample_image_mapping_20260914_e2e.cjs`、`qa/quotation_prototype_alignment_1920_e2e.cjs` | 页面、视觉和业务写入混杂，不能按文件名批量启用 |
| `inquiry` | `qa/inquiry_list_width_probe_20260924.cjs`、`qa/inquiry_detail_width_probe_20260924.cjs`、`qa/inquiry_customer_table_density_1920_e2e.cjs`、`qa/page_loading_optimization_20260915/inquiry/measure.cjs`、`qa/page_loading_optimization_20260915/edit_inquiry.cjs` | 先区分只读测量、模拟认证和真实保存；缺少前置信息时标记 `UNKNOWN` |
| `all` | 上述模块中 `enabled=true` 的条目，按注册表 `order` 排序 | 不等于扫描并运行全部 793 个 CJS；默认排除 `data_init`、`real-write` 和 `unknown` |

数据初始化脚本、迁移脚本和 API 辅助脚本可以作为某个场景的显式前置步骤，但不能因为位于同一目录就被 `all` 隐式执行。每个前置步骤必须单独登记风险和授权方式。

## 5. 调度流程

入口实现应按以下顺序执行，任何一步失败都要形成可审计状态：

1. **加载注册表**：校验 JSON 版本、字段枚举、路径边界、模块名和唯一 ID。
2. **选择条目**：按模块和 `order` 取出 `enabled=true` 的条目；`all` 只合并已批准模块，不扫描目录。
3. **预检运行时**：确认 Node/Python 可执行文件、脚本存在、工作目录存在；不自动安装依赖。
4. **预检环境**：只检查必需变量是否存在，禁止把密码或 Cookie 打印到终端/报告。
5. **执行安全门禁**：`--read-only` 只放行 `read-only`；`isolated-write` 需 `--allow-db-write`，`real-write` 需 `--allow-real-db-write` 和环境确认；`real-write` 默认仍不进入 `all`；`unknown`、`headed`、`unknown browser` 一律阻断。
6. **启动子进程**：使用 argv 数组和 `shell=false`，在注册的 `cwd` 下执行；不拼接未经校验的 shell 字符串。
7. **收集结果**：保存退出码、超时、开始/结束时间、耗时、stdout/stderr 文件、声明的证据路径和失败分类。
8. **写出报告**：先写 JSON，再从同一结果对象生成 Markdown，避免两份报告内容漂移。
9. **计算退出码**：按第 2.2 节映射；所有被阻断或未登记的范围必须在报告中显式列出。

入口不得捕获并吞掉脚本的内部异常；脚本非零退出应保留原始输出并归类为 `FAIL`，而不是转换成假成功。

## 6. 统一报告契约

每次运行目录建议包含：

```text
output/qa-runs/<run-id>/
  report.json
  report.md
  cases/<case-id>.stdout.log
  cases/<case-id>.stderr.log
```

JSON 顶层字段：

| 字段 | 内容 |
| --- | --- |
| `schema_version` | 报告结构版本 |
| `run_id`、`module`、`mode` | 本次运行标识、模块和 `normal/read-only/dry-run` 模式 |
| `started_at`、`finished_at`、`duration_ms` | 时间和耗时 |
| `summary` | `pass/fail/blocked/skipped/unknown` 数量 |
| `cases[]` | 每条脚本的完整结果 |
| `environment` | 变量名及 `provided/missing` 状态，不含值 |
| `runner_version`、`git_revision`（可选） | 入口版本和源码修订标识 |

`cases[]` 至少包含：`id`、`path`、`runtime`、`category`、`risk`、`database_target`、`browser_mode`、`account_required`、解析后的安全 argv（脱敏）、`status`、`exit_code`、`duration_ms`、stdout/stderr 路径、证据路径、阻断原因或失败分类。

报告状态定义：

- `PASS`：进程退出码为 0，且注册表要求的最低结果检查通过。
- `FAIL`：脚本非零退出、超时、进程异常或已执行断言失败。
- `BLOCKED`：安全门禁、账号、地址、运行时或前置条件缺失，脚本未启动。
- `SKIP`：因显式筛选或模块不包含而未执行，并记录原因。
- `UNKNOWN`：注册信息或证据不足，不能安全判断。

报告不得保存密码、Session Cookie、Authorization 头、完整数据库 URL 或未脱敏业务记录；截图和脚本已有 JSON 只记录相对路径。

## 7. 与现有脚本的兼容策略

1. 入口调用的 argv 应与历史手工命令一致，例如 `node qa/production_scheduling_business_e2e.cjs`；不向脚本注入隐藏参数。
2. 历史脚本仍可直接运行；删除或改写脚本不是 runner 的职责。
3. Python 脚本使用当前项目解释器，Node 脚本使用环境中已验证的 `node`；Playwright 包路径由脚本和环境负责，入口只做预检和记录。
4. 入口不依赖 `playwright.config.*`、`@playwright/test` 或 MCP；现有自管理 `chromium.launch` 生命周期保持不变。
5. 失败时优先保留脚本自己的截图、JSON、trace 和日志；runner 只追加统一索引，不复制海量历史证据。
6. 账号变量遵循脚本已有命名（例如 `E2E_*`、`PRODUCTION_SCHEDULING_QA_*`、`PM_QA_*`），不在入口层硬编码默认密码。

## 8. 实施阶段拆分与当前进度

### Task 1：冻结注册表格式和首批只读白名单（已完成基础实现）

**Files:**

- Create: `qa/runner_manifest.json`
- Modified: `.gitignore`（只增加入口、注册表和契约测试的最小例外）
- Test: dry-run/list 命令的配置校验

- [x] 复核首批登记脚本的路径、运行时、数据库目标和浏览器模式；账号变量仍按真实环境另行提供。
- [x] 只登记明确 `read-only` 且 `browser_mode` 已确认的少量 smoke 条目；fixture 视觉条目保持 `enabled=false`。
- [x] 运行 `python qa/run.py --list` 并核对无秘密值、无失效路径。

### Task 2：实现最小 Python 调度器（已完成）

**Files:**

- Create: `qa/run.py`
- Test: `python qa/run.py --dry-run`、缺环境变量、失效路径、非零子进程和超时场景

- [x] 使用标准库解析参数、加载注册表和校验路径。
- [x] 使用安全子进程调用收集 stdout/stderr，禁止 `shell=True`。
- [x] 实现退出码和风险/headless 门禁；真实写入仍需双重显式授权。

### Task 3：统一 JSON/Markdown 报告（已完成基础实现）

**Files:**

- Modify: `qa/run.py`
- Test: 一次 dry-run、一次通过、一次失败和一次阻断的报告字段快照

- [x] 由同一结果对象生成 `report.json` 和 `report.md`。
- [x] 通过契约测试验证报告不包含密码、Cookie、Authorization 或完整数据库连接串。
- [x] 脚本失败时保留原始 stdout/stderr 和证据路径索引。

### Task 4：按模块逐步启用（首批登记，真实账号仍待环境确认）

**Files:**

- Modify: `qa/runner_manifest.json`
- Test: `production`、`quotation`、`inquiry` 的 dry-run/read-only smoke

- [x] 先登记不写业务库的条目；每次运行记录前置条件和账号状态。
- [x] 把生产领料真实写入链路留到专项验收，不放入默认 `all`。
- [x] `all` 只组合白名单条目，不扫描未登记脚本，不自动初始化、迁移或累计业务数量。

### Task 5：与第三阶段 headless 规则衔接（已完成静态门禁）

**Files:**

- 已登记 Playwright 脚本及其运行规则文档
- Test: headless 断言、失败截图/trace 和可视定位单独流程

- [x] 静态扫描确认当前可识别的 503 个 Playwright 启动点均明确 `headless: true`，未发现违规项。
- [x] 普通入口拒绝 headed/unknown；可视模式仅作为失败定位、视觉验收、尺寸/动画/拖拽等独立流程。

## 9. 已执行的实现验收

- `python qa/run.py --list` 已列出首批登记条目，未启动浏览器。
- `python qa/run.py production --read-only --dry-run` 已完成预检并生成 JSON/Markdown 报告。
- `python qa/run.py --audit-headless` 已扫描 503 个启动点，违规数为 0。
- `python -m unittest qa/test_run.py -v` 已通过 6 个 runner 契约测试。
- `all` 只执行注册表白名单；旧脚本仍可独立运行，runner 不调用 MCP、不打开可视浏览器窗口。
- 统一 runner 的首批 live smoke 仍有 3 项因 `development-auto-login` 已关闭而失败；这不应被解释为业务通过。
- 专项报告 `docs/QA_REPORT_PRODUCTION_MATERIAL_ISSUE.md` 已记录一次经授权的真实半成品领料：无头浏览器完成创建、提交、预览、确认和数据库流水回读；普通原材料分支发现 `pieces_per_bar` 500 缺陷，未修改业务代码。

## 10. 待用户确认的决策

以下问题未在当前仓库事实中得到答案，实施前不能自行猜测：

1. 首批正式回归白名单是否扩大；当前登记仍是保守 smoke 集合，不等于完整业务回归。
2. `production`、`quotation`、`inquiry` 的正式前端/API 地址和测试账号变量来源。
3. 哪些脚本可以写专项隔离库，哪些脚本绝对禁止写主开发库；真实写库是否永远只允许手工直接命令。
4. 是否需要把更多 QA 历史脚本纳入版本控制；当前只保留统一入口和契约测试。
5. 统一报告是仅保存在本地 `output/qa-runs/`，还是需要另设脱敏后可提交的历史摘要目录。

## 11. 本阶段交付边界

设计已获确认，最小 runner 和 headless 静态审计已经实现并完成契约验证。当前仍有明确边界：首批 live 脚本在现有环境中因 `development-auto-login` 返回 404（系统要求独立账号密码）而不能报告通过；没有账号、地址和写库授权时，runner 必须保留 `FAIL`/`BLOCKED`，不能改成假成功。生产领料真实写入已作为专项验收完成一笔半成品场景，普通原材料分支仍待修复；本阶段未修改业务代码。
