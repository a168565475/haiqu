# haiqu ERP CRM API V1 设计

版本：V1.0  
状态：已确认，切片 A 至切片 G 的公共基础、客户、沟通任务、询价、报价、样品、治理与首页已实现  
范围：客户 CRM、轻量客诉、询价、报价、样品和公共工作流
明确排除：订单、产品、财务、采购、库存、生产以及客诉中的退款、赔付和财务执行

## 1. 设计结论

API V1 使用 Django REST Framework，业务接口统一放在 /api/v1/ 下。现有登录、退出、当前用户和健康检查接口继续保留，避免破坏已经运行的登录页。

71 张业务表不会机械生成 71 组增删改查接口。API 按以下三类处理：

1. 业务主资源：提供列表、详情、创建、修改和明确的状态动作。
2. 内部关系与历史记录：通过所属业务资源读写，不暴露任意修改接口。
3. 系统记录：只读或完全不对前端开放。

业务状态不能通过普通 PATCH 随意修改，必须调用 submit、approve、issue、ship、complete 等动作接口。动作接口在数据库事务中完成状态检查、并发锁、历史快照、时间轴和审计日志。

## 2. 当前事实与设计边界

### 2.1 已存在能力

- Django 5.2、Django REST Framework 3.16、django-filter。
- PostgreSQL 17 和 Redis 7。
- 基于 Django Session 的登录认证和 CSRF 防护。
- 71 张 CRM 业务表、UUID 业务主键、软归档字段和更新时间。
- PostgreSQL 跨表约束、排斥约束和 18 个完整性触发器。
- 组织、员工、角色、数据授权、审计、任务、SLA、审批和自动化执行模型。

### 2.2 尚不存在的能力

- 切片 G 的治理与首页接口尚未实现。
- 客户审计查询和客户附件接口尚未实现；时间轴现已支持只读查询。
- 组织模型尚无可靠的“主管/管理者”标识，因此当前客户范围只支持本人归属、显式授权和查看全部客户权限；不能把同组织自动等同于主管权限。
- 没有文件实际存储、下载授权和病毒扫描实现。
- 没有后台任务框架，不能把“异步导入”假装成已具备能力。

### 2.3 本期不做

- 不创建订单、订单明细、付款、发货、产品和财务 API。
- 不提供通用动态查询语言。
- 不提供任意表名、字段名或排序表达式。
- 不直接开放审计日志、时间轴事件、合并变更明细的写接口。
- 不在第一版引入微服务、消息队列、CQRS 或复杂缓存。

## 3. URL 和版本规则

### 3.1 保留现有平台接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/auth/login/ | 登录 |
| POST | /api/auth/logout/ | 退出 |
| GET | /api/auth/me/ | 当前登录状态、员工和权限摘要 |
| GET | /api/health/ | 服务健康检查 |

### 3.2 新业务接口

所有新业务接口使用：

    /api/v1/{resource}/

资源名称统一使用小写复数和连字符。业务主键均为 UUID 字符串；Django 用户主键只在认证内部使用，不作为 CRM 业务对象主键。

### 3.3 方法规则

- GET：查询，不改变业务数据。
- POST：创建资源或执行一个明确业务动作。
- PATCH：修改允许编辑的普通字段。
- PUT：V1 不开放，避免调用方误以为可以安全覆盖整条业务记录。
- DELETE：仅用于草稿明细和尚未生效的临时关系；客户、询价、报价、样品等主资源不物理删除。
- archive、restore：主资源使用专用动作进行软归档与恢复。

## 4. 通用请求与响应

### 4.1 成功响应

单条资源：

    {
      "data": {
        "id": "UUID",
        "account_code": "CUS-0001",
        "account_name": "示例客户",
        "updated_at": "2026-08-22T04:30:00Z"
      }
    }

分页列表：

    {
      "data": [],
      "meta": {
        "page": 1,
        "page_size": 20,
        "total": 135,
        "total_pages": 7
      }
    }

普通管理列表使用页码分页，默认每页 20 条，最大 100 条。客户时间轴和审计日志使用游标分页，避免新增记录造成翻页重复或遗漏。

### 4.2 错误响应

    {
      "error": {
        "code": "INVALID_STATE_TRANSITION",
        "message": "草稿询价没有明细，不能提交",
        "field_errors": {
          "items": ["至少需要一条询价明细"]
        },
        "request_id": "UUID"
      }
    }

| HTTP 状态 | 使用场景 |
| --- | --- |
| 400 | 字段格式、必填项或业务参数错误 |
| 401 | 未登录 |
| 403 | 已登录但无权限或无数据范围 |
| 404 | 资源不存在，或当前用户无权知道资源存在 |
| 409 | 状态冲突、重复提交、唯一约束或跨表冲突 |
| 412 | If-Match 版本已经过期 |
| 428 | 修改接口缺少 If-Match |
| 429 | 请求频率过高 |
| 500 | 未预料的服务器异常 |

数据库约束名称不能直接返回给普通用户。服务端应将约束异常转换成稳定的业务错误码，同时记录原始错误供排查。

### 4.3 日期、金额和编码

- 日期时间统一返回带时区的 ISO 8601 字符串，数据库保存 UTC，界面按 Asia/Shanghai 显示。
- 金额和数量使用字符串输出，例如 "1250.0000"，禁止使用浮点数。
- 币种使用三位大写代码，例如 USD、CNY。
- 国家使用两位大写代码，例如 CN、US。
- 枚举值使用稳定英文编码，同时返回中文显示名。

### 4.4 筛选、搜索和排序

- 关键词：q。
- 精确筛选：status、owner_id、customer_id 等白名单字段。
- 时间范围：created_from、created_to、updated_from、updated_to。
- 排序：ordering，只允许服务端白名单，如 -updated_at、account_name。
- 多状态筛选：status=OPEN&status=WON。
- 空值筛选使用明确参数，例如 has_contact=true。
- 未知筛选字段返回 400，不能静默忽略。

### 4.5 业务编号

客户编号、询价编号和报价编号由服务端生成，调用方不得指定或修改。来源样品需求先生成永久 SRQ 编号；样品正式编号由服务端根据工厂填写的手写号生成 `HTS-{手写号}`，手写号会去除首尾空格并转大写，生成后两者均不可修改。建议格式：

- 客户：CUS-000001，连续递增，不按月份重置。
- 询价：INQ-202608-000001，按月显示年月，序号持续递增。
- 报价：QUO-202608-000001，按月显示年月，序号持续递增。
- 样品需求：SRQ-202609-000001，按月显示年月，序号持续递增。
- 样品正式号：HTS-{手写打样单号}；历史 `SMP-` 编号原样保留，不重写。

实现使用 PostgreSQL sequence 生成并允许因事务回滚出现断号。ERP 内部编号的核心要求是唯一和不可变，不应为了“绝对连续”引入锁表或复用失败编号。

## 5. 认证、CSRF 和会话

V1 继续使用 SessionAuthentication，不改成 JWT，原因如下：

- 当前 Vue 是第一方前端，登录接口和 CSRF 流程已经正常运行。
- Session 可以立即失效，适合企业内部系统。
- 当前没有移动客户端、第三方开放平台或跨系统令牌需求。
- 为“看起来先进”而同时维护 Session 和 JWT 会增加安全面和排错成本。

规则：

- 除登录、当前登录状态和健康检查外，全部接口默认要求登录。
- POST、PATCH、DELETE 和业务动作必须通过 CSRF 校验。
- 登录成功后 /api/auth/me/ 增加 employee、permissions、data_scope 字段。
- 员工不存在、已停用、已离职或已归档时，业务 API 返回 403；超级管理员保留故障处理通道。
- 登录失败不区分用户名不存在、密码错误或员工停用，防止账号枚举。
- request_id 由中间件生成或接收合法的 X-Request-ID，用于审计和排错。

## 6. 权限与客户数据范围

权限判断分两层，缺一不可：

1. 动作权限：用户是否可以查看、创建、转移、合并、签发、审批或寄送。
2. 数据范围：用户可以对哪些客户执行该动作。

### 6.1 数据范围

按优先级合并：

- 超级管理员：全部数据。
- 当前有效的 CustomerDataAccessGrant：授予指定客户和指定权限。
- 当前有效的 CustomerAssignment：本人主负责或协作的客户。
- 主管范围：本人当前主组织及下属组织员工负责的客户。
- 其他用户：无客户数据。

数据范围必须在 QuerySet 查询阶段过滤，不能先查出对象再仅在页面上隐藏。详情接口对无权访问的数据返回 404，降低客户信息泄漏风险。

### 6.2 建议新增业务权限

| 权限编码 | 用途 |
| --- | --- |
| customers.view_all_customer | 查看全部客户 |
| customers.transfer_customer | 发起客户转移 |
| customers.approve_customer_transfer | 审批客户转移 |
| customers.merge_customer | 执行客户合并 |
| customers.manage_customer_access | 管理客户数据授权 |
| quotations.issue_quotation | 签发正式报价 |
| quotations.dispatch_quotation | 发送正式报价 |
| quotations.accept_quotation | 标记报价被接受 |
| quotations.approve_quotation | 审批报价 |
| samples.decide_sample_fee | 决定样品收费 |
| samples.ship_sample | 寄送样品 |
| samples.view_all_samplerequest | 查看全部样品流程，不扩大全量客户资料权限 |
| samples.complete_sample_requirements | 完善待工厂处理的样品需求 |
| workflow.manage_sla_policy | 管理 SLA 策略 |
| audit.view_all_auditlog | 查看全部审计日志 |

这些权限需要在实现 API 时通过 Migration 写入 Django 权限表，不能只写成前端按钮控制。

## 7. API 资源与路由

### 7.1 公共元数据、组织和员工

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/meta/choices/ | 返回模型枚举及中文名 |
| GET | /api/v1/reference-data/ | 按 category_code 查询有效字典 |
| GET | /api/v1/organization-units/tree/ | 组织树，只返回当前有权查看范围 |
| GET | /api/v1/employees/ | 员工选择器，支持 q、status、organization_id |
| GET | /api/v1/employees/{id}/ | 员工基本资料 |

组织、员工、角色和字典的写操作第一版继续使用 Django Admin。业务 API 只提供安全的查询能力，避免同时维护两套权限管理入口。

### 7.2 客户账户

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/customers/ | 客户列表 |
| POST | /api/v1/customers/ | 创建客户账户 |
| GET | /api/v1/customers/{id}/ | 客户基础详情 |
| PATCH | /api/v1/customers/{id}/ | 修改允许编辑字段 |
| POST | /api/v1/customers/{id}/archive/ | 软归档 |
| POST | /api/v1/customers/{id}/restore/ | 恢复归档客户 |
| GET | /api/v1/customers/{id}/summary/ | 客户 360 首屏摘要 |
| GET | /api/v1/customers/{id}/timeline/ | 客户时间轴，只读 |
| GET | /api/v1/customers/{id}/audit-logs/ | 当前客户审计记录，只读 |
| GET | /api/v1/customers/{id}/attention-history/ | 客户关注等级履历 |
| POST | /api/v1/customers/{id}/set-attention/ | 结束当前关注等级并创建新履历 |
| GET | /api/v1/customers/options/ | 客户阶段、活跃度、等级、类型、来源、标签和负责人选项 |
| GET | /api/v1/customers/duplicate-check/ | 按 name、website、country_code 实时检查可见范围内的疑似重复客户；编辑时用 exclude_customer_id 排除自身 |
| GET/POST | /api/v1/customers/{id}/grade-history/、set-grade/ | 客户等级履历与调整 |
| GET/POST | /api/v1/customers/{id}/source-history/、set-source/ | 首次来源、当前来源及来源履历 |
| GET/POST | /api/v1/customers/{id}/activity-history/、set-activity/ | 客户活跃度履历与人工调整 |
| POST | /api/v1/customers/{id}/set-classification/ | 整体替换当前客户类型或标签并保留历史 |
| GET/POST | /api/v1/customers/{id}/business-snapshot-history/、set-business-snapshot/ | 人工业务快照历史与当前快照 |
| GET/POST | /api/v1/customers/{id}/files/ | 客户附件 |

客户列表支持 q、lifecycle_stage、country_code、owner_id、organization_id、attention_level、customer_grade、customer_source、customer_type、customer_tag、activity_status、archived 和 updated 时间范围。默认不返回已归档客户。

客户 360 摘要是组合查询接口，不对应一张新表。它返回客户基础资料、当前负责人、关注等级、联系人数量、未完成询价、开放报价、进行中样品、未关闭客诉和逾期任务数量。

客户阶段只表达成交进程，固定为 LEAD、VERIFIED、OPPORTUNITY、CUSTOMER、LOST；ACTIVE、FOLLOW_UP、HIGH_RISK、DORMANT 等属于独立的活跃度履历，不能再混入客户阶段。人工业务快照必须返回 source_type=MANUAL、as_of_at 和录入人，不能冒充订单或财务模块的实时事实；客诉数量优先读取实时客诉表，旧快照仅作兼容回退。

### 7.2.1 轻量客诉

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/complaints/ | 按客户数据范围查询或创建客诉 |
| GET/PATCH | /api/v1/complaints/{id}/ | 读取或修改客诉资料；PATCH 必须携带 If-Match |
| GET | /api/v1/complaints/options/ | 返回客诉类型、严重程度、状态和在职员工选项 |
| GET | /api/v1/complaints/stats/ | 返回总数、处理中、结束状态、SLA、类型和负责人统计 |
| POST | /api/v1/complaints/{id}/progress/ | 更新进展或按规则推进状态；必须携带 If-Match |
| POST | /api/v1/complaints/{id}/attachments/ | 上传 JPG/PNG/WebP 图片，单张最大 5MB |
| GET | /api/v1/complaints/{id}/attachments/{attachment_id}/preview/ | 仅预览已通过安全扫描的图片 |

状态固定为 ACCEPTED、RESPONSIBILITY_CONFIRMATION、SOLUTION_PLANNING、CUSTOMER_CONFIRMATION、CLOSED、CANCELLED。类型和严重程度必须来自 `COMPLAINT_TYPE`、`COMPLAINT_SEVERITY` 字典；SLA 由类型倍率和严重程度规则融合计算。订单模块未接入前使用 `source_order_reference` 和 `source_order_snapshot` 手工记录，不创建虚假订单关系。客户转移不改客诉负责人；客户合并切换当前客户并保留 `original_customer_account`。

### 7.3 交易主体、地址和联系人

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/customers/{customer_id}/entities/ | 客户交易主体列表与创建 |
| GET/PATCH | /api/v1/customer-entities/{id}/ | 交易主体详情与修改 |
| POST | /api/v1/customer-entities/{id}/archive/ | 归档交易主体 |
| GET/POST | /api/v1/customer-entities/{id}/roles/ | 交易主体角色履历 |
| POST | /api/v1/customer-entity-roles/{id}/end/ | 结束当前角色 |
| GET/POST | /api/v1/customer-entities/{id}/addresses/ | 地址列表与创建 |
| GET/PATCH | /api/v1/customer-addresses/{id}/ | 地址详情与修改 |
| POST | /api/v1/customer-addresses/{id}/archive/ | 归档地址 |
| GET/POST | /api/v1/customer-addresses/{id}/usages/ | 注册、账单、收货等地址用途履历 |
| POST | /api/v1/customer-address-usages/{id}/end/ | 结束当前地址用途 |
| GET/POST | /api/v1/customers/{customer_id}/contacts/ | 联系人列表与创建 |
| GET/PATCH | /api/v1/contacts/{id}/ | 联系人详情与修改 |
| POST | /api/v1/contacts/{id}/archive/ | 归档联系人 |
| GET/POST | /api/v1/contacts/{id}/methods/ | 联系方式 |
| GET/PATCH | /api/v1/contact-methods/{id}/ | 联系方式详情与修改 |
| POST | /api/v1/contact-methods/{id}/archive/ | 归档联系方式 |
| GET/POST | /api/v1/contacts/{id}/roles/ | 联系人角色履历 |
| POST | /api/v1/contact-roles/{id}/end/ | 结束当前联系人角色 |

联系人变更不覆盖旧历史快照。报价、样品寄送等正式业务继续读取各自保存的 snapshot 字段。

联系方式的 normalized_value、normalization_version 和 normalized_at 由服务端生成，调用方不能自行提交，避免不同客户端产生不同去重结果。

### 7.4 客户归属、授权、转移和合并

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/customers/{id}/assignments/ | 负责人和协作人履历 |
| POST | /api/v1/customers/{id}/collaborators/ | 增加协作人 |
| POST | /api/v1/customers/{id}/collaborators/{employee_id}/end/ | 结束协作 |
| GET/POST | /api/v1/customer-transfer-requests/ | 转移申请列表与创建 |
| POST | /api/v1/customer-transfer-requests/{id}/approve/ | 批准并生成新归属履历 |
| POST | /api/v1/customer-transfer-requests/{id}/reject/ | 拒绝 |
| POST | /api/v1/customer-transfer-requests/{id}/cancel/ | 申请人取消 |
| GET | /api/v1/customers/{id}/access-grants/ | 数据授权 |
| POST | /api/v1/customers/{id}/access-grants/ | 授权 |
| POST | /api/v1/customer-access-grants/{id}/revoke/ | 撤销授权 |
| GET/POST | /api/v1/customer-duplicate-cases/ | 重复案例列表与创建 |
| GET | /api/v1/customer-duplicate-cases/{id}/ | 案例及候选客户 |
| POST | /api/v1/customer-duplicate-candidates/{id}/decide/ | 标记重复、非重复或存续客户 |
| POST | /api/v1/customer-duplicate-cases/{id}/dismiss/ | 判定非重复 |
| POST | /api/v1/customer-duplicate-cases/{id}/merge-preview/ | 合并预览，不写业务数据 |
| POST | /api/v1/customer-duplicate-cases/{id}/merge/ | 执行合并 |
| GET | /api/v1/customer-merges/{id}/ | 合并结果与变更明细，只读 |

客户转移不能直接修改当前负责人字段。批准动作结束旧 CustomerAssignment 时间段，并创建新时间段，因此历史业务员不会被改写。

客户合并必须提交 survivor_customer_id、source_customer_ids、reason 和 field_decisions。服务端在同一事务中锁定全部客户，重新检查重复关系后执行；合并完成记录不允许修改。

### 7.5 沟通与时间轴

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/communications/ | 沟通列表与创建 |
| GET/PATCH | /api/v1/communications/{id}/ | 沟通详情与修正 |
| POST | /api/v1/communications/{id}/archive/ | 归档 |

创建沟通记录可以一次提交 employee_participant_ids、contact_participant_ids、inquiry_id、quotation_version_id、sample_request_id 和 file_ids。服务端写入内部关系表并检查所有对象属于同一客户。

时间轴事件由客户、沟通、询价、报价、样品和任务服务产生。前端不能直接创建、修改或删除 CustomerTimelineEvent。

### 7.6 询盘

新建／草稿编辑附件上传：`POST /api/v1/inquiries/{id}/attachments/`，使用 `multipart/form-data`，字段 `file` 与 `upload_id`（客户端生成的 UUID），请求携带 `If-Match`。需 `inquiries.add_inquiryfilelink`、`inquiries.change_inquiry`、有效员工及客户数据可见范围，且询盘仍为草稿。支持 PDF、XLSX、JPG、JPEG、PNG，单文件大于 0 且不超过 10 MB，每张询盘最多 100 个关联附件。先检查签名及工作簿容器，再经 ClamAV 扫描；扫描失败或不可用不保存、不关联附件。成功返回附件元数据及新 ETag；同一询盘重复上传相同 `upload_id` 和内容返回原附件，不重复关联。关联失败会回滚数据库并清理本次文件。

列表及详情增加只读 `product_amount`：`item_count` 为产品行数，`missing_price_count` 为未填目标单价或币种的行数，`totals` 按币种返回 `{currency_code, amount}`。金额以十进制字符串返回，等于该币种各行 `quantity × target_unit_price` 之和，不做汇率换算。列表“预估金额”和导出使用此结果；有缺价行显示“待补齐”，无产品显示“—”。原 `estimated_amount_min/max` 及 `estimated_currency_code` 继续保留手填预算含义。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/inquiries/ | 询盘列表与创建；创建人自动成为负责人 |
| GET/PATCH | /api/v1/inquiries/{id}/ | 询盘详情与草稿修改 |
| GET | /api/v1/inquiries/options/ | 创建及筛选选项 |
| GET | /api/v1/inquiries/metrics/ | 列表统计，含报价已接受与待建订单 |
| GET | /api/v1/inquiries/board/ | 按询盘主状态分组的看板 |
| PATCH | /api/v1/inquiries/{id}/draft/ | 保存草稿版本 |
| GET/POST | /api/v1/inquiries/{id}/items/ | 询盘明细 |
| PATCH/DELETE | /api/v1/inquiry-items/{id}/ | 修改或删除草稿明细 |
| POST | /api/v1/inquiries/{id}/submit/ | 正式提交；联系人和至少一条产品必填 |
| POST | /api/v1/inquiries/{id}/respond/ | 记录首响沟通并进入分析中 |
| POST | /api/v1/inquiries/{id}/attach-contact/ | 为历史缺联系人询盘补充联系人 |
| POST | /api/v1/inquiries/{id}/confirm-requirements/ | 确认需求并进入待报价 |
| POST | /api/v1/inquiries/{id}/mark-quoted/ | 标记已报价 |
| POST | /api/v1/inquiries/{id}/follow-up/ | 重复记录客户沟通，不覆盖主状态 |
| GET | /api/v1/inquiries/{id}/timeline/ | 分页返回询盘、沟通、样品与销售订单事件 |
| POST | /api/v1/inquiries/{id}/close/ | 关闭 |
| POST | /api/v1/inquiries/{id}/cancel/ | 取消 |
| GET/POST | /api/v1/inquiries/{id}/files/ | 附件关联 |
| GET | /api/v1/inquiries/{id}/files/{file_id}/download/ | 下载当前询盘已通过扫描的单个附件 |
| GET | /api/v1/inquiries/{id}/files-download/ | 全部附件打包 ZIP；最多 100 个、实际内容合计不超过 100 MB |
| GET | /api/v1/inquiries/{id}/tasks/ | 关联任务 |

附件下载需要 `inquiries.view_inquiryfilelink` 权限，同时按询盘客户可见范围和附件关联关系校验；只允许未归档且扫描为 CLEAN 的文件。缺失或越界文件返回 404，未通过扫描及打包超限返回 400。打包不静默跳过失败文件；重复文件名加序号，文件名中的路径分隔符替换为下划线。下载为私有、不缓存响应，不修改业务数据。

创建询盘支持 items 嵌套写入，整个请求必须原子成功或全部失败。负责人字段由服务端只读生成，前端不得传入或覆盖。DRAFT 可修改并允许暂缺联系人；正式提交必须选择同一客户下的有效联系人并至少包含一条产品。

询盘详情、明细集合和附件集合返回询盘聚合根 ETag。草稿修改、明细新增/修改/删除、附件关联和全部状态动作必须提交当前询盘的 If-Match；旧 ETag 返回 412，缺失返回 428。状态动作返回带请求上下文的新详情和新版 ETag，使前端无需刷新即可获得新的 `allowed_actions`。业务校验失败返回稳定错误代码和可操作提示；close 和 cancel 必须填写 reason。

提交询盘时，服务端选择 policy_code 最小的一条已启用 `target_type=INQUIRY` 策略并创建 SLA 跟踪。当前模型每张询盘只使用一条实际跟踪记录，截止时间采用 resolution_minutes，未配置时回退 response_minutes；没有启用策略时不阻塞提交。首响与后续跟进都创建正式客户沟通记录并写入时间轴。客户接受报价后，报价服务在同一事务中把询盘推进为 `QUOTE_ACCEPTED`；首张销售订单确认后推进为 `CONVERTED`。

### 7.7 报价与报价版本

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/quotations/ | 报价主记录列表与创建 |
| GET/PATCH | /api/v1/quotations/{id}/ | 报价主记录详情与允许字段修改 |
| GET | /api/v1/quotation-templates/ | 可用报价模板，只读 |
| GET/POST | /api/v1/quotations/{id}/versions/ | 版本列表与新建版本 |
| GET/PATCH | /api/v1/quotation-versions/{id}/ | 版本详情与草稿修改 |
| GET/POST | /api/v1/quotation-versions/{id}/lines/ | 报价明细 |
| PATCH/DELETE | /api/v1/quotation-lines/{id}/ | 修改或删除草稿明细 |
| GET/POST | /api/v1/quotation-lines/{id}/quantity-tiers/ | 数量阶梯价格 |
| POST | /api/v1/quotation-versions/{id}/lock/ | 锁定版本和全部快照 |
| POST | /api/v1/quotation-versions/{id}/submit-approval/ | 提交审批 |
| POST | /api/v1/quotation-versions/{id}/issue/ | 签发正式报价 |
| POST | /api/v1/quotation-versions/{id}/generate-document/ | 登记固定模板生成结果，现阶段提交既有 file_id |
| POST | /api/v1/quotation-versions/{id}/dispatch/ | 记录发送并进入 SENT |
| GET | /api/v1/quotation-versions/{id}/documents/ | 生成文件历史，只读 |
| GET | /api/v1/quotation-versions/{id}/dispatches/ | 发送历史，只读 |
| GET | /api/v1/quotation-versions/{id}/tasks/ | 关联任务 |
| POST | /api/v1/quotation-versions/{id}/void/ | 作废版本 |
| POST | /api/v1/quotations/{id}/accept/ | 指定接受版本并把结果设为 WON |
| POST | /api/v1/quotations/{id}/lose/ | 标记失单 |
| POST | /api/v1/quotations/{id}/cancel/ | 取消报价 |

普通 PATCH 不能修改 status、locked_at、issued_at、accepted_version、金额汇总或快照。

新版本可提交 from_version_id，服务端复制上一版本的明细和条款，但产生新的 UUID 和 version_number。锁定时复制交易主体、地址、联系人、模板和条款快照，并重新计算各行金额和总金额。

签发前检查：

- 至少一条报价明细。
- 交易主体、地址和联系人快照完整。
- 金额重新计算一致。
- 模板要求审批时，必须存在已通过审批。
- 当前版本尚未签发、发送、替代或作废。

发送动作创建 QuotationDispatchRecord。接受报价必须指定属于该报价的已发送版本。报价结果一旦进入 WON、LOST 或 CANCELLED，`dispatch`、`manual-dispatch` 和 `email-dispatch` 均返回 409，不允许继续产生发送记录。

锁定前必须选择属于当前买方交易主体的地址和属于当前客户的有效联系人；校验失败时版本保持 DRAFT。报价编辑页可调用客户地址创建接口补充地址，创建成功后把新地址作为本次预览页的首选锁定地址。

报价、版本、明细和阶梯价分别受客户数据范围与动作权限控制。报价主记录动作使用报价 ETag；版本修改、明细/阶梯价写入、锁定、审批提交、签发、文档登记、发送和作废使用报价版本 ETag。审批决定使用审批 ETag，响应同时返回最新 `Quotation-Version-ETag`，供签发动作继续使用。

当前模型没有税率字段。锁定版本时提交 tax_rate，服务端重新计算每行金额、折扣额、税额和总额，并将税率固化到 terms_snapshot；调用方不能直接提交汇总金额。

当前阶段尚无文件上传、下载及 PDF 生成基础设施，因此 generate-document 不伪造文件。它只接受已由外部模板流程生成、已登记且扫描状态为 CLEAN 的 file_id，服务端校验客户归属、计算 snapshot_hash，并建立正式文档和报价文件关系。待文件子系统完成后，再把该端点内部替换为真正的异步文档生成，不改变报价状态机。

### 7.7.1 销售订单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/sales-orders/ | 销售订单列表与新建草稿 |
| GET/PATCH | /api/v1/sales-orders/{id}/ | 详情与草稿修改，写入必须携带 If-Match |
| GET | /api/v1/sales-orders/options/ | 客户、交易主体、有效买方地址、固定卖方模板、员工、产品、币种及可转报价版本 |
| GET | /api/v1/sales-orders/quotation-options/ | 读取已接受报价、签发地址 ID/快照、卖方模板及各行已转、已占用和剩余数量 |
| POST | /api/v1/sales-orders/{id}/confirm/ | 业务员直接确认草稿订单 |
| POST | /api/v1/sales-orders/{id}/confirmed-change/ | 已确认订单保存并确认新版本 |

报价转单只能选择客户已接受的报价版本，并允许删减产品或减少数量；同一报价可分多张销售订单，但未取消订单累计占用量不能超过报价数量。创建入口先读取报价行剩余数量，全部转完时留在报价页并给出明确提示。成交价允许编辑，确认时不比较历史价格，也不要求主管审批；服务端仍冻结来源报价价、实际成交价、价差和价差比例用于审计。

销售订单写入字段增加可空的 `buyer_address_id`，详情返回 `buyer_address_id` 与独立的 `buyer_address_snapshot`。草稿可以缺少地址；`confirm` 与 `confirmed-change` 会重新校验该地址仍有效且属于当前 `transaction_entity_id`，然后冻结最新地址快照。缺失、已归档或归属错误时返回稳定错误码 `BUYER_ADDRESS_REQUIRED`，`meta.field=buyer_address_id`、`meta.action=edit_buyer_address`。报价来源上下文始终返回签发时的 `buyer_address_snapshot`；仅当原地址仍有效且属于当前买方主体时返回非空 `buyer_address_id`。

销售订单版本的 `snapshot` 必须包含买方主体、买方地址、卖方、条款、客户要求、产品及交付批次，不得只保存产品和批次。订单确认前还必须完成客户确认字段及交付批次数量校验；每款产品在所有有效批次的分配总量必须严格等于订单数量。

### 7.8 样品

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/sample-requests/ | 样品申请列表；创建接收 `multipart/form-data`，其中 `payload` 为完整嵌套 JSON，任务单字段名为 `task_sheet_{client_key}`，打样信息明细图片字段名为 `sampling_image_{detail_client_key}` |
| GET | /api/v1/sample-requests/form-options/ | 制单人、样品类型、业务员、有效成品类别、去重色卡、颜色、公差及打样信息明细配置模板 |
| GET | /api/v1/sample-requests/form-context/?sourceType={type}&sourceId={uuid} | 权限校验后返回询盘或报价的客户、联系人、业务员和全部产品快照 |
| POST | /api/v1/sample-requests/create-from-inquiry/ | 从有效询盘提交业务员简报并创建 SRQ 待完善记录 |
| POST | /api/v1/sample-requests/create-from-quotation/ | 从当前已发送且未作废的报价版本提交简报并创建 SRQ 待完善记录 |
| GET/PATCH | /api/v1/sample-requests/{id}/ | 详情与历史草稿兼容修改 |
| PATCH | /api/v1/sample-requests/{id}/form/ | 携带 `If-Match` 和完整嵌套表单，按编辑阶段原子更新并返回新 ETag |
| GET/POST | /api/v1/sample-requests/{id}/items/ | 样品明细 |
| PATCH/DELETE | /api/v1/sample-items/{id}/ | 草稿明细修改 |
| POST | /api/v1/sample-requests/{id}/submit/ | 历史草稿兼容提交；新表单创建时已直接提交 |
| POST | /api/v1/sample-requests/{id}/start-preparing/ | 开始准备 |
| POST | /api/v1/sample-requests/{id}/finance-confirm/ | 财务确认；`multipart/form-data`，凭证 `file` 与人工 `note` 至少一项，携带 `If-Match` |
| POST | /api/v1/sample-requests/{id}/pmc-approve/ | PMC 审核通过，携带 `If-Match` |
| POST | /api/v1/sample-requests/{id}/metalwork-parameters/ | 上传金工参数，`file` 必填、`note` 选填，携带 `If-Match` |
| POST | /api/v1/sample-requests/{id}/cutting-parameters/ | 上传裁剪参数并结束主流程，`file` 必填、`note` 选填，携带 `If-Match` |
| GET | /api/v1/sample-requests/{id}/business-files/{file_id}/ | 在样品数据权限内安全预览或下载任务单、财务凭证及参数文件 |
| GET/POST | /api/v1/sample-requests/{id}/fee-records/ | 收费决策履历 |
| GET/POST | /api/v1/sample-requests/{id}/shipments/ | 寄送记录 |
| POST | /api/v1/sample-shipments/{id}/ship/ | 寄出并锁定收件和地址快照 |
| POST | /api/v1/sample-shipments/{id}/deliver/ | 标记送达 |
| GET/POST | /api/v1/sample-requests/{id}/feedback/ | 反馈记录 |
| GET/POST | /api/v1/sample-requests/{id}/files/ | 样品附件 |
| GET | /api/v1/sample-requests/{id}/tasks/ | 关联任务 |
| POST | /api/v1/sample-requests/{id}/complete/ | 完成 |
| POST | /api/v1/sample-requests/{id}/cancel/ | 取消 |

新建表单按 `products[].details[]` 保存颜色样品明细，并按 `products[].sampling_details[]` 保存每个产品独立的打样信息明细。打样信息明细保存配置键、可编辑类型、类别项、是/否选择、描述及可选单图；详情同时返回嵌套 `products` 与旧扁平 `items`。费用、物流和反馈接口继续通过原样品明细 UUID 工作。所有数量按 `PCS` 整数保存，产品总数量由明细自动汇总。颜色必须提交有效颜色 UUID，服务端同时保存色卡、颜色名称和色号快照。

样品列表响应增加手写打样单号、寄送方式及显示名、下单日期、样品交期、交货批次及显示名、翻单、制单人、提交日期，并返回轻量 `products[]` 摘要。产品摘要包含类别、名称、规格、任务单文件、总打样数量及长/扶手宽/坐宽/背高/坐高；多产品按 `line_number` 顺序返回，列表页不得只展示第一条产品。

任务单图片每个产品一张；打样信息明细每行最多一张图片。两类图片均最大 5MB，仅支持 JPG/JPEG/PNG/GIF/WebP；服务端校验文件签名并经过 ClamAV 扫描。任一文件或数据库步骤失败时清理本次已保存文件。默认 19 行由 `apps/samples/config/sampling_detail_template.json` 维护，配置修改只影响之后生成的表单，不覆盖历史数据。

工厂直接完整创建响应状态为 `PENDING`，同时启动 SLA、审计和客户时间线。询盘/报价简报只接收样品类型、可选交期、可选特殊说明、幂等键及产品 UUID/正整数 PCS 数量，响应状态为 `PENDING_COMPLETION`；此时 `request_number` 与永久 `intake_number` 均显示 SRQ，`requested_by_employee` 记录业务申请人，`created_by_employee` 为空，不启动 SLA。

工厂对待完善记录调用表单 PATCH 时必须具备 `samples.complete_sample_requirements` 并携带 `If-Match`。完整校验和任务单图片扫描成功后，服务端原子生成 `HTS-{手写号}`、记录制单人、切换至 `PENDING` 并启动 SLA；失败时回滚数据库并清理本次上传文件。详情的 `edit_capabilities.mode` 为 `COMPLETE`、`FULL`、`REPORT_ONLY` 或 `READ_ONLY`。重复 `idempotency_key` 返回原记录，产前样和大货确认样不再要求先关联订单。

新主流程为 `PENDING（财务待确认） → PMC_REVIEW → METALWORK_PENDING → CUTTING_PENDING → FINISHED`。财务确认要求凭证或人工备注至少一项；PMC 本期只做通过；金工与裁剪参数必须顺序上传。详情返回 `workflow_records`（节点、操作人、时间、备注、文件）和 `workflow_actions`（当前账号可执行动作）。裁剪参数上传成功时写入结束节点并完成 SLA。

财务凭证支持 PDF/JPG/JPEG/PNG；生产参数支持 PDF/JPG/JPEG/PNG/XLS/XLSX；单文件最大 10MB，校验文件签名并通过 ClamAV 扫描。任一状态转换或数据库步骤失败时，删除本次已保存的文件。任务单、财务凭证和参数文件只能由有权查看该样品的账号读取，且仅允许读取扫描状态为 `CLEAN` 的文件。

收费决策采用新增履历并结束上一条当前记录的方式，不覆盖历史。收费但尚未确认凭证时，寄送动作必须传 fee_warning_acknowledged=true 和说明；服务端记录确认人和时间。

寄出后收件人、地址、物流单号、寄出时间和寄送明细不可修改。需要更正时新增异常或补寄记录。

寄出前必须存在当前收费决策且不能仍为 PENDING。EVIDENCE_UPLOADED 必须先关联 file_role=FEE_EVIDENCE 的既有文件；PAID 且未 MANUALLY_CONFIRMED 时必须明确确认风险并填写原因。多个寄送记录全部送达后，样品申请才进入 FEEDBACK_PENDING；至少存在一条反馈后才能完成。

样品申请、明细集合、收费履历、附件和反馈写入使用样品申请 ETag。寄送创建响应以寄送记录 ETag 为主，并通过 Sample-Request-ETag 返回最新申请版本；ship 和 deliver 使用寄送 ETag，响应同样返回最新申请 ETag。

提交样品申请时按 policy_code 选择第一条已启用 target_type=SAMPLE_REQUEST 的 SLA 策略，解决时限优先、响应时限兜底。完成时记录 MET/BREACHED，取消时记录 CANCELLED。统一 SLA 列表可通过 /api/v1/sla-trackings/ 按 status 和 target_type 查询。

### 7.9 任务、审批和 SLA

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/tasks/ | 我的任务和创建任务 |
| GET/PATCH | /api/v1/tasks/{id}/ | 任务详情与允许字段修改 |
| POST | /api/v1/tasks/{id}/start/ | 开始任务 |
| POST | /api/v1/tasks/{id}/complete/ | 完成任务 |
| POST | /api/v1/tasks/{id}/cancel/ | 取消任务 |
| POST | /api/v1/tasks/{id}/reassign/ | 转派 |
| GET | /api/v1/approvals/ | 我的待审批和历史 |
| GET | /api/v1/approvals/{id}/ | 审批详情 |
| POST | /api/v1/approvals/{id}/approve/ | 通过 |
| POST | /api/v1/approvals/{id}/reject/ | 拒绝 |
| POST | /api/v1/approvals/{id}/cancel/ | 申请人取消 |
| GET | /api/v1/sla-trackings/ | SLA 执行记录，只读 |

任务关联客户、沟通、询价、报价或样品时，前端提交 source_type 和 source_id；服务端写入对应关系表。关系表不提供独立 CRUD。

SLA 策略第一版通过 Django Admin 配置，SlaTracking 由业务动作创建和更新，普通用户只读。

### 7.10 文件

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/v1/files/ | multipart 上传 |
| GET | /api/v1/files/{id}/ | 文件元数据 |
| GET | /api/v1/files/{id}/download/ | 鉴权后下载 |
| POST | /api/v1/files/{id}/archive/ | 归档文件元数据 |

storage_key、content_hash、size_bytes、uploaded_by_employee 和 scan_status 均由服务端生成。下载前再次检查用户是否能访问至少一个与文件关联的业务对象。

INFECTED、FAILED 和 PENDING 文件默认禁止普通用户下载。V1 实现前必须确定私有文件存储位置和扫描策略。

### 7.11 搜索、Dashboard 和保存视图

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/search/ | 跨客户、主体、联系人、询价和报价编号搜索 |
| GET | /api/v1/dashboard/me/ | 业务员首页 |
| GET | /api/v1/dashboard/manager/ | 主管首页 |
| GET/POST | /api/v1/saved-views/ | 当前员工保存的筛选视图 |
| GET/PATCH | /api/v1/saved-views/{id}/ | 修改保存视图 |
| POST | /api/v1/saved-views/{id}/set-default/ | 设为模块默认视图 |
| POST | /api/v1/saved-views/{id}/archive/ | 归档 |

搜索只允许固定资源类型和字段，最低关键词长度建议为 2。Dashboard 每个统计项都必须应用相同客户数据范围，不能出现数字可见但明细不可见的泄漏。

### 7.12 审计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/audit-logs/ | 有权限用户查询审计日志 |
| GET | /api/v1/audit-logs/{id}/ | 审计详情 |

AuditLog 只读。普通员工只能从其有权访问的业务对象入口查看相关审计；全局审计查询仅对具备 audit.view_all_auditlog 权限的用户开放。

### 7.13 关键写接口示例

创建客户：

    {
      "account_name": "Example Outdoor GmbH",
      "english_name": "Example Outdoor GmbH",
      "short_name": "Example Outdoor",
      "primary_country_code": "DE",
      "primary_website_url": "example.invalid",
      "lifecycle_stage": "LEAD",
      "customer_source_item_id": "UUID",
      "customer_grade_item_id": "UUID，可选",
      "customer_type_item_ids": ["UUID"],
      "customer_tag_ids": ["UUID"],
      "primary_owner_employee_id": "UUID，可选；缺省为当前员工",
      "contact_name": "采购联系人，可选",
      "contact_method_type": "EMAIL",
      "contact_method_value": "buyer@example.invalid",
      "notes": ""
    }

服务端生成 account_code，同时创建当前主负责人、首次来源、初始活跃度及可选的等级、类型、标签和联系人记录。网站允许提交完整 URL 或裸域名。account_code、created_at、updated_at、archived_at 和 archived_by_employee 均不可由调用方提交。

创建带明细的询价：

    {
      "customer_id": "UUID",
      "transaction_entity_id": "UUID",
      "customer_contact_id": "UUID",
      "owner_employee_id": "UUID",
      "inquiry_source": "EMAIL",
      "subject": "折叠椅询价",
      "description": "客户原始需求",
      "received_at": "2026-08-22T04:30:00Z",
      "requested_due_at": "2026-08-30T04:30:00Z",
      "items": [
        {
          "line_number": 1,
          "product_description": "Folding chair",
          "specification": "Black, steel frame",
          "quantity": "1000.0000",
          "unit_code": "PCS",
          "target_unit_price": "12.5000",
          "target_currency_code": "USD",
          "notes": ""
        }
      ]
    }

锁定报价版本：

    {
      "transaction_entity_id": "UUID",
      "address_id": "UUID",
      "contact_id": "UUID",
      "terms": {
        "incoterm": "FOB",
        "incoterm_version": "2020",
        "named_place": "NINGBO",
        "payment_terms": "T/T",
        "lead_time": "30 days"
      }
    }

服务端读取当前主数据生成快照，重新计算各行金额和版本总金额。请求中的主体、地址和联系人必须属于报价客户。

寄出样品：

    {
      "carrier_code": "DHL",
      "tracking_number": "TEST123456",
      "recipient_contact_id": "UUID",
      "address_id": "UUID",
      "shipped_at": "2026-08-22T04:30:00Z",
      "items": [
        {
          "sample_item_id": "UUID",
          "shipped_quantity": "2.0000"
        }
      ],
      "fee_warning_acknowledged": false,
      "fee_warning_note": ""
    }

服务端生成 recipient_snapshot 和 address_snapshot。存在收费但未核验的当前费用记录时，必须明确确认风险并填写原因。

## 8. 状态动作和事务规则

### 8.1 通用执行顺序

每个状态动作必须在 transaction.atomic 中按以下顺序执行：

1. 用 select_for_update 锁定主记录。
2. 检查 If-Match 和 updated_at，防止覆盖他人的新修改。
3. 再次检查动作权限和客户数据范围。
4. 检查当前状态是否允许动作。
5. 校验关联对象和必要明细。
6. 计算金额或生成历史快照。
7. 更新主记录和关系记录。
8. 写入时间轴和审计日志。
9. 提交事务后再执行非关键外部操作。

数据库唯一约束和触发器是最后防线，不能替代服务层的中文业务提示。

### 8.2 并发控制

详情 GET 返回 ETag，值由资源 UUID 和 updated_at 生成。PATCH、归档和重要状态动作必须携带：

    If-Match: "返回的 ETag"

缺少时返回 428；版本过期时返回 412，并返回当前 updated_at。列表内的轻量动作可以提交 expected_updated_at，服务端转换为相同检查。

客户合并、客户转移审批、报价签发、报价接受和样品寄送必须使用数据库行锁。涉及多条记录时按 UUID 排序后锁定，降低死锁风险。

### 8.3 审计内容

以下操作必须写 AuditLog：

- 新增、修改、归档和恢复客户主数据。
- 联系人、地址、联系方式和客户归属变化。
- 数据授权、转移审批和客户合并。
- 询价、报价、样品的全部状态动作。
- 报价金额、条款、快照和正式文件生成。
- 样品收费决定、寄送和收费风险确认。
- 权限、角色、SLA 策略和字典变更。

before_data 和 after_data 只保存业务字段，不保存密码、Session、CSRF、原始文件内容或其他秘密。

### 8.4 状态机

询价：

| 当前状态 | 动作 | 新状态 |
| --- | --- | --- |
| DRAFT | submit | SUBMITTED |
| SUBMITTED | start | IN_PROGRESS |
| IN_PROGRESS | mark-quoted | QUOTED |
| SUBMITTED、IN_PROGRESS、QUOTED | close | CLOSED |
| DRAFT、SUBMITTED、IN_PROGRESS、QUOTED | cancel | CANCELLED |

报价主记录：

| 当前状态 | 动作 | 新状态 |
| --- | --- | --- |
| OPEN | accept | WON |
| OPEN | lose | LOST |
| OPEN | cancel | CANCELLED |

报价版本：

| 当前状态 | 动作 | 新状态 |
| --- | --- | --- |
| DRAFT | lock | LOCKED |
| LOCKED | issue | ISSUED |
| ISSUED | dispatch | SENT |
| DRAFT、LOCKED、ISSUED | void | VOID |
| ISSUED、SENT | 新版本签发 | SUPERSEDED |

样品申请：

| 当前状态 | 动作 | 新状态 |
| --- | --- | --- |
| PENDING_COMPLETION | form（完善并提交） | PENDING |
| DRAFT | submit | PENDING |
| PENDING | finance-confirm | PMC_REVIEW |
| PMC_REVIEW | pmc-approve | METALWORK_PENDING |
| METALWORK_PENDING | metalwork-parameters | CUTTING_PENDING |
| CUTTING_PENDING | cutting-parameters | FINISHED |
| PENDING_COMPLETION、DRAFT、PENDING、PMC_REVIEW、METALWORK_PENDING、CUTTING_PENDING | cancel | CANCELLED |

`PREPARING → SHIPPED → FEEDBACK_PENDING → COMPLETED` 等旧寄送/反馈状态只用于兼容历史数据和既有接口，不再由新样品主流程进入。费用、物流、反馈和报工记录作为辅助事实保存，只有存在真实记录及时间时才在详情页显示。

任务：

| 当前状态 | 动作 | 新状态 |
| --- | --- | --- |
| PENDING | start | IN_PROGRESS |
| PENDING、IN_PROGRESS | complete | COMPLETED |
| PENDING、IN_PROGRESS | cancel | CANCELLED |

审批：

| 当前状态 | 动作 | 新状态 |
| --- | --- | --- |
| PENDING | approve | APPROVED |
| PENDING | reject | REJECTED |
| PENDING | cancel | CANCELLED |

所有终态默认不可恢复。业务确实需要撤销时，应新增反向业务记录和审计，而不是直接把状态改回去。

## 9. Django 代码组织

每个业务应用建议采用以下简单结构：

    apps/customers/
      api/
        urls.py
        views.py
        serializers.py
        filters.py
        permissions.py
      services.py
      selectors.py
      models.py
      tests/

- views：处理 HTTP、调用序列化器和服务，不写复杂业务规则。
- serializers：输入格式、字段级校验和输出结构；创建输入与详情输出分开。
- services：事务、状态机、快照、审计和跨表写入。
- selectors：统一数据范围、select_related、prefetch_related 和聚合查询。
- permissions：动作权限；对象是否可见主要由 selectors 的 QuerySet 范围控制。
- filters：白名单筛选和排序。

不使用 Django signal 承载客户合并、报价签发等核心流程。隐藏在 signal 中的跨表写入难以看懂、难以测试，也不容易控制事务顺序。

## 10. 性能规则

- 列表序列化器只返回页面需要的摘要字段，详情另查。
- 客户、询价、报价、样品列表统一使用 select_related 获取负责人和客户摘要。
- 联系人、明细、文件等一对多关系使用 prefetch_related，禁止循环逐条查询。
- Dashboard 使用少量聚合 SQL，不把全量数据加载到 Python。
- 列表默认最多 100 条；导出必须使用独立导出流程。
- 搜索优先使用已建立的 trigram 和唯一编号索引。
- API 测试为主要列表设置查询次数上限，防止 N+1 查询退化。
- Redis 第一版仅用于短期限流和轻量缓存；权限结果、报价状态和样品状态不能只存在 Redis。

## 11. 文件与后台任务的现实限制

当前项目没有 Celery 或其他后台任务执行器，因此：

- 报价文档生成可以先同步执行，但必须设置文件大小和执行超时。
- 病毒扫描、批量导入和大文件处理不能宣称为真正异步。
- ImportBatch、ImportRecord 和 AutomationExecution 暂时作为内部能力保留，不在首批前端 API 中开放。
- 后续确认确实需要长任务时，再单独选择后台任务方案并补充部署、失败重试和监控。

## 12. OpenAPI 和接口契约

实现阶段建议新增 drf-spectacular，用于从实际路由和序列化器生成 OpenAPI 3 文档。建议提供：

- /api/schema/：OpenAPI JSON/YAML。
- /api/docs/：仅开发和测试环境开放的交互文档。

接口文档必须生成自真实代码，不能长期手工维护一份与代码分离的 YAML。

## 13. 实施切片

### 切片 A：公共基础（已实现）

统一响应、异常、分页、request_id、认证员工校验、权限范围、ETag、审计服务和 OpenAPI。

### 切片 B：客户核心（已实现）

客户、交易主体、地址、联系人、联系方式、归属和客户 360 摘要。

### 切片 C：沟通、任务和时间轴（已实现）

沟通记录、参与者、任务、附件关联和时间轴。

### 切片 D：询价（已实现）

询价、明细、状态动作、附件和 SLA。

### 切片 E：报价（已实现）

报价主记录、版本、明细、阶梯价、审批、快照、签发、文档和发送。

### 切片 F：样品（已实现）

申请、明细、收费、寄送、反馈、审批和 SLA。

### 切片 G：治理与首页（已实现）

客户转移、授权、去重合并、全局搜索、Dashboard、保存视图和审计查询。

每个切片完成后都应先执行自动测试和前后端契约验证，再进入下一切片。

## 14. 必测场景

- 未登录、无员工档案、员工停用、无动作权限和无数据范围。
- 列表、详情、聚合和搜索均不能泄漏越权客户。
- 两人同时修改客户时，旧 ETag 请求失败。
- 两人同时审批转移、签发报价或寄送样品时，只允许一次成功。
- 提交无明细询价失败。
- 已提交询价不能修改明细。
- 报价金额由服务端计算，调用方伪造汇总金额无效。
- 已锁定报价及快照不能修改。
- 接受版本必须属于当前报价。
- 样品收费未确认时，寄送必须明确确认风险。
- 已寄出样品的物流和地址快照不能修改。
- 客户合并必须一个存续客户和至少一个来源客户。
- 文件下载必须同时通过文件状态和关联业务对象权限。
- 审计日志不能通过 ORM、API 或直接 SQL 修改和删除。

## 15. 已确认的实施参数

以下三项已于 API V1 设计确认时一并确定：

1. 文件策略：建议 V1 使用服务器本地私有目录保存，限制单文件 20 MB；只有白名单文件类型可上传。扫描能力未接入前，普通用户上传后由管理员确认 CLEAN 才能下载，避免把未扫描文件直接当作安全文件。
2. OpenAPI：建议增加 drf-spectacular 这一项轻量依赖，自动生成并校验接口文档。
3. 编号规则：客户、询价、报价采用本文 4.5 的 CUS、INQ、QUO 规则；新样品采用唯一且不可变的 HTS 正式号，历史 SMP 编号继续保留。

切片 A 已实现统一认证基础、员工状态校验、请求编号、统一异常、分页、ETag、审计服务、四类业务编号序列、13 项业务动作权限和 OpenAPI。切片 B 已实现客户、交易主体、地址、联系人、联系方式、归属、关注等级、客户 360 摘要、数据范围、软归档、审计与并发保护。切片 C 已实现沟通记录、员工与联系人参与者、询价/报价版本/样品/既有文件关联、任务状态机、转派、审计和客户时间轴只读查询。切片 D 已实现询价自动编号、嵌套明细、草稿编辑、状态机、既有文件关联、任务查询、单条 SLA 跟踪、审计、时间轴和聚合根并发保护。切片 E 已实现报价主记录、版本复制、明细、阶梯价、服务端金额重算、锁定快照、审批、签发、正式文档登记、发送履历、接受/失单/取消、任务查询、审计和并发保护。切片 F 已实现样品申请、明细、收费履历、凭证约束、寄送快照、收费风险确认、送达、反馈、附件、任务、SLA 查询、审计与并发保护。切片 G 已实现客户转移申请与审批、客户级显式授权、去重案例、合并预检与事务化合并、全局搜索、个人与管理驾驶舱、保存视图和分级审计查询。订单模块按已确认范围继续延期，待客户侧订单方案完成后另行设计。

## 16. 原料信息 API 扩展（2026-08-31）

### 16.1 端点

- `GET /api/v1/raw-materials/`：分页列表；支持 `q`、`item_type`、`category_id`、`warehouse_number` 和受控 `ordering`。
- `GET /api/v1/raw-materials/{id}/`：详情并返回 `ETag`。
- `POST /api/v1/raw-materials/`：新增原料信息。
- `PATCH /api/v1/raw-materials/{id}/`：携带 `If-Match` 更新原料信息。
- `GET /api/v1/raw-materials/options/`：返回材料/半成品类型、按类型标记的类别、生产单位、产品颜色、附件仓库和箱子形状。

### 16.2 权限与规则

- 查看、新增、编辑分别使用 `products.view_rawmaterialinformation`、`products.add_rawmaterialinformation`、`products.change_rawmaterialinformation`。
- 类别的 `item_type` 必须与原料类型一致；停用或归档的类别、单位、颜色不能用于新的关联。
- “是否包材辅料”和“箱子形状”只允许用于“材料 / 包材”。仓库号与仓库名称必须是附件中已确认的同一组组合。
- 新增品号必须唯一；附件中的 26 个历史重复品号以 `source_row_number` 区分并保留。
- 更新使用 ETag 乐观锁；创建和更新写入 `RAW_MATERIAL_INFORMATION` 审计日志；不开放删除端点。
