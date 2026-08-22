# haiqu ERP CRM API V1 设计

版本：V1.0  
状态：已确认，切片 A 至切片 G 的公共基础、客户、沟通任务、询价、报价、样品、治理与首页已实现  
范围：客户 CRM、询价、报价、样品和公共工作流  
明确排除：订单、产品、财务、采购、库存、生产、客诉

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

客户编号、询价编号、报价编号和样品申请编号由服务端生成，调用方不得指定或修改。建议格式：

- 客户：CUS-000001，连续递增，不按月份重置。
- 询价：INQ-202608-000001，按月显示年月，序号持续递增。
- 报价：QUO-202608-000001，按月显示年月，序号持续递增。
- 样品：SMP-202608-000001，按月显示年月，序号持续递增。

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
| GET/POST | /api/v1/customers/{id}/files/ | 客户附件 |

客户列表支持 q、lifecycle_stage、country_code、owner_id、organization_id、attention_level、archived 和 updated 时间范围。默认不返回已归档客户。

客户 360 摘要是组合查询接口，不对应一张新表。它返回客户基础资料、当前负责人、关注等级、联系人数量、未完成询价、开放报价、进行中样品和逾期任务数量。

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

### 7.6 询价

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/inquiries/ | 询价列表与创建 |
| GET/PATCH | /api/v1/inquiries/{id}/ | 询价详情与草稿修改 |
| GET/POST | /api/v1/inquiries/{id}/items/ | 询价明细 |
| PATCH/DELETE | /api/v1/inquiry-items/{id}/ | 修改或删除草稿明细 |
| POST | /api/v1/inquiries/{id}/submit/ | 提交 |
| POST | /api/v1/inquiries/{id}/start/ | 开始处理 |
| POST | /api/v1/inquiries/{id}/mark-quoted/ | 标记已报价 |
| POST | /api/v1/inquiries/{id}/close/ | 关闭 |
| POST | /api/v1/inquiries/{id}/cancel/ | 取消 |
| GET/POST | /api/v1/inquiries/{id}/files/ | 附件关联 |
| GET | /api/v1/inquiries/{id}/tasks/ | 关联任务 |

创建询价支持 items 嵌套写入，整个请求必须原子成功或全部失败。DRAFT 可修改；提交后明细只读。如需更正，应取消旧询价并建立新询价，或后续单独设计修订机制。

询价详情、明细集合和附件集合返回询价聚合根 ETag。草稿修改、明细新增/修改/删除、附件关联和全部状态动作必须提交当前询价的 If-Match；旧 ETag 返回 412，缺失返回 428。close 和 cancel 必须填写 reason。

提交询价时，服务端选择 policy_code 最小的一条已启用 `target_type=INQUIRY` 策略并创建 SLA 跟踪。当前模型每张询价只使用一条实际跟踪记录，截止时间采用 resolution_minutes，未配置时回退 response_minutes；没有启用策略时不阻塞提交。标记已报价或关闭时按实际完成时间判定 MET/BREACHED，取消时记为 CANCELLED。

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

发送动作创建 QuotationDispatchRecord。接受报价必须指定属于该报价的已签发或已发送版本。

报价、版本、明细和阶梯价分别受客户数据范围与动作权限控制。报价主记录动作使用报价 ETag；版本修改、明细/阶梯价写入、锁定、审批提交、签发、文档登记、发送和作废使用报价版本 ETag。审批决定使用审批 ETag，响应同时返回最新 `Quotation-Version-ETag`，供签发动作继续使用。

当前模型没有税率字段。锁定版本时提交 tax_rate，服务端重新计算每行金额、折扣额、税额和总额，并将税率固化到 terms_snapshot；调用方不能直接提交汇总金额。

当前阶段尚无文件上传、下载及 PDF 生成基础设施，因此 generate-document 不伪造文件。它只接受已由外部模板流程生成、已登记且扫描状态为 CLEAN 的 file_id，服务端校验客户归属、计算 snapshot_hash，并建立正式文档和报价文件关系。待文件子系统完成后，再把该端点内部替换为真正的异步文档生成，不改变报价状态机。

### 7.8 样品

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/v1/sample-requests/ | 样品申请列表与创建 |
| GET/PATCH | /api/v1/sample-requests/{id}/ | 详情与草稿修改 |
| GET/POST | /api/v1/sample-requests/{id}/items/ | 样品明细 |
| PATCH/DELETE | /api/v1/sample-items/{id}/ | 草稿明细修改 |
| POST | /api/v1/sample-requests/{id}/submit/ | 提交申请 |
| POST | /api/v1/sample-requests/{id}/start-preparing/ | 开始准备 |
| GET/POST | /api/v1/sample-requests/{id}/fee-records/ | 收费决策履历 |
| GET/POST | /api/v1/sample-requests/{id}/shipments/ | 寄送记录 |
| POST | /api/v1/sample-shipments/{id}/ship/ | 寄出并锁定收件和地址快照 |
| POST | /api/v1/sample-shipments/{id}/deliver/ | 标记送达 |
| GET/POST | /api/v1/sample-requests/{id}/feedback/ | 反馈记录 |
| GET/POST | /api/v1/sample-requests/{id}/files/ | 样品附件 |
| GET | /api/v1/sample-requests/{id}/tasks/ | 关联任务 |
| POST | /api/v1/sample-requests/{id}/complete/ | 完成 |
| POST | /api/v1/sample-requests/{id}/cancel/ | 取消 |

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
      "primary_website_url": "https://example.invalid",
      "lifecycle_stage": "PROSPECT",
      "primary_owner_employee_id": "UUID",
      "notes": ""
    }

服务端生成 account_code，同时创建当前主负责人履历。account_code、created_at、updated_at、archived_at 和 archived_by_employee 均不可由调用方提交。

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
| DRAFT | submit | PENDING |
| PENDING | start-preparing | PREPARING |
| PREPARING | shipment.ship | SHIPPED |
| SHIPPED | shipment.deliver | FEEDBACK_PENDING |
| FEEDBACK_PENDING | complete | COMPLETED |
| DRAFT、PENDING、PREPARING | cancel | CANCELLED |

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
3. 编号规则：建议采用本文 4.5 的 CUS、INQ、QUO、SMP 规则，并通过 PostgreSQL sequence 保证并发唯一。

切片 A 已实现统一认证基础、员工状态校验、请求编号、统一异常、分页、ETag、审计服务、四类业务编号序列、13 项业务动作权限和 OpenAPI。切片 B 已实现客户、交易主体、地址、联系人、联系方式、归属、关注等级、客户 360 摘要、数据范围、软归档、审计与并发保护。切片 C 已实现沟通记录、员工与联系人参与者、询价/报价版本/样品/既有文件关联、任务状态机、转派、审计和客户时间轴只读查询。切片 D 已实现询价自动编号、嵌套明细、草稿编辑、状态机、既有文件关联、任务查询、单条 SLA 跟踪、审计、时间轴和聚合根并发保护。切片 E 已实现报价主记录、版本复制、明细、阶梯价、服务端金额重算、锁定快照、审批、签发、正式文档登记、发送履历、接受/失单/取消、任务查询、审计和并发保护。切片 F 已实现样品申请、明细、收费履历、凭证约束、寄送快照、收费风险确认、送达、反馈、附件、任务、SLA 查询、审计与并发保护。切片 G 已实现客户转移申请与审批、客户级显式授权、去重案例、合并预检与事务化合并、全局搜索、个人与管理驾驶舱、保存视图和分级审计查询。订单模块按已确认范围继续延期，待客户侧订单方案完成后另行设计。
