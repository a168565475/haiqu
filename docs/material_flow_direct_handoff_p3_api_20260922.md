# P3 加工完成与备注结清接口

适用范围：已确认的 P3 后端。正式页面接入、厂内加工件外发分配及回货属于 P4。主业务库尚未应用新增迁移。

## 1. 接口与权限

基础路径 `/api/v1/metal-processing-sources/`。使用现有 Session 登录及 CSRF。路径中的 `{id}` 始终是具体领料明细 UUID，不是新增加工来源 UUID。

| 方法及路径 | 权限 | 返回 |
| --- | --- | --- |
| GET 基础路径 | `material_issues.view_metalprocessingsource` | `data` 为来源数组，`meta` 为 page/page_size/total/total_pages |
| GET `{id}/` | 同上 | `data` 为来源详情，响应头含 ETag |
| GET `{id}/closure-preview/` | 同上 | 当前数量、能否结清、阻止原因、已存在的结清记录 |
| POST `{id}/completions/` | `material_issues.register_metalprocessingcompletion` | 完成记录写入后的来源及 operation_id |
| POST `{id}/close/` | `material_issues.close_metalprocessingsource` | 结清后的来源、差额、备注、操作人与时间 |

列表支持 `production_task_id`、`product_line_id`、`component_identity`、`issue_id`、`issue_number`、`status` 和原有分页参数。状态为 OPEN/CLOSED。上述 UUID 和状态参数先校验，不能用错误参数绕过范围过滤。

所有操作都复用原领料可见范围；新增动作权限不会自动获得所有订单的查看范围。本期没有自动给正式账号分配权限。来源来自已出库、金工计划对应的管材原料明细。读取未登记来源不会创建数据。

## 2. 写入示例

以下只是契约示例，UUID 不是实际单据。写入前读取具体来源详情，取得 ETag，在请求头带 `If-Match` 和有效 CSRF 信息。

完成登记：

```json
{
  "request_id": "e742f313-abfb-4f4c-a831-2c8984383d35",
  "good_pieces": 200,
  "completion_date": "2026-09-22"
}
```

备注结清：

```json
{
  "request_id": "f6314d01-fb35-4d77-a362-98d5a1e09b12",
  "remark": "现场数量已核对，剩余差额按实际记录结清。"
}
```

`good_pieces` 为正整数，不接受小数、布尔值、无效文本或超上限数量。完成日期仅校验有效日期，服务端另存操作时间。备注去首尾空格后必须非空，最多 1000 字。请求 UUID 每个新动作新建；网络重试沿用原 UUID、原内容及原 ETag。

不接受额外写入字段，特别是累计完成、已交接、待交接占用、原料根米、操作者和状态。客户端只能提交上面的本次业务输入。

## 3. 数量与显示

| 返回字段 | 意义 |
| --- | --- |
| issued_pieces / completed_pieces | 已实际领支数 L / 累计合格完成 C |
| dispatched_pieces / reserved_pieces | 已交接 D / 待外发占用 P；P3 正常操作中均为 0，P4 接入真实明细后维护 |
| unfinished_pieces | L−C |
| unallocated_pieces | C−D−P，保留实际未分配差额，不作为结清后可操作量 |
| available_pieces | 未结清时 C−D−P；结清后 0 |
| remaining_completion_pieces | 未结清时 L−C；结清后 0 |
| bar_count / meters | 原领料根、米追溯，本次加工操作不扣库 |
| source_snapshot | 原领料、任务、产品、部位、批次及换算的冻结资料 |
| completions / closure | 实际登记明细，以及结清时数量快照、备注、人员和时间 |
| can_register / can_close / blockers | 数据和状态是否允许操作及阻止原因；前端还须结合账号动作权限 |

来源冻结资料不完整时显示阻止原因，ETag 为空，不能登记或结清；不根据最新 BOM 猜补。后续 BOM 调整不重算已经冻结的支根米。已结清无编辑、删除或重开入口。

结清前 P 必须为 0。P4 尚未实现真实外发占用关联，因此本期不会生成“关联外发单号”示例数据；P4 接入后需返回真实关联单据以供处理。已交接的外发单不会随来源结清结束。

## 4. 错误与重试

错误沿用项目 `error` 包装：`code`、`message`、`field_errors`、`request_id`。

| HTTP 状态 | 常见原因 |
| --- | --- |
| 400 | 数量、日期、备注、额外字段无效；冻结来源资料缺失或不一致 |
| 401 / 403 | 未登录、员工无效、权限不足、CSRF 校验失败 |
| 404 | 来源不存在、不可访问，或不是已出库金工管材来源 |
| 409 | 已结清、仍有占用、已建账的冻结来源发生改变、同请求 UUID 改内容／换操作人／换来源 |
| 412 | 来源版本已变化，刷新核对后再提交新的操作 |
| 428 | 新操作缺少 If-Match |

相同请求 UUID、同一操作人及相同内容重试返回首次成功结果，不重复写入。即使随后又发生其他操作，也不会把原请求重试当成新登记；前端收到重试结果后应重新读取最新来源，不能把首次结果当作永远最新的余额。权限仍会重新验证。

## 5. 环境及复验

沿用 Python 3.13、Django 5.2、PostgreSQL 17 和现有依赖，未新增依赖。P3 验证使用独立网络、独立 PostgreSQL／Redis 和独立后端容器，不开放主机端口。环境记录在 `qa/direct_handoff_p3_20260922/environment.json`。

在项目根目录可使用以下命令，在本轮独立环境中从完整迁移基准新建测试库并运行回归。脚本验证独立数据库标识，不访问业务库；它不负责启动已停止的测试容器。

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
docker exec haiqu-handoff-p3-20260922-115920-backend python /qa/run_seeded_regression.py
```

不要把命令中的容器替换成业务后端。旧测试依赖迁移生成的产品资料；事务测试结束会清空测试数据，所以不能认为 `--keepdb` 等于保留完整基础样例。上述脚本每次创建名称唯一的新测试库，保留本轮旧测试日志供追溯。
