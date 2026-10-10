# 当前权限与 API 目录（自动提取）

采集时间：2026-09-28T06:39:49.784302+00:00。扫描 388 个业务源码文件、129 个静态控制器定义，解析 741 条 API 路由注册（包含格式后缀等重复注册）。

这是现有代码目录，不代表目标权限已实施或 API 已通过运行验收。模型自动生成的权限不一定有对应业务功能；目标页面只呈现实有操作。直接检查、继承权限和业务服务门禁须结合差异报告阅读。

## 工作台与全局检索 (core)

9 个已注册处理类，9 条路由注册，0 个映射中的权限码。

### auth_login

权限类：AllowAny。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| auth-login | `api/auth/login/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### development_auto_login

权限类：AllowAny。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| development-auto-login | `api/auth/development-auto-login/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### auth_logout

权限类：AllowAny。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| auth-logout | `api/auth/logout/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### current_user

权限类：AllowAny。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| auth-me | `api/auth/me/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### health

权限类：AllowAny。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| health | `api/health/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### api_v1_root

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| api-v1-root | `api/v1/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### GlobalSearchView

源码：[apps/core/api/discovery_views.py:30](../../src/backend/apps/core/api/discovery_views.py#L30)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| global-search | `api/v1/search/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### MyDashboardView

源码：[apps/core/api/discovery_views.py:188](../../src/backend/apps/core/api/discovery_views.py#L188)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| dashboard-me | `api/v1/dashboard/me/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ManagerDashboardView

源码：[apps/core/api/discovery_views.py:199](../../src/backend/apps/core/api/discovery_views.py#L199)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| dashboard-manager | `api/v1/dashboard/manager/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

类内直接权限判断：

- 第 204 行：`request.user.has_perm('customers.view_all_customer')`

## 客户、联系人及客诉 (customers)

15 个已注册处理类，75 条路由注册，51 个映射中的权限码。

### CustomerAccessGrantNestedViewSet

源码：[apps/customers/api/governance_views.py:151](../../src/backend/apps/customers/api/governance_views.py#L151)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-access-grant-nested-list | `api/v1/customers/<uuid:customer_pk>/access-grants/` | GET → list；POST → create |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | customers.manage_customer_access |
| create | customers.manage_customer_access |

### CustomerViewSet

源码：[apps/customers/api/views.py:235](../../src/backend/apps/customers/api/views.py#L235)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-list | `api/v1/^customers/$` | GET → list；POST → create |
| customer-bulk-add-tags | `api/v1/^customers/bulk-add-tags/$` | POST → bulk_add_tags |
| customer-create-tag | `api/v1/^customers/tags/$` | POST → create_tag |
| customer-duplicate-check | `api/v1/^customers/duplicate-check/$` | GET → duplicate_check |
| customer-export | `api/v1/^customers/export/$` | GET → export |
| customer-options | `api/v1/^customers/options/$` | GET → options |
| customer-stats | `api/v1/^customers/stats/$` | GET → stats |
| customer-detail | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update；DELETE → destroy |
| customer-activity-history | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/activity-history/$` | GET → activity_history |
| customer-archive | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |
| customer-assignments | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/assignments/$` | GET → assignments |
| customer-attention-history | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/attention-history/$` | GET → attention_history |
| customer-business-snapshot-history | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/business-snapshot-history/$` | GET → business_snapshot_history |
| customer-collaborators | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/collaborators/$` | POST → collaborators |
| customer-contacts | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/contacts/$` | GET → contacts；POST → contacts |
| customer-end-collaborator | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/collaborators/(?P<employee_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/end/$` | POST → end_collaborator |
| customer-entities | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/entities/$` | GET → entities；POST → entities |
| customer-grade-history | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/grade-history/$` | GET → grade_history |
| customer-restore | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/restore/$` | POST → restore |
| customer-set-activity | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-activity/$` | POST → set_activity |
| customer-set-attention | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-attention/$` | POST → set_attention |
| customer-set-business-snapshot | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-business-snapshot/$` | POST → set_business_snapshot |
| customer-set-classification | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-classification/$` | POST → set_classification |
| customer-set-grade | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-grade/$` | POST → set_grade |
| customer-set-source | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-source/$` | POST → set_source |
| customer-source-history | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/source-history/$` | GET → source_history |
| customer-summary | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/summary/$` | GET → summary |
| customer-timeline | `api/v1/^customers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/timeline/$` | GET → timeline |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | customers.view_customeraccount |
| retrieve | customers.view_customeraccount |
| create | customers.add_customeraccount |
| destroy | customers.delete_customeraccount |
| partial_update | customers.change_customeraccount |
| archive | customers.change_customeraccount |
| restore | customers.change_customeraccount |
| summary | customers.view_customeraccount |
| timeline | crm.view_customertimelineevent |
| assignments | customers.view_customerassignment |
| collaborators.POST | customers.add_customerassignment |
| end_collaborator.POST | customers.change_customerassignment |
| entities.GET | customers.view_customertransactionentity |
| entities.POST | customers.add_customertransactionentity |
| contacts.GET | customers.view_customercontact |
| contacts.POST | customers.add_customercontact |
| attention_history | customers.view_customerattentionreview |
| set_attention | customers.add_customerattentionreview |
| options | customers.view_customeraccount |
| create_tag | customers.add_customertag |
| duplicate_check | customers.view_customeraccount |
| grade_history | customers.view_customergradereview |
| set_grade | customers.add_customergradereview |
| source_history | customers.view_customersourceattribution |
| set_source | customers.add_customersourceattribution |
| activity_history | customers.view_customeractivityreview |
| set_activity | customers.add_customeractivityreview |
| set_classification | customers.change_customeraccount |
| business_snapshot_history | customers.view_customerbusinesssnapshot |
| set_business_snapshot | customers.add_customerbusinesssnapshot |
| stats | customers.view_customeraccount |
| export | customers.view_customeraccount |
| bulk_add_tags | customers.change_customeraccount |

### CustomerEntityViewSet

源码：[apps/customers/api/views.py:1083](../../src/backend/apps/customers/api/views.py#L1083)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-entity-detail | `api/v1/^customer-entities/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update |
| customer-entity-addresses | `api/v1/^customer-entities/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/addresses/$` | GET → addresses；POST → addresses |
| customer-entity-archive | `api/v1/^customer-entities/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |
| customer-entity-roles | `api/v1/^customer-entities/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/roles/$` | GET → roles；POST → roles |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.view_customertransactionentity |
| partial_update | customers.change_customertransactionentity |
| archive | customers.change_customertransactionentity |
| roles.GET | customers.view_customertransactionentityrole |
| roles.POST | customers.add_customertransactionentityrole |
| addresses.GET | customers.view_customerentityaddress |
| addresses.POST | customers.add_customerentityaddress |

### CustomerAddressViewSet

源码：[apps/customers/api/views.py:1184](../../src/backend/apps/customers/api/views.py#L1184)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-address-detail | `api/v1/^customer-addresses/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update |
| customer-address-archive | `api/v1/^customer-addresses/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |
| customer-address-usages | `api/v1/^customer-addresses/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/usages/$` | GET → usages；POST → usages |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.view_customerentityaddress |
| partial_update | customers.change_customerentityaddress |
| archive | customers.change_customerentityaddress |
| usages.GET | customers.view_customerentityaddressusage |
| usages.POST | customers.add_customerentityaddressusage |

### CustomerContactViewSet

源码：[apps/customers/api/views.py:1261](../../src/backend/apps/customers/api/views.py#L1261)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| contact-list | `api/v1/^contacts/$` | GET → list |
| contact-bulk-create-tasks | `api/v1/^contacts/bulk-create-tasks/$` | POST → bulk_create_tasks |
| contact-bulk-mark-left | `api/v1/^contacts/bulk-mark-left/$` | POST → bulk_mark_left |
| contact-configuration | `api/v1/^contacts/options/$` | GET → configuration |
| contact-duplicate-check | `api/v1/^contacts/duplicate-check/$` | GET → duplicate_check |
| contact-detail | `api/v1/^contacts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update；DELETE → destroy |
| contact-archive | `api/v1/^contacts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |
| contact-employment-history | `api/v1/^contacts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/employment-history/$` | GET → employment_history；POST → employment_history |
| contact-mark-left | `api/v1/^contacts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/mark-left/$` | POST → mark_left |
| contact-methods | `api/v1/^contacts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/methods/$` | GET → methods；POST → methods |
| contact-roles | `api/v1/^contacts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/roles/$` | GET → roles；POST → roles |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | customers.view_customercontact |
| retrieve | customers.view_customercontact |
| destroy | customers.delete_customercontact |
| partial_update | customers.change_customercontact |
| archive | customers.change_customercontact |
| duplicate_check | customers.view_customercontact |
| configuration | customers.view_customercontact |
| employment_history.GET | customers.view_customercontact |
| employment_history.POST | customers.change_customercontact |
| mark_left | customers.change_customercontact |
| bulk_mark_left | customers.bulk_change_customercontact |
| bulk_create_tasks | customers.bulk_create_contact_task |
| methods.GET | customers.view_customercontactmethod |
| methods.POST | customers.add_customercontactmethod |
| roles.GET | customers.view_customercontactrole |
| roles.POST | customers.add_customercontactrole |

类内直接权限判断：

- 第 1513 行：`request.user.has_perm('customers.view_sensitive_customercontactmethod')`

### ContactMethodViewSet

源码：[apps/customers/api/views.py:1567](../../src/backend/apps/customers/api/views.py#L1567)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| contact-method-detail | `api/v1/^contact-methods/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update |
| contact-method-archive | `api/v1/^contact-methods/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.view_customercontactmethod |
| partial_update | customers.change_customercontactmethod |
| archive | customers.change_customercontactmethod |

类内直接权限判断：

- 第 1594 行：`request.user.has_perm('customers.view_sensitive_customercontactmethod')`
- 第 1665 行：`request.user.has_perm('customers.view_sensitive_customercontactmethod')`
- 第 1690 行：`request.user.has_perm('customers.view_sensitive_customercontactmethod')`

### EntityRoleViewSet

源码：[apps/customers/api/views.py:1761](../../src/backend/apps/customers/api/views.py#L1761)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-entity-role-detail | `api/v1/^customer-entity-roles/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| customer-entity-role-end | `api/v1/^customer-entity-roles/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/end/$` | POST → end |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.view_customertransactionentityrole |
| end | customers.change_customertransactionentityrole |

### AddressUsageViewSet

源码：[apps/customers/api/views.py:1777](../../src/backend/apps/customers/api/views.py#L1777)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-address-usage-detail | `api/v1/^customer-address-usages/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| customer-address-usage-end | `api/v1/^customer-address-usages/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/end/$` | POST → end |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.view_customerentityaddressusage |
| end | customers.change_customerentityaddressusage |

### ContactRoleViewSet

源码：[apps/customers/api/views.py:1794](../../src/backend/apps/customers/api/views.py#L1794)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| contact-role-detail | `api/v1/^contact-roles/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| contact-role-end | `api/v1/^contact-roles/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/end/$` | POST → end |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.view_customercontactrole |
| end | customers.change_customercontactrole |

### CustomerTransferRequestViewSet

源码：[apps/customers/api/governance_views.py:67](../../src/backend/apps/customers/api/governance_views.py#L67)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-transfer-request-list | `api/v1/^customer-transfer-requests/$` | GET → list；POST → create |
| customer-transfer-request-detail | `api/v1/^customer-transfer-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| customer-transfer-request-approve | `api/v1/^customer-transfer-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/approve/$` | POST → approve |
| customer-transfer-request-cancel | `api/v1/^customer-transfer-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cancel/$` | POST → cancel |
| customer-transfer-request-reject | `api/v1/^customer-transfer-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/reject/$` | POST → reject |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | customers.transfer_customer |
| retrieve | customers.transfer_customer |
| create | customers.transfer_customer |
| approve | customers.approve_customer_transfer |
| reject | customers.approve_customer_transfer |
| cancel | customers.transfer_customer |

### CustomerAccessGrantViewSet

源码：[apps/customers/api/governance_views.py:192](../../src/backend/apps/customers/api/governance_views.py#L192)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-access-grant-revoke | `api/v1/^customer-access-grants/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/revoke/$` | POST → revoke |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| revoke | customers.manage_customer_access |

### CustomerDuplicateCaseViewSet

源码：[apps/customers/api/governance_views.py:210](../../src/backend/apps/customers/api/governance_views.py#L210)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-duplicate-case-list | `api/v1/^customer-duplicate-cases/$` | GET → list；POST → create |
| customer-duplicate-case-detail | `api/v1/^customer-duplicate-cases/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| customer-duplicate-case-dismiss | `api/v1/^customer-duplicate-cases/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/dismiss/$` | POST → dismiss |
| customer-duplicate-case-merge | `api/v1/^customer-duplicate-cases/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/merge/$` | POST → merge |
| customer-duplicate-case-merge-preview | `api/v1/^customer-duplicate-cases/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/merge-preview/$` | POST → merge_preview |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | customers.merge_customer |
| retrieve | customers.merge_customer |
| create | customers.merge_customer |
| dismiss | customers.merge_customer |
| merge_preview | customers.merge_customer |
| merge | customers.merge_customer |

### CustomerDuplicateCandidateViewSet

源码：[apps/customers/api/governance_views.py:339](../../src/backend/apps/customers/api/governance_views.py#L339)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-duplicate-candidate-decide | `api/v1/^customer-duplicate-candidates/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/decide/$` | POST → decide |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| decide | customers.merge_customer |

### CustomerMergeOperationViewSet

源码：[apps/customers/api/governance_views.py:381](../../src/backend/apps/customers/api/governance_views.py#L381)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-merge-detail | `api/v1/^customer-merges/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | customers.merge_customer |

### ComplaintViewSet

源码：[apps/customers/api/complaint_views.py:79](../../src/backend/apps/customers/api/complaint_views.py#L79)。

权限类：IsAuthenticated、HasActiveEmployee、ComplaintActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| complaint-list | `api/v1/^complaints/$` | GET → list；POST → create |
| complaint-options | `api/v1/^complaints/options/$` | GET → options |
| complaint-stats | `api/v1/^complaints/stats/$` | GET → stats |
| complaint-detail | `api/v1/^complaints/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| complaint-attachment-preview | `api/v1/^complaints/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/attachments/(?P<attachment_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/preview/$` | GET → attachment_preview |
| complaint-attachments | `api/v1/^complaints/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/attachments/$` | POST → attachments |
| complaint-progress | `api/v1/^complaints/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/progress/$` | POST → progress |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | customers.view_customercomplaint |
| retrieve | customers.view_customercomplaint |
| create | customers.add_customercomplaint |
| partial_update | customers.change_customercomplaint |
| options | customers.view_customercomplaint |
| stats | customers.view_customercomplaint |
| progress | customers.process_customer_complaint |
| attachment_preview | customers.view_customercomplaint |

类内直接权限判断：

- 第 289 行：`request.user.has_perm('customers.close_customer_complaint')`

## 沟通记录 (crm)

1 个已注册处理类，3 条路由注册，3 个映射中的权限码。

### CommunicationViewSet

源码：[apps/crm/api/views.py:27](../../src/backend/apps/crm/api/views.py#L27)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| communication-list | `api/v1/^communications/$` | GET → list；POST → create |
| communication-detail | `api/v1/^communications/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update |
| communication-archive | `api/v1/^communications/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | crm.view_customercommunication |
| retrieve | crm.view_customercommunication |
| create | crm.add_customercommunication |
| partial_update | crm.change_customercommunication |
| archive | crm.change_customercommunication |

## 任务与审批 (workflow)

4 个已注册处理类，28 条路由注册，10 个映射中的权限码。

### TaskSourceOptionsView

源码：[apps/workflow/api/views.py:458](../../src/backend/apps/workflow/api/views.py#L458)。

权限类：HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| task-source-options | `api/v1/task-source-options/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

类内直接权限判断：

- 第 465 行：`request.user.has_perm('workflow.view_businesstask')`

### TaskViewSet

源码：[apps/workflow/api/views.py:75](../../src/backend/apps/workflow/api/views.py#L75)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| task-list | `api/v1/^tasks/$` | GET → list；POST → create |
| task-bulk-complete | `api/v1/^tasks/bulk-complete/$` | POST → bulk_complete |
| task-bulk-complete-preview | `api/v1/^tasks/bulk-complete/preview/$` | POST → bulk_complete_preview |
| task-bulk-reassign | `api/v1/^tasks/bulk-reassign/$` | POST → bulk_reassign |
| task-bulk-reassign-preview | `api/v1/^tasks/bulk-reassign/preview/$` | POST → bulk_reassign_preview |
| task-options | `api/v1/^tasks/options/$` | GET → options |
| task-summary | `api/v1/^tasks/summary/$` | GET → summary |
| task-detail | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update；DELETE → destroy |
| task-activity | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/activity/$` | GET → activity |
| task-attachment | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/attachments/(?P<file_id>[0-9a-f-]+)/(?P<disposition>preview\|download)/$` | GET → attachment |
| task-block | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/block/$` | POST → block |
| task-cancel | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cancel/$` | POST → cancel |
| task-complete | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/complete/$` | POST → complete |
| task-reassign | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/reassign/$` | POST → reassign |
| task-reschedule | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/reschedule/$` | POST → reschedule |
| task-reschedule-preview | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/reschedule-preview/$` | POST → reschedule_preview |
| task-resume | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/resume/$` | POST → resume |
| task-start | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/start/$` | POST → start |
| task-toggle-checklist | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/checklist/(?P<item_id>[0-9a-f-]+)/$` | PATCH → toggle_checklist |
| task-wait-customer | `api/v1/^tasks/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/wait-customer/$` | POST → wait_customer |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workflow.view_businesstask |
| retrieve | workflow.view_businesstask |
| create | workflow.add_businesstask |
| destroy | workflow.delete_businesstask |
| partial_update | workflow.change_businesstask |
| start | workflow.change_businesstask |
| complete | workflow.change_businesstask |
| cancel | workflow.change_businesstask |
| reassign | workflow.reassign_businesstask |
| summary | workflow.view_businesstask |
| options | workflow.view_businesstask |
| activity | workflow.view_businesstask |
| wait_customer | workflow.change_businesstask |
| block | workflow.change_businesstask |
| resume | workflow.change_businesstask |
| reschedule_preview | workflow.change_businesstask |
| reschedule | workflow.change_businesstask |
| toggle_checklist | workflow.change_businesstask |
| bulk_complete_preview | workflow.bulk_change_businesstask |
| bulk_complete | workflow.bulk_change_businesstask |
| bulk_reassign_preview | workflow.bulk_change_businesstask |
| bulk_reassign | workflow.bulk_change_businesstask |
| attachment | workflow.view_businesstask |

类内直接权限判断：

- 第 178 行：`request.user.has_perm('workflow.view_team_businesstask')`
- 第 179 行：`request.user.has_perm('workflow.view_all_businesstask')`

### ApprovalViewSet

源码：[apps/workflow/api/views.py:502](../../src/backend/apps/workflow/api/views.py#L502)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| approval-list | `api/v1/^approvals/$` | GET → list |
| approval-detail | `api/v1/^approvals/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| approval-approve | `api/v1/^approvals/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/approve/$` | POST → approve |
| approval-cancel | `api/v1/^approvals/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cancel/$` | POST → cancel |
| approval-reject | `api/v1/^approvals/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/reject/$` | POST → reject |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workflow.view_approvalrequest |
| retrieve | workflow.view_approvalrequest |
| approve | quotations.approve_quotation |
| reject | quotations.approve_quotation |
| cancel | workflow.change_approvalrequest |

### SlaTrackingViewSet

源码：[apps/workflow/api/views.py:591](../../src/backend/apps/workflow/api/views.py#L591)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sla-tracking-list | `api/v1/^sla-trackings/$` | GET → list |
| sla-tracking-detail | `api/v1/^sla-trackings/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workflow.view_slatracking |
| retrieve | workflow.view_slatracking |

## 询盘 (inquiries)

3 个已注册处理类，37 条路由注册，15 个映射中的权限码。

### InquiryHandlingSettingsViewSet

源码：[apps/inquiries/api/handling_settings.py:51](../../src/backend/apps/inquiries/api/handling_settings.py#L51)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| inquiry-handling-time-handling-settings | `api/v1/^inquiry-handling-time/settings/$` | GET → handling_settings；PUT → handling_settings |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| handling_settings.GET | workflow.view_slapolicy |
| handling_settings.PUT | workflow.manage_sla_policy |

### InquiryViewSet

源码：[apps/inquiries/api/views.py:80](../../src/backend/apps/inquiries/api/views.py#L80)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| inquiry-list | `api/v1/^inquiries/$` | GET → list；POST → create |
| inquiry-assignment-queue | `api/v1/^inquiries/assignment-queue/$` | GET → assignment_queue |
| inquiry-board | `api/v1/^inquiries/board/$` | GET → board |
| inquiry-bulk-assign | `api/v1/^inquiries/bulk-assign/$` | POST → bulk_assign |
| inquiry-bulk-mark-invalid | `api/v1/^inquiries/bulk-mark-invalid/$` | POST → bulk_mark_invalid |
| inquiry-demo-seed | `api/v1/^inquiries/demo-seed/$` | POST → demo_seed |
| inquiry-export | `api/v1/^inquiries/export/$` | GET → export |
| inquiry-metrics | `api/v1/^inquiries/metrics/$` | GET → metrics |
| inquiry-options | `api/v1/^inquiries/options/$` | GET → options |
| inquiry-detail | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update；DELETE → destroy |
| inquiry-assign | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/assign/$` | POST → assign |
| inquiry-attach-contact | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/attach-contact/$` | POST → attach_contact |
| inquiry-cancel | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cancel/$` | POST → cancel |
| inquiry-close | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/close/$` | POST → close |
| inquiry-confirm-requirements | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/confirm-requirements/$` | POST → confirm_requirements |
| inquiry-deletion-preview | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/deletion-preview/$` | GET → deletion_preview |
| inquiry-download-file | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/files/(?P<file_id>[0-9a-f-]{36})/download/$` | GET → download_file |
| inquiry-download-files | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/files-download/$` | GET → download_files |
| inquiry-draft | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/draft/$` | PATCH → draft |
| inquiry-files | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/files/$` | GET → files；POST → files |
| inquiry-follow-up | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/follow-up/$` | POST → follow_up |
| inquiry-image | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/images/(?P<file_id>[0-9a-f-]{36})/$` | GET → image |
| inquiry-items | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/items/$` | GET → items；POST → items |
| inquiry-mark-invalid | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/mark-invalid/$` | POST → mark_invalid |
| inquiry-mark-lost | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/mark-lost/$` | POST → mark_lost |
| inquiry-mark-quoted | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/mark-quoted/$` | POST → mark_quoted |
| inquiry-priority | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/priority/$` | POST → priority |
| inquiry-respond | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/respond/$` | POST → respond |
| inquiry-start | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/start/$` | POST → start |
| inquiry-submit | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/submit/$` | POST → submit |
| inquiry-sync-quotation | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/sync-quotation/$` | POST → sync_quotation |
| inquiry-tasks | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/tasks/$` | GET → tasks |
| inquiry-timeline | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/timeline/$` | GET → timeline |
| inquiry-upload-attachment | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/attachments/$` | POST → upload_attachment |
| inquiry-wang-image-upload | `api/v1/^inquiries/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/images/$` | POST → wang_image_upload |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | inquiries.view_inquiry |
| priority | inquiries.change_inquiry |
| export | inquiries.view_inquiry |
| retrieve | inquiries.view_inquiry |
| create | inquiries.add_inquiry |
| destroy | inquiries.delete_inquiry |
| deletion_preview | inquiries.delete_inquiry |
| partial_update | inquiries.change_inquiry |
| draft | inquiries.change_inquiry |
| submit | inquiries.change_inquiry |
| start | inquiries.change_inquiry |
| respond | inquiries.change_inquiry |
| attach_contact | inquiries.change_inquiry |
| confirm_requirements | inquiries.change_inquiry |
| sync_quotation | inquiries.change_inquiry |
| mark_quoted | inquiries.change_inquiry |
| follow_up | inquiries.change_inquiry |
| mark_lost | inquiries.change_inquiry |
| close | inquiries.change_inquiry |
| cancel | inquiries.change_inquiry |
| options | inquiries.view_inquiry |
| metrics | inquiries.view_inquiry |
| assignment_queue | inquiries.view_inquiry |
| board | inquiries.view_inquiry |
| assign | inquiries.assign_inquiry |
| bulk_assign | inquiries.bulk_change_inquiry |
| mark_invalid | inquiries.change_inquiry |
| bulk_mark_invalid | inquiries.bulk_change_inquiry |
| demo_seed | inquiries.add_inquiry |
| items.GET | inquiries.view_inquiryitem |
| items.POST | inquiries.add_inquiryitem |
| files.GET | inquiries.view_inquiryfilelink |
| files.POST | inquiries.add_inquiryfilelink |
| wang_image_upload | inquiries.change_inquiry |
| image | inquiries.view_inquiryfilelink |
| download_file | inquiries.view_inquiryfilelink |
| download_files | inquiries.view_inquiryfilelink |
| upload_attachment | inquiries.add_inquiryfilelink |
| tasks | workflow.view_businesstask |
| timeline | inquiries.view_inquiry |

类内直接权限判断：

- 第 232 行：`self.request.user.has_perm('inquiries.assign_inquiry')`
- 第 387 行：`request.user.has_perm('inquiries.assign_inquiry')`
- 第 772 行：`request.user.has_perm('inquiries.change_inquiry')`

### InquiryItemViewSet

源码：[apps/inquiries/api/views.py:893](../../src/backend/apps/inquiries/api/views.py#L893)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| inquiry-item-detail | `api/v1/^inquiry-items/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | PUT → update；PATCH → partial_update；DELETE → destroy |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| partial_update | inquiries.change_inquiryitem |
| destroy | inquiries.delete_inquiryitem |

## 报价 (quotations)

6 个已注册处理类，48 条路由注册，26 个映射中的权限码。

### QuotationViewSet

源码：[apps/quotations/api/views.py:121](../../src/backend/apps/quotations/api/views.py#L121)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| quotation-list | `api/v1/^quotations/$` | GET → list；POST → create |
| quotation-create-draft | `api/v1/^quotations/create-draft/$` | POST → create_draft |
| quotation-create-from-inquiry | `api/v1/^quotations/create-from-inquiry/$` | POST → create_from_inquiry |
| quotation-creation-options | `api/v1/^quotations/creation-options/$` | GET → creation_options |
| quotation-export | `api/v1/^quotations/export/$` | GET → export |
| quotation-inquiry-context | `api/v1/^quotations/inquiry-context/$` | GET → inquiry_context |
| quotation-options | `api/v1/^quotations/options/$` | GET → options |
| quotation-price-history | `api/v1/^quotations/price-history/$` | GET → price_history |
| quotation-summary | `api/v1/^quotations/summary/$` | GET → summary |
| quotation-detail | `api/v1/^quotations/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update；DELETE → destroy |
| quotation-accept | `api/v1/^quotations/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/accept/$` | POST → accept |
| quotation-cancel | `api/v1/^quotations/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cancel/$` | POST → cancel |
| quotation-inquiry-images | `api/v1/^quotations/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/inquiry-images/$` | GET → inquiry_images |
| quotation-lose | `api/v1/^quotations/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/lose/$` | POST → lose |
| quotation-versions | `api/v1/^quotations/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/versions/$` | GET → versions；POST → versions |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | quotations.view_quotation |
| summary | quotations.view_quotation |
| options | quotations.view_quotation |
| creation_options | quotations.add_quotation |
| inquiry_context | quotations.add_quotation |
| create_from_inquiry | quotations.add_quotation |
| export | quotations.export_quotation |
| retrieve | quotations.view_quotation |
| create | quotations.add_quotation |
| destroy | quotations.delete_quotation |
| create_draft | quotations.add_quotation |
| partial_update | quotations.change_quotation |
| versions.GET | quotations.view_quotationversion |
| versions.POST | quotations.add_quotationversion |
| accept | quotations.accept_quotation |
| lose | quotations.change_quotation |
| cancel | quotations.change_quotation |
| price_history | quotations.view_quotation |
| inquiry_images | quotations.view_quotation |

类内直接权限判断：

- 第 502 行：`request.user.has_perm('inquiries.change_inquiry')`
- 第 510 行：`request.user.has_perm('customers.add_customertransactionentity')`
- 第 416 行：`request.user.has_perm('customers.add_customertransactionentity')`

### QuotationTemplateViewSet

源码：[apps/quotations/api/views.py:661](../../src/backend/apps/quotations/api/views.py#L661)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| quotation-template-list | `api/v1/^quotation-templates/$` | GET → list |
| quotation-template-detail | `api/v1/^quotation-templates/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| quotation-template-seller-profile | `api/v1/^quotation-templates/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/seller-profile/$` | GET → seller_profile；PATCH → seller_profile |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | quotations.view_quotationtemplate |
| retrieve | quotations.view_quotationtemplate |
| seller_profile | quotations.change_quotationtemplate |

### QuotationVersionViewSet

源码：[apps/quotations/api/views.py:743](../../src/backend/apps/quotations/api/views.py#L743)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| quotation-version-detail | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| quotation-version-diff | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/diff/$` | GET → diff |
| quotation-version-dispatch | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/dispatch/$` | POST → dispatch_quote |
| quotation-version-dispatches | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/dispatches/$` | GET → dispatches |
| quotation-version-documents | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/documents/$` | GET → documents |
| quotation-version-download-formal-document | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/formal-document-download/$` | GET → download_formal_document |
| quotation-version-download-formal-xlsx | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/formal-xlsx-download/$` | GET → download_formal_xlsx |
| quotation-version-email-attempts | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/email-attempts/$` | GET → email_attempts |
| quotation-version-email-dispatch | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/email-dispatch/$` | POST → email_dispatch |
| quotation-version-generate-document | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/generate-document/$` | POST → generate_document |
| quotation-version-generate-formal-pdf | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/generate-formal-pdf/$` | POST → generate_formal_pdf |
| quotation-version-generate-sample-invoice | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/generate-sample-invoice/$` | POST → generate_sample_invoice |
| quotation-version-issue | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/issue/$` | POST → issue |
| quotation-version-lines | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/lines/$` | GET → lines；POST → lines |
| quotation-version-lock | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/lock/$` | POST → lock |
| quotation-version-manual-dispatch | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/manual-dispatch/$` | POST → manual_dispatch |
| quotation-version-price-matrix | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/price-matrix/$` | GET → price_matrix；PUT → price_matrix |
| quotation-version-simulate-dispatch | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/simulate-dispatch/$` | POST → simulate_dispatch |
| quotation-version-submit-approval | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/submit-approval/$` | POST → submit_approval |
| quotation-version-tasks | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/tasks/$` | GET → tasks |
| quotation-version-upload-formal-document | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/formal-document/$` | POST → upload_formal_document |
| quotation-version-void | `api/v1/^quotation-versions/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/void/$` | POST → void |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | quotations.view_quotationversion |
| partial_update | quotations.change_quotationversion |
| lines.GET | quotations.view_quotationline |
| lines.POST | quotations.add_quotationline |
| lock | quotations.change_quotationversion |
| submit_approval | quotations.change_quotationversion |
| issue | quotations.issue_quotation |
| generate_document | quotations.issue_quotation |
| generate_formal_pdf | quotations.issue_quotation |
| download_formal_document | quotations.view_quotationdocument |
| download_formal_xlsx | quotations.view_quotationdocument |
| upload_formal_document | quotations.issue_quotation |
| generate_sample_invoice | quotations.change_quotationversion |
| dispatch_quote | quotations.dispatch_quotation |
| manual_dispatch | quotations.dispatch_quotation |
| email_dispatch | quotations.dispatch_quotation |
| email_attempts | quotations.dispatch_quotation |
| simulate_dispatch | quotations.dispatch_quotation |
| price_matrix.GET | quotations.view_quotationversion |
| price_matrix.PUT | quotations.change_quotationversion |
| documents | quotations.view_quotationdocument |
| dispatches | quotations.view_quotationdispatchrecord |
| tasks | workflow.view_businesstask |
| void | quotations.change_quotationversion |
| diff | quotations.view_quotationversion |

### QuotationEmailDispatchAttemptViewSet

源码：[apps/quotations/api/views.py:1298](../../src/backend/apps/quotations/api/views.py#L1298)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| quotation-email-attempt-resolve | `api/v1/^quotation-email-attempts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/resolve/$` | POST → resolve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| resolve | quotations.dispatch_quotation |

### QuotationLineViewSet

源码：[apps/quotations/api/views.py:1344](../../src/backend/apps/quotations/api/views.py#L1344)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| quotation-line-detail | `api/v1/^quotation-lines/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | PUT → update；PATCH → partial_update；DELETE → destroy |
| quotation-line-container-options | `api/v1/^quotation-lines/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/container-options/$` | GET → container_options |
| quotation-line-container-tiers | `api/v1/^quotation-lines/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/container-tiers/$` | GET → container_tiers；POST → container_tiers |
| quotation-line-packaging | `api/v1/^quotation-lines/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/packaging/$` | GET → packaging；PUT → packaging |
| quotation-line-product-image | `api/v1/^quotation-lines/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/product-image/$` | GET → product_image；POST → product_image；DELETE → product_image |
| quotation-line-quantity-tiers | `api/v1/^quotation-lines/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/quantity-tiers/$` | GET → quantity_tiers；POST → quantity_tiers |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| partial_update | quotations.change_quotationline |
| destroy | quotations.delete_quotationline |
| quantity_tiers.GET | quotations.view_quotationquantitytier |
| quantity_tiers.POST | quotations.add_quotationquantitytier |
| packaging.GET | quotations.view_quotationline |
| packaging.PUT | quotations.change_quotationline |
| container_tiers.GET | quotations.view_quotationcontainertier |
| container_tiers.POST | quotations.add_quotationcontainertier |
| container_options | quotations.view_quotationcontainerconfig |
| product_image.GET | quotations.view_quotationline |
| product_image.POST | quotations.change_quotationline |
| product_image.DELETE | quotations.change_quotationline |

### QuotationContainerTierViewSet

源码：[apps/quotations/api/views.py:1546](../../src/backend/apps/quotations/api/views.py#L1546)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| quotation-container-tier-detail | `api/v1/^quotation-container-tiers/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | DELETE → destroy |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| destroy | quotations.delete_quotationcontainertier |

## 销售订单 (sales_orders)

1 个已注册处理类，11 条路由注册，0 个映射中的权限码。

### SalesOrderViewSet

源码：[apps/sales_orders/api/views.py:84](../../src/backend/apps/sales_orders/api/views.py#L84)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sales-order-list | `api/v1/^sales-orders/$` | GET → list；POST → create |
| sales-order-options | `api/v1/^sales-orders/options/$` | GET → options |
| sales-order-quotation-options | `api/v1/^sales-orders/quotation-options/$` | GET → quotation_options |
| sales-order-detail | `api/v1/^sales-orders/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| sales-order-business-file | `api/v1/^sales-orders/(?P<pk>[^/.]+)/business-files/(?P<file_id>[^/.]+)/$` | GET → business_file |
| sales-order-cancel-batch | `api/v1/^sales-orders/(?P<pk>[^/.]+)/delivery-batches/(?P<batch_id>[^/.]+)/cancel/$` | POST → cancel_batch |
| sales-order-collaboration-events | `api/v1/^sales-orders/(?P<pk>[^/.]+)/collaboration-events/$` | POST → collaboration_events |
| sales-order-complete | `api/v1/^sales-orders/(?P<pk>[^/.]+)/complete/$` | POST → complete |
| sales-order-confirm | `api/v1/^sales-orders/(?P<pk>[^/.]+)/confirm/$` | POST → confirm |
| sales-order-confirmed-change | `api/v1/^sales-orders/(?P<pk>[^/.]+)/confirmed-change/$` | POST → confirmed_change |
| sales-order-upload-evidence | `api/v1/^sales-orders/(?P<pk>[^/.]+)/evidence/$` | POST → upload_evidence |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

## 打样与样品库存 (samples)

6 个已注册处理类，69 条路由注册，34 个映射中的权限码。

### SampleRequestViewSet

源码：[apps/samples/api/views.py:121](../../src/backend/apps/samples/api/views.py#L121)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sample-request-list | `api/v1/^sample-requests/$` | GET → list；POST → create |
| sample-request-application-create | `api/v1/^sample-requests/applications/$` | POST → application_create |
| sample-request-bulk-remind | `api/v1/^sample-requests/bulk-remind/$` | POST → bulk_remind |
| sample-request-bulk-transfer | `api/v1/^sample-requests/bulk-transfer/$` | POST → bulk_transfer |
| sample-request-create-from-inquiry | `api/v1/^sample-requests/create-from-inquiry/$` | POST → create_from_inquiry |
| sample-request-create-from-quotation | `api/v1/^sample-requests/create-from-quotation/$` | POST → create_from_quotation |
| sample-request-export | `api/v1/^sample-requests/export/$` | GET → export |
| sample-request-form-context | `api/v1/^sample-requests/form-context/$` | GET → form_context |
| sample-request-form-options | `api/v1/^sample-requests/form-options/$` | GET → form_options |
| sample-request-material-candidates | `api/v1/^sample-requests/material-candidates/$` | GET → material_candidates |
| sample-request-material-reference-options | `api/v1/^sample-requests/material-reference-options/$` | GET → material_reference_options |
| sample-request-material-units | `api/v1/^sample-requests/material-units/$` | GET → material_units |
| sample-request-options | `api/v1/^sample-requests/options/$` | GET → options |
| sample-request-summary | `api/v1/^sample-requests/summary/$` | GET → summary |
| sample-request-detail | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update；DELETE → destroy |
| sample-request-application-resubmit | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/application-resubmit/$` | POST → application_resubmit |
| sample-request-business-file | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/business-files/(?P<file_id>[^/.]+)/$` | GET → business_file |
| sample-request-cancel | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cancel/$` | POST → cancel |
| sample-request-complete | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/complete/$` | POST → complete |
| sample-request-confirm | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/confirm/$` | POST → confirm |
| sample-request-create-requotation | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/feedback/(?P<feedback_id>[^/.]+)/create-requotation/$` | POST → create_requotation |
| sample-request-cutting-parameters | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/cutting-parameters/$` | POST → cutting_parameters |
| sample-request-director-review | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/director-review/$` | POST → director_review |
| sample-request-fee-approval-approve | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/fee-approval/approve/$` | POST → fee_approval_approve |
| sample-request-fee-approval-reject | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/fee-approval/reject/$` | POST → fee_approval_reject |
| sample-request-fee-records | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/fee-records/$` | GET → fee_records；POST → fee_records |
| sample-request-feedback | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/feedback/$` | GET → feedback；POST → feedback |
| sample-request-files | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/files/$` | GET → files；POST → files |
| sample-request-finance-confirm | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/finance-confirm/$` | POST → finance_confirm |
| sample-request-form | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/form/$` | PATCH → form |
| sample-request-items | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/items/$` | GET → items；POST → items |
| sample-request-materials | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/materials/$` | GET → materials；PUT → materials |
| sample-request-metalwork-parameters | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/metalwork-parameters/$` | POST → metalwork_parameters |
| sample-request-no-materials | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/no-materials/$` | POST → no_materials |
| sample-request-pmc-approve | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/pmc-approve/$` | POST → pmc_approve |
| sample-request-production-report | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/production-report/$` | POST → production_report |
| sample-request-reject | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/reject/$` | POST → reject |
| sample-request-requotation-options | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/feedback/(?P<feedback_id>[^/.]+)/requotation-options/$` | GET → requotation_options |
| sample-request-shipments | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/shipments/$` | GET → shipments；POST → shipments |
| sample-request-start-preparing | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/start-preparing/$` | POST → start_preparing |
| sample-request-submit | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/submit/$` | POST → submit |
| sample-request-tasks | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/tasks/$` | GET → tasks |
| sample-request-upload-fee-evidence | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/fee-evidence/$` | POST → upload_fee_evidence |
| sample-request-warehouse-review | `api/v1/^sample-requests/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/warehouse-review/$` | GET → warehouse_review；PUT → warehouse_review |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| no_materials | samples.edit_sample_materials |
| production_report | samples.change_samplerequest |
| material_units | samples.view_samplerequest |
| material_reference_options | samples.edit_sample_materials |
| material_candidates | samples.edit_sample_materials |
| materials.GET | samples.view_samplerequest |
| materials.PUT | samples.edit_sample_materials |
| warehouse_review.GET | samples.view_samplerequest |
| warehouse_review.PUT | samples.review_sample_materials |
| application_create | samples.add_samplerequest |
| application_resubmit | samples.add_samplerequest |
| director_review | samples.review_sample_application |
| list | samples.view_samplerequest |
| retrieve | samples.view_samplerequest |
| create | samples.add_samplerequest |
| destroy | samples.delete_samplerequest |
| create_from_inquiry | samples.add_samplerequest |
| create_from_quotation | samples.add_samplerequest |
| partial_update | samples.change_samplerequest |
| items.GET | samples.view_sampleitem |
| items.POST | samples.add_sampleitem |
| submit | samples.change_samplerequest |
| start_preparing | samples.change_samplerequest |
| fee_records.GET | samples.view_samplefeerecord |
| fee_records.POST | samples.decide_sample_fee |
| fee_approval_approve | samples.change_samplefeerecord |
| fee_approval_reject | samples.change_samplefeerecord |
| shipments.GET | samples.view_sampleshipment |
| shipments.POST | samples.add_sampleshipment |
| feedback.GET | samples.view_samplefeedback |
| feedback.POST | samples.add_samplefeedback |
| requotation_options | samples.view_samplefeedback |
| create_requotation | samples.change_samplefeedback |
| files.GET | samples.view_samplefilelink |
| files.POST | samples.add_samplefilelink |
| upload_fee_evidence | samples.add_samplefilelink |
| finance_confirm | samples.decide_sample_fee |
| pmc_approve | samples.change_samplerequest |
| metalwork_parameters | samples.change_samplerequest |
| cutting_parameters | samples.change_samplerequest |
| business_file | samples.view_samplerequest |
| tasks | workflow.view_businesstask |
| complete | samples.change_samplerequest |
| confirm | samples.change_samplerequest |
| reject | samples.change_samplerequest |
| cancel | samples.view_samplerequest |
| summary | samples.view_samplerequest |
| options | samples.view_samplerequest |
| form_options | samples.view_samplerequest |
| form_context | samples.add_samplerequest |
| form | samples.view_samplerequest |
| export | samples.view_samplerequest |
| bulk_transfer | samples.change_samplerequest |
| bulk_remind | workflow.add_businesstask |

类内直接权限判断：

- 第 406 行：`request.user.has_perm('inquiries.view_inquiry')`
- 第 436 行：`request.user.has_perm('quotations.view_quotationversion')`
- 第 1052 行：`request.user.has_perm('quotations.view_quotationversion')`
- 第 1117 行：`request.user.has_perm('quotations.view_quotationversion')`
- 第 1119 行：`request.user.has_perm('quotations.add_quotationversion')`
- 第 355 行：`request.user.has_perm('samples.complete_sample_requirements')`
- 第 357 行：`request.user.has_perm('samples.change_samplerequest')`
- 第 645 行：`request.user.has_perm('inquiries.view_inquiry')`
- 第 647 行：`request.user.has_perm('quotations.view_quotationversion')`
- 第 782 行：`request.user.has_perm('samples.change_samplerequest')`
- 第 303 行：`request.user.has_perm('inquiries.view_inquiry')`
- 第 307 行：`request.user.has_perm('quotations.view_quotationversion')`

### SampleItemViewSet

源码：[apps/samples/api/views.py:1275](../../src/backend/apps/samples/api/views.py#L1275)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sample-item-detail | `api/v1/^sample-items/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | PUT → update；PATCH → partial_update；DELETE → destroy |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| partial_update | samples.change_sampleitem |
| destroy | samples.delete_sampleitem |

### SampleShipmentViewSet

源码：[apps/samples/api/views.py:1327](../../src/backend/apps/samples/api/views.py#L1327)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sample-shipment-detail | `api/v1/^sample-shipments/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| sample-shipment-deliver | `api/v1/^sample-shipments/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/deliver/$` | POST → deliver |
| sample-shipment-exception | `api/v1/^sample-shipments/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/exception/$` | POST → exception |
| sample-shipment-progress | `api/v1/^sample-shipments/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/progress/$` | POST → progress |
| sample-shipment-ship | `api/v1/^sample-shipments/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/ship/$` | POST → ship |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | samples.view_sampleshipment |
| ship | samples.ship_sample |
| deliver | samples.change_sampleshipment |
| exception | samples.change_sampleshipment |
| progress | samples.change_sampleshipment |

### SampleInventoryLineViewSet

源码：[apps/samples/api/inventory_views.py:38](../../src/backend/apps/samples/api/inventory_views.py#L38)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sample-inventory-list | `api/v1/^sample-inventory/$` | GET → list |
| sample-inventory-eligible | `api/v1/^sample-inventory/eligible/$` | GET → eligible |
| sample-inventory-finished-goods-options | `api/v1/^sample-inventory/finished-goods-options/$` | GET → finished_goods_options |
| sample-inventory-options | `api/v1/^sample-inventory/options/$` | GET → options |
| sample-inventory-receipt-detail | `api/v1/^sample-inventory/receipts/(?P<receipt_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → receipt_detail；DELETE → receipt_detail |
| sample-inventory-receipts | `api/v1/^sample-inventory/receipts/$` | POST → receipts |
| sample-inventory-summary | `api/v1/^sample-inventory/summary/$` | GET → summary |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | samples.view_sampleinventoryline |
| summary | samples.view_sampleinventoryline |
| options | samples.view_sampleinventoryline |
| eligible | samples.add_sampleinventoryreceipt |
| finished_goods_options | samples.add_sampleinventoryreceipt |
| receipts | samples.add_sampleinventoryreceipt |
| receipt_detail | samples.view_sampleinventoryline |
| receipt_detail.DELETE | samples.delete_sampleinventoryreceipt |

### SampleInventoryOutboundLineViewSet

源码：[apps/samples/api/outbound_views.py:37](../../src/backend/apps/samples/api/outbound_views.py#L37)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sample-outbound-list | `api/v1/^sample-outbound/$` | GET → list |
| sample-outbound-document-detail | `api/v1/^sample-outbound/documents/(?P<outbound_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → document_detail；DELETE → document_detail |
| sample-outbound-documents | `api/v1/^sample-outbound/documents/$` | POST → documents |
| sample-outbound-eligible | `api/v1/^sample-outbound/eligible/$` | GET → eligible |
| sample-outbound-options | `api/v1/^sample-outbound/options/$` | GET → options |
| sample-outbound-summary | `api/v1/^sample-outbound/summary/$` | GET → summary |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | samples.view_sampleinventoryoutboundline |
| summary | samples.view_sampleinventoryoutboundline |
| options | samples.view_sampleinventoryoutboundline |
| eligible | samples.add_sampleinventoryoutbound |
| documents | samples.add_sampleinventoryoutbound |
| document_detail | samples.view_sampleinventoryoutboundline |
| document_detail.DELETE | samples.delete_sampleinventoryoutbound |

### SampleInventoryLoanLineViewSet

源码：[apps/samples/api/loan_views.py:32](../../src/backend/apps/samples/api/loan_views.py#L32)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| sample-loan-list | `api/v1/^sample-loans/$` | GET → list |
| sample-loan-document-detail | `api/v1/^sample-loans/documents/(?P<loan_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → document_detail；DELETE → document_detail |
| sample-loan-documents | `api/v1/^sample-loans/documents/$` | POST → documents |
| sample-loan-eligible | `api/v1/^sample-loans/eligible/$` | GET → eligible |
| sample-loan-options | `api/v1/^sample-loans/options/$` | GET → options |
| sample-loan-summary | `api/v1/^sample-loans/summary/$` | GET → summary |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | samples.view_sampleinventoryloanline |
| summary | samples.view_sampleinventoryloanline |
| options | samples.view_sampleinventoryloanline |
| eligible | samples.add_sampleinventoryloan |
| documents | samples.add_sampleinventoryloan |
| document_detail | samples.view_sampleinventoryloanline |
| document_detail.DELETE | samples.delete_sampleinventoryloan |

## 产品与原料 (products)

4 个已注册处理类，6 条路由注册，6 个映射中的权限码。

### ProductOptionsView

源码：[apps/products/api/views.py:53](../../src/backend/apps/products/api/views.py#L53)。

权限类：IsAuthenticated、HasActiveEmployee、ProductOptionsPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| product-options | `api/v1/products/options/` | GET → list |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### RawMaterialOptionsView

源码：[apps/products/api/views.py:246](../../src/backend/apps/products/api/views.py#L246)。

权限类：IsAuthenticated、HasActiveEmployee、RawMaterialOptionsPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| raw-material-options | `api/v1/raw-materials/options/` | GET → list |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ProductInformationViewSet

源码：[apps/products/api/views.py:98](../../src/backend/apps/products/api/views.py#L98)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| product-information-list | `api/v1/^products/$` | GET → list；POST → create |
| product-information-detail | `api/v1/^products/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | products.view_productinformation |
| retrieve | products.view_productinformation |
| create | products.add_productinformation |
| update | products.change_productinformation |
| partial_update | products.change_productinformation |

### RawMaterialInformationViewSet

源码：[apps/products/api/views.py:318](../../src/backend/apps/products/api/views.py#L318)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| raw-material-information-list | `api/v1/^raw-materials/$` | GET → list；POST → create |
| raw-material-information-detail | `api/v1/^raw-materials/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | products.view_rawmaterialinformation |
| retrieve | products.view_rawmaterialinformation |
| create | products.add_rawmaterialinformation |
| update | products.change_rawmaterialinformation |
| partial_update | products.change_rawmaterialinformation |

## 生产订单 (production_tasks)

1 个已注册处理类，14 条路由注册，6 个映射中的权限码。

### ProductionTaskViewSet

源码：[apps/production_tasks/api/views.py:65](../../src/backend/apps/production_tasks/api/views.py#L65)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| production-task-list | `api/v1/^production-tasks/$` | GET → list；POST → create |
| production-task-create-from-sales-order | `api/v1/^production-tasks/create-from-sales-order/$` | POST → create_from_sales_order |
| production-task-export | `api/v1/^production-tasks/export/$` | GET → export；POST → export |
| production-task-options | `api/v1/^production-tasks/options/$` | GET → options |
| production-task-reserve-contract-number | `api/v1/^production-tasks/reserve-contract-number/$` | POST → reserve_contract_number |
| production-task-stats | `api/v1/^production-tasks/stats/$` | GET → stats |
| production-task-detail | `api/v1/^production-tasks/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| production-task-business-file | `api/v1/^production-tasks/(?P<pk>[^/.]+)/business-files/(?P<file_id>[^/.]+)/$` | GET → business_file |
| production-task-cancel | `api/v1/^production-tasks/(?P<pk>[^/.]+)/cancel/$` | POST → cancel |
| production-task-confirm | `api/v1/^production-tasks/(?P<pk>[^/.]+)/confirm/$` | POST → confirm |
| production-task-finish | `api/v1/^production-tasks/(?P<pk>[^/.]+)/finish/$` | POST → finish |
| production-task-pmc-decision | `api/v1/^production-tasks/(?P<pk>[^/.]+)/pmc-decision/$` | POST → pmc_decision |
| production-task-start | `api/v1/^production-tasks/(?P<pk>[^/.]+)/start/$` | POST → start |
| production-task-submit | `api/v1/^production-tasks/(?P<pk>[^/.]+)/submit/$` | POST → submit |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | production_tasks.view_productiontask |
| retrieve | production_tasks.view_productiontask |
| business_file | production_tasks.view_productiontask |
| create | production_tasks.add_productiontask |
| create_from_sales_order | production_tasks.add_productiontask |
| reserve_contract_number | production_tasks.add_productiontask |
| partial_update | production_tasks.change_productiontask |
| options | production_tasks.view_productiontask |
| stats | production_tasks.view_productiontask |
| export | production_tasks.view_productiontask |
| submit | production_tasks.submit_productiontask |
| confirm | production_tasks.confirm_productiontask |
| pmc_decision | production_tasks.confirm_productiontask |
| start | production_tasks.start_productiontask |
| cancel | production_tasks.change_productiontask |
| finish | production_tasks.change_productiontask |

## 计划排产 (production_scheduling)

2 个已注册处理类，9 条路由注册，4 个映射中的权限码。

### ProductionScheduleViewSet

源码：[apps/production_scheduling/api/views.py:53](../../src/backend/apps/production_scheduling/api/views.py#L53)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| production-schedule-list | `api/v1/^production-schedules/$` | GET → list；POST → create |
| production-schedule-batch-create | `api/v1/^production-schedules/batch/$` | POST → batch_create |
| production-schedule-options | `api/v1/^production-schedules/options/$` | GET → options |
| production-schedule-task-candidate-detail | `api/v1/^production-schedules/task-candidates/(?P<task_id>[^/.]+)/$` | GET → task_candidate_detail |
| production-schedule-task-candidates | `api/v1/^production-schedules/task-candidates/$` | GET → task_candidates |
| production-schedule-task-file | `api/v1/^production-schedules/task-files/(?P<task_id>[^/.]+)/(?P<file_id>[^/.]+)/$` | GET → task_file |
| production-schedule-detail | `api/v1/^production-schedules/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| production-schedule-void | `api/v1/^production-schedules/(?P<pk>[^/.]+)/void/$` | POST → void |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | production_scheduling.view_productionschedule |
| retrieve | production_scheduling.view_productionschedule |
| task_candidates | production_scheduling.view_productionschedule |
| task_candidate_detail | production_scheduling.view_productionschedule |
| task_file | production_scheduling.view_productionschedule |
| options | production_scheduling.view_productionschedule |
| create | production_scheduling.add_productionschedule |
| batch_create | production_scheduling.add_productionschedule |
| partial_update | production_scheduling.change_productionschedule |
| void | production_scheduling.void_productionschedule |

### ProductionScheduleItemViewSet

源码：[apps/production_scheduling/api/views.py:410](../../src/backend/apps/production_scheduling/api/views.py#L410)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| production-schedule-item-list | `api/v1/^production-schedule-items/$` | GET → list |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | production_scheduling.view_productionschedule |

## BOM (boms)

3 个已注册处理类，50 条路由注册，5 个映射中的权限码。

### BomLineImageDraftViewSet

源码：[apps/boms/api/image_views.py:223](../../src/backend/apps/boms/api/image_views.py#L223)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| bom-line-image-draft-list | `api/v1/boms/<uuid:bom_id>/draft-line-images/` | POST → create |
| bom-line-image-draft-detail | `api/v1/boms/<uuid:bom_id>/draft-line-images/<uuid:draft_id>/` | DELETE → destroy |
| bom-line-image-draft-content | `api/v1/boms/<uuid:bom_id>/draft-line-images/<uuid:draft_id>/content/` | GET → content |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| create | boms.change_bom |
| destroy | boms.change_bom |
| content | boms.change_bom |

### BomLineImageViewSet

源码：[apps/boms/api/image_views.py:43](../../src/backend/apps/boms/api/image_views.py#L43)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| bom-line-image-list | `api/v1/boms/<uuid:bom_id>/lines/<uuid:line_id>/images/` | GET → list；POST → create |
| bom-line-image-detail | `api/v1/boms/<uuid:bom_id>/lines/<uuid:line_id>/images/<uuid:image_id>/` | DELETE → destroy |
| bom-line-image-content | `api/v1/boms/<uuid:bom_id>/lines/<uuid:line_id>/images/<uuid:image_id>/content/` | GET → content |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | boms.view_bom |
| create | boms.change_bom |
| destroy | boms.change_bom |
| content | boms.view_bom |

### BomViewSet

源码：[apps/boms/api/views.py:94](../../src/backend/apps/boms/api/views.py#L94)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| bom-list | `api/v1/^boms/$` | GET → list；POST → create |
| bom-create-auxiliary-reference | `api/v1/^boms/create-auxiliary-reference/$` | POST → create_auxiliary_reference |
| bom-editor-reference-options | `api/v1/^boms/editor-reference-options/$` | GET → editor_reference_options |
| bom-export | `api/v1/^boms/export/$` | GET → export；POST → export |
| bom-fabric-materials | `api/v1/^boms/fabric-materials/$` | GET → fabric_materials |
| bom-hardware-material-groups | `api/v1/^boms/hardware-material-groups/$` | GET → hardware_material_groups |
| bom-hardware-materials | `api/v1/^boms/hardware-materials/$` | GET → hardware_materials |
| bom-material-flow-preview | `api/v1/^boms/material-flow-preview/$` | POST → material_flow_preview |
| bom-options | `api/v1/^boms/options/$` | GET → options |
| bom-packaging-material-groups | `api/v1/^boms/packaging-material-groups/$` | GET → packaging_material_groups |
| bom-packaging-materials | `api/v1/^boms/packaging-materials/$` | GET → packaging_materials |
| bom-pipe-materials | `api/v1/^boms/pipe-materials/$` | GET → pipe_materials |
| bom-plastic-material-groups | `api/v1/^boms/plastic-material-groups/$` | GET → plastic_material_groups |
| bom-plastic-materials | `api/v1/^boms/plastic-materials/$` | GET → plastic_materials |
| bom-preview-import | `api/v1/^boms/preview-import/$` | POST → preview_import |
| bom-semi-finished-material-groups | `api/v1/^boms/semi-finished-material-groups/$` | GET → semi_finished_material_groups |
| bom-semi-finished-materials | `api/v1/^boms/semi-finished-materials/$` | GET → semi_finished_materials |
| bom-stats | `api/v1/^boms/stats/$` | GET → stats |
| bom-detail | `api/v1/^boms/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| bom-archive | `api/v1/^boms/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| bom-sync-order-quantity | `api/v1/^boms/(?P<pk>[^/.]+)/sync-order-quantity/$` | POST → sync_order_quantity |
| bom-verify | `api/v1/^boms/(?P<pk>[^/.]+)/verify/$` | POST → verify |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | boms.view_bom |
| retrieve | boms.view_bom |
| stats | boms.view_bom |
| export | boms.view_bom |
| options | boms.view_bom |
| hardware_materials | boms.change_bom |
| pipe_materials | boms.change_bom |
| material_flow_preview | boms.change_bom |
| fabric_materials | boms.change_bom |
| hardware_material_groups | boms.change_bom |
| plastic_materials | boms.change_bom |
| plastic_material_groups | boms.change_bom |
| packaging_materials | boms.change_bom |
| packaging_material_groups | boms.change_bom |
| semi_finished_materials | boms.change_bom |
| semi_finished_material_groups | boms.change_bom |
| editor_reference_options | boms.change_bom |
| create_auxiliary_reference | boms.change_bom |
| create | boms.add_bom |
| preview_import | boms.add_bom |
| partial_update | boms.change_bom |
| sync_order_quantity | boms.change_bom |
| verify | boms.verify_bom |
| archive | boms.delete_bom |

类内直接权限判断：

- 第 711 行：`request.user.has_perm('production_tasks.view_productiontask')`
- 第 241 行：`self.request.user.has_perm('production_tasks.view_productiontask')`
- 第 269 行：`request.user.has_perm('production_tasks.change_productiontask')`
- 第 411 行：`request.user.has_perm('production_tasks.change_productiontask')`
- 第 643 行：`request.user.has_perm(code)`

## 采购、供应商及退货 (procurement)

6 个已注册处理类，86 条路由注册，9 个映射中的权限码。

### SupplierViewSet

源码：[apps/procurement/api/views.py:124](../../src/backend/apps/procurement/api/views.py#L124)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| supplier-list | `api/v1/^suppliers/$` | GET → list；POST → create |
| supplier-options | `api/v1/^suppliers/options/$` | GET → options |
| supplier-stats | `api/v1/^suppliers/stats/$` | GET → stats |
| supplier-detail | `api/v1/^suppliers/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | procurement.view_supplier |
| retrieve | procurement.view_supplier |
| stats | procurement.view_supplier |
| options | procurement.view_supplier |
| create | procurement.add_supplier |
| update | procurement.change_supplier |
| partial_update | procurement.change_supplier |

### PurchaseOrderViewSet

源码：[apps/procurement/api/views.py:269](../../src/backend/apps/procurement/api/views.py#L269)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| purchase-order-list | `api/v1/^purchase-orders/$` | GET → list；POST → create |
| purchase-order-filter-options | `api/v1/^purchase-orders/filter-options/$` | GET → filter_options |
| purchase-order-options | `api/v1/^purchase-orders/options/$` | GET → options |
| purchase-order-source | `api/v1/^purchase-orders/source/$` | GET → source |
| purchase-order-stats | `api/v1/^purchase-orders/stats/$` | GET → stats |
| purchase-order-detail | `api/v1/^purchase-orders/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update；DELETE → destroy |
| purchase-order-complete | `api/v1/^purchase-orders/(?P<pk>[^/.]+)/complete/$` | POST → complete |
| purchase-order-confirm | `api/v1/^purchase-orders/(?P<pk>[^/.]+)/confirm/$` | POST → confirm |
| purchase-order-generate-sheets | `api/v1/^purchase-orders/(?P<pk>[^/.]+)/generate-sheets/$` | POST → generate_sheets |
| purchase-order-sheet-options | `api/v1/^purchase-orders/(?P<pk>[^/.]+)/sheet-options/$` | GET → sheet_options |
| purchase-order-submit | `api/v1/^purchase-orders/(?P<pk>[^/.]+)/submit/$` | POST → submit |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | procurement.view_purchaseorder |
| retrieve | procurement.view_purchaseorder |
| stats | procurement.view_purchaseorder |
| filter_options | procurement.view_purchaseorder |
| options | procurement.add_purchaseorder |
| source | procurement.add_purchaseorder |
| create | procurement.add_purchaseorder |
| update | procurement.add_purchaseorder |
| partial_update | procurement.add_purchaseorder |
| destroy | procurement.delete_purchaseorder |
| confirm | procurement.submit_purchaseorder |
| submit | procurement.submit_purchaseorder |
| complete | procurement.submit_purchaseorder |
| sheet_options | procurement.view_purchaseorder |
| generate_sheets | procurement.add_purchaseorder |

### PurchaseReturnViewSet

源码：[apps/procurement/api/return_views.py:59](../../src/backend/apps/procurement/api/return_views.py#L59)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| purchase-return-list | `api/v1/^purchase-returns/$` | GET → list |
| purchase-return-filter-options | `api/v1/^purchase-returns/filter-options/$` | GET → filter_options |
| purchase-return-stats | `api/v1/^purchase-returns/stats/$` | GET → stats |
| purchase-return-detail | `api/v1/^purchase-returns/(?P<pk>[^/.]+)/$` | GET → retrieve |
| purchase-return-complete | `api/v1/^purchase-returns/(?P<pk>[^/.]+)/complete/$` | POST → complete |
| purchase-return-confirm | `api/v1/^purchase-returns/(?P<pk>[^/.]+)/confirm/$` | POST → confirm |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | procurement.view_purchaseorder 或 inventory.receive_material 或 inventory.quality_confirm_material |
| retrieve | procurement.view_purchaseorder 或 inventory.receive_material 或 inventory.quality_confirm_material |
| stats | procurement.view_purchaseorder 或 inventory.receive_material 或 inventory.quality_confirm_material |
| filter_options | procurement.view_purchaseorder 或 inventory.receive_material 或 inventory.quality_confirm_material |
| confirm | procurement.submit_purchaseorder |
| complete | procurement.submit_purchaseorder |

### PurchaseRequestViewSet

源码：[apps/procurement/api/purchase_request_views.py:47](../../src/backend/apps/procurement/api/purchase_request_views.py#L47)。

权限类：HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| purchase-request-list | `api/v1/^purchase-requests/$` | GET → list；POST → create |
| purchase-request-options | `api/v1/^purchase-requests/options/$` | GET → options |
| purchase-request-detail | `api/v1/^purchase-requests/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| purchase-request-allocate | `api/v1/^purchase-requests/(?P<pk>[^/.]+)/allocate/$` | POST → allocate |
| purchase-request-cancel-allocation | `api/v1/^purchase-requests/(?P<pk>[^/.]+)/cancel-allocation/$` | POST → cancel_allocation |
| purchase-request-generate-supplier-order | `api/v1/^purchase-requests/(?P<pk>[^/.]+)/generate-supplier-order/$` | POST → generate_supplier_order |
| purchase-request-submit | `api/v1/^purchase-requests/(?P<pk>[^/.]+)/submit/$` | POST → submit |
| purchase-request-supplier-order-options | `api/v1/^purchase-requests/(?P<pk>[^/.]+)/supplier-order-options/$` | GET → supplier_order_options |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### PurchaseContractTemplateViewSet

源码：[apps/procurement/api/views.py:780](../../src/backend/apps/procurement/api/views.py#L780)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| purchase-contract-template-list | `api/v1/^purchase-contract-templates/$` | GET → list；POST → create |
| purchase-contract-template-detail | `api/v1/^purchase-contract-templates/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | procurement.view_purchaseorder |
| retrieve | procurement.view_purchaseorder |
| create | procurement.view_purchaseorder |
| update | procurement.view_purchaseorder |
| partial_update | procurement.view_purchaseorder |

### SupplierPurchaseSheetViewSet

源码：[apps/procurement/api/views.py:865](../../src/backend/apps/procurement/api/views.py#L865)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| supplier-purchase-sheet-list | `api/v1/^supplier-purchase-sheets/$` | GET → list |
| supplier-purchase-sheet-batch-download | `api/v1/^supplier-purchase-sheets/batch-download/$` | POST → batch_download |
| supplier-purchase-sheet-batch-publish | `api/v1/^supplier-purchase-sheets/batch-publish/$` | POST → batch_publish |
| supplier-purchase-sheet-options | `api/v1/^supplier-purchase-sheets/options/$` | GET → options |
| supplier-purchase-sheet-detail | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| supplier-purchase-sheet-download-pdf | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/download-pdf/$` | GET → download_pdf |
| supplier-purchase-sheet-download-xlsx | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/download-xlsx/$` | GET → download_xlsx |
| supplier-purchase-sheet-line-image | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/line-images/(?P<line_id>[0-9a-fA-F-]+)/$` | GET → line_image；POST → line_image；DELETE → line_image |
| supplier-purchase-sheet-new-version | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/new-version/$` | POST → new_version |
| supplier-purchase-sheet-preview-pdf | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/preview-pdf/$` | GET → preview_pdf |
| supplier-purchase-sheet-publish | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/publish/$` | POST → publish |
| supplier-purchase-sheet-seal-image | `api/v1/^supplier-purchase-sheets/(?P<pk>[^/.]+)/seal-image/$` | GET → seal_image；POST → seal_image；DELETE → seal_image |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | procurement.view_purchaseorder |
| options | procurement.view_purchaseorder |
| retrieve | procurement.view_purchaseorder |
| partial_update | procurement.add_purchaseorder |
| update | procurement.add_purchaseorder |
| preview_pdf | procurement.view_purchaseorder |
| publish | procurement.submit_purchaseorder |
| download_pdf | procurement.view_purchaseorder |
| download_xlsx | procurement.view_purchaseorder |
| new_version | procurement.add_purchaseorder |
| batch_download | procurement.view_purchaseorder |
| batch_publish | procurement.submit_purchaseorder |
| line_image.GET | procurement.view_purchaseorder |
| line_image.POST | procurement.add_purchaseorder |
| line_image.DELETE | procurement.add_purchaseorder |
| seal_image.GET | procurement.view_purchaseorder |
| seal_image.POST | procurement.add_purchaseorder |
| seal_image.DELETE | procurement.add_purchaseorder |

## 库存与收货质检 (inventory)

5 个已注册处理类，31 条路由注册，16 个映射中的权限码。

### WarehouseViewSet

源码：[apps/inventory/api/views.py:168](../../src/backend/apps/inventory/api/views.py#L168)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| warehouse-list | `api/v1/^warehouses/$` | GET → list；POST → create |
| warehouse-detail | `api/v1/^warehouses/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | inventory.view_warehouse |
| retrieve | inventory.view_warehouse |
| create | inventory.add_warehouse |
| update | inventory.change_warehouse |
| partial_update | inventory.change_warehouse |

### WarehouseZoneViewSet

源码：[apps/inventory/api/views.py:195](../../src/backend/apps/inventory/api/views.py#L195)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| warehouse-zone-list | `api/v1/^warehouse-zones/$` | GET → list；POST → create |
| warehouse-zone-detail | `api/v1/^warehouse-zones/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | inventory.view_warehousezone |
| retrieve | inventory.view_warehousezone |
| create | inventory.add_warehousezone |
| update | inventory.change_warehousezone |
| partial_update | inventory.change_warehousezone |

### WarehouseLocationViewSet

源码：[apps/inventory/api/views.py:217](../../src/backend/apps/inventory/api/views.py#L217)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| warehouse-location-list | `api/v1/^warehouse-locations/$` | GET → list；POST → create |
| warehouse-location-detail | `api/v1/^warehouse-locations/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | inventory.view_warehouselocation |
| retrieve | inventory.view_warehouselocation |
| create | inventory.add_warehouselocation |
| update | inventory.change_warehouselocation |
| partial_update | inventory.change_warehouselocation |

### FinishedGoodsInventoryViewSet

源码：[apps/inventory/api/views.py:245](../../src/backend/apps/inventory/api/views.py#L245)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| finished-goods-inventory-list | `api/v1/^finished-goods-inventory/$` | GET → list |
| finished-goods-inventory-batch-receipts | `api/v1/^finished-goods-inventory/batch-receipts/$` | POST → batch_receipts |
| finished-goods-inventory-eligible-orders | `api/v1/^finished-goods-inventory/eligible-orders/$` | GET → eligible_orders |
| finished-goods-inventory-eligible-products | `api/v1/^finished-goods-inventory/eligible-products/$` | GET → eligible_products |
| finished-goods-inventory-options | `api/v1/^finished-goods-inventory/options/$` | GET → options |
| finished-goods-inventory-outbound-batches | `api/v1/^finished-goods-inventory/outbound-batches/$` | GET → outbound_batches |
| finished-goods-inventory-outbounds | `api/v1/^finished-goods-inventory/outbounds/$` | POST → outbounds |
| finished-goods-inventory-receipts | `api/v1/^finished-goods-inventory/receipts/$` | GET → receipts；POST → receipts |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | inventory.view_finishedgoodsreceipt |
| options | inventory.view_finishedgoodsreceipt |
| eligible_products | inventory.add_finishedgoodsreceipt |
| eligible_orders | inventory.add_finishedgoodsreceipt |
| receipts.GET | inventory.view_finishedgoodsreceipt |
| receipts.POST | inventory.add_finishedgoodsreceipt |
| batch_receipts | inventory.add_finishedgoodsreceipt |
| outbound_batches | inventory.add_finishedgoodsoutbound |
| outbounds | inventory.add_finishedgoodsoutbound |

### MaterialInventoryViewSet

源码：[apps/inventory/api/views.py:442](../../src/backend/apps/inventory/api/views.py#L442)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| material-inventory-list | `api/v1/^material-inventory/$` | GET → list |
| material-inventory-batch-receipts | `api/v1/^material-inventory/batch-receipts/$` | POST → batch_receipts |
| material-inventory-confirm-quality | `api/v1/^material-inventory/quality-batches/(?P<inbound_id>[^/.]+)/confirm/$` | POST → confirm_quality |
| material-inventory-eligible-lines | `api/v1/^material-inventory/eligible-lines/$` | GET → eligible_lines |
| material-inventory-eligible-purchase-orders | `api/v1/^material-inventory/eligible-purchase-orders/$` | GET → eligible_purchase_orders |
| material-inventory-inbound-details | `api/v1/^material-inventory/inbound-details/$` | GET → inbound_details |
| material-inventory-manual-material-options | `api/v1/^material-inventory/manual-material-options/$` | GET → manual_material_options |
| material-inventory-manual-receipts | `api/v1/^material-inventory/manual-receipts/$` | POST → manual_receipts |
| material-inventory-options | `api/v1/^material-inventory/options/$` | GET → options |
| material-inventory-procurement-inbound-orders | `api/v1/^material-inventory/procurement-inbound-orders/$` | GET → procurement_inbound_orders |
| material-inventory-quality-batch | `api/v1/^material-inventory/quality-batches/(?P<inbound_id>[^/.]+)/$` | GET → quality_batch |
| material-inventory-quality-batches | `api/v1/^material-inventory/quality-batches/$` | GET → quality_batches |
| material-inventory-receipts | `api/v1/^material-inventory/receipts/$` | GET → receipts；POST → receipts |
| material-inventory-receivings | `api/v1/^material-inventory/receivings/$` | POST → receivings |
| material-inventory-order-issues | `api/v1/^material-inventory/(?P<pk>[^/.]+)/order-issues/$` | GET → order_issues |
| material-inventory-order-purchases | `api/v1/^material-inventory/(?P<pk>[^/.]+)/order-purchases/$` | GET → order_purchases |
| material-inventory-summary | `api/v1/^material-inventory/(?P<pk>[^/.]+)/summary/$` | GET → summary |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | inventory.view_materialinbound |
| options | inventory.view_materialinbound |
| eligible_purchase_orders | inventory.receive_material |
| procurement_inbound_orders | inventory.receive_material 或 inventory.quality_confirm_material |
| eligible_lines | inventory.receive_material |
| manual_material_options | inventory.receive_material |
| manual_receipts | inventory.receive_material |
| receipts.GET | inventory.view_material_receipt |
| receipts.POST | inventory.receive_material |
| batch_receipts | inventory.receive_material |
| receivings | inventory.receive_material |
| quality_batches | inventory.quality_confirm_material |
| quality_batch | inventory.quality_confirm_material |
| confirm_quality | inventory.quality_confirm_material |
| inbound_details | inventory.view_material_receipt |
| summary | inventory.view_materialinbound |
| order_purchases | inventory.view_materialinbound |
| order_issues | inventory.view_materialinbound |

类内直接权限判断：

- 第 765 行：`request.user.has_perm('inventory.receive_material')`
- 第 692 行：`request.user.has_perm('procurement.view_purchaseorder')`

## 领料与加工流转 (material_issues)

7 个已注册处理类，33 条路由注册，19 个映射中的权限码。

### MaterialIssueViewSet

源码：[apps/material_issues/api/views.py:55](../../src/backend/apps/material_issues/api/views.py#L55)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| material-issue-list | `api/v1/^material-issues/$` | GET → list；POST → create |
| material-issue-eligible-products | `api/v1/^material-issues/eligible-products/$` | GET → eligible_products |
| material-issue-options | `api/v1/^material-issues/options/$` | GET → options |
| material-issue-requirements | `api/v1/^material-issues/requirements/$` | GET → requirements |
| material-issue-detail | `api/v1/^material-issues/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| material-issue-confirm-issue | `api/v1/^material-issues/(?P<pk>[^/.]+)/confirm-issue/$` | POST → confirm_issue |
| material-issue-preview-issue | `api/v1/^material-issues/(?P<pk>[^/.]+)/preview-issue/$` | POST → preview_issue |
| material-issue-return-issue | `api/v1/^material-issues/(?P<pk>[^/.]+)/return/$` | POST → return_issue |
| material-issue-submit | `api/v1/^material-issues/(?P<pk>[^/.]+)/submit/$` | POST → submit |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | material_issues.view_materialissue |
| retrieve | material_issues.view_materialissue |
| options | material_issues.view_materialissue |
| eligible_products | material_issues.view_materialissue |
| requirements | material_issues.view_materialissue |
| create | material_issues.add_materialissue |
| partial_update | material_issues.change_materialissue |
| submit | material_issues.submit_materialissue |
| return_issue | material_issues.review_materialissue |
| preview_issue | material_issues.review_materialissue |
| confirm_issue | material_issues.review_materialissue |

### MetalProcessingSourceViewSet

源码：[apps/material_issues/api/processing_views.py:28](../../src/backend/apps/material_issues/api/processing_views.py#L28)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| metal-processing-source-list | `api/v1/^metal-processing-sources/$` | GET → list |
| metal-processing-source-options | `api/v1/^metal-processing-sources/options/$` | GET → options |
| metal-processing-source-detail | `api/v1/^metal-processing-sources/(?P<pk>[0-9a-fA-F-]{36})/$` | GET → retrieve |
| metal-processing-source-close | `api/v1/^metal-processing-sources/(?P<pk>[0-9a-fA-F-]{36})/close/$` | POST → close |
| metal-processing-source-closure-preview | `api/v1/^metal-processing-sources/(?P<pk>[0-9a-fA-F-]{36})/closure-preview/$` | GET → closure_preview |
| metal-processing-source-completions | `api/v1/^metal-processing-sources/(?P<pk>[0-9a-fA-F-]{36})/completions/$` | POST → completions |
| metal-processing-source-handoffs | `api/v1/^metal-processing-sources/(?P<pk>[0-9a-fA-F-]{36})/handoffs/$` | POST → handoffs |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | material_issues.view_metalprocessingsource |
| retrieve | material_issues.view_metalprocessingsource |
| options | material_issues.view_metalprocessingsource |
| closure_preview | material_issues.view_metalprocessingsource |
| completions | material_issues.register_metalprocessingcompletion |
| close | material_issues.close_metalprocessingsource |
| handoffs | material_issues.create_metalprocessingoriginalhandoff |

### MetalProcessingOriginalHandoffViewSet

源码：[apps/material_issues/api/p4_views.py:35](../../src/backend/apps/material_issues/api/p4_views.py#L35)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| metal-processing-handoff-detail | `api/v1/^metal-processing-handoffs/(?P<pk>[0-9a-fA-F-]{36})/$` | GET → retrieve |
| metal-processing-handoff-good-returns | `api/v1/^metal-processing-handoffs/(?P<pk>[0-9a-fA-F-]{36})/good-returns/$` | POST → good_returns |
| metal-processing-handoff-returns | `api/v1/^metal-processing-handoffs/(?P<pk>[0-9a-fA-F-]{36})/returns/$` | POST → returns |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | material_issues.view_metalprocessingsource |
| returns | material_issues.register_metalprocessingunsprayedreturn |
| good_returns | outsourcing.confirm_return_outsourcingorder |

### MetalProcessingOriginalOrderViewSet

源码：[apps/material_issues/api/p4_views.py:100](../../src/backend/apps/material_issues/api/p4_views.py#L100)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| metal-processing-original-order-detail | `api/v1/^metal-processing-original-orders/(?P<pk>[0-9a-fA-F-]{36})/$` | GET → retrieve |
| metal-processing-original-order-cancel-pending | `api/v1/^metal-processing-original-orders/(?P<pk>[0-9a-fA-F-]{36})/cancel-pending/$` | POST → cancel_pending |
| metal-processing-original-order-close | `api/v1/^metal-processing-original-orders/(?P<pk>[0-9a-fA-F-]{36})/close/$` | POST → close |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | material_issues.view_metalprocessingsource |
| close | outsourcing.complete_outsourcingorder |
| cancel_pending | outsourcing.change_outsourcingorder |

### MetalProcessingUnsprayedReturnViewSet

源码：[apps/material_issues/api/p4_views.py:140](../../src/backend/apps/material_issues/api/p4_views.py#L140)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| metal-processing-unsprayed-return-detail | `api/v1/^metal-processing-unsprayed-returns/(?P<pk>[0-9a-fA-F-]{36})/$` | GET → retrieve |
| metal-processing-unsprayed-return-rework | `api/v1/^metal-processing-unsprayed-returns/(?P<pk>[0-9a-fA-F-]{36})/rework/$` | POST → rework |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | material_issues.view_metalprocessingsource |
| rework | material_issues.register_metalprocessingrework |

### MetalProcessingReworkViewSet

源码：[apps/material_issues/api/p4_views.py:173](../../src/backend/apps/material_issues/api/p4_views.py#L173)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| metal-processing-rework-detail | `api/v1/^metal-processing-reworks/(?P<pk>[0-9a-fA-F-]{36})/$` | GET → retrieve |
| metal-processing-rework-orders | `api/v1/^metal-processing-reworks/(?P<pk>[0-9a-fA-F-]{36})/orders/$` | POST → orders |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| retrieve | material_issues.view_metalprocessingsource |
| orders | material_issues.create_metalprocessingexternalorder |

### MetalProcessingExternalOrderViewSet

源码：[apps/material_issues/api/p4_views.py:203](../../src/backend/apps/material_issues/api/p4_views.py#L203)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| metal-processing-external-order-list | `api/v1/^metal-processing-external-orders/$` | GET → list |
| metal-processing-external-order-detail | `api/v1/^metal-processing-external-orders/(?P<pk>[0-9a-fA-F-]{36})/$` | GET → retrieve |
| metal-processing-external-order-allocation | `api/v1/^metal-processing-external-orders/(?P<pk>[0-9a-fA-F-]{36})/allocation/$` | POST → allocation |
| metal-processing-external-order-close | `api/v1/^metal-processing-external-orders/(?P<pk>[0-9a-fA-F-]{36})/close/$` | POST → close |
| metal-processing-external-order-handoff | `api/v1/^metal-processing-external-orders/(?P<pk>[0-9a-fA-F-]{36})/handoff/$` | POST → handoff |
| metal-processing-external-order-returns | `api/v1/^metal-processing-external-orders/(?P<pk>[0-9a-fA-F-]{36})/returns/$` | POST → returns |
| metal-processing-external-order-semi-stock | `api/v1/^metal-processing-external-orders/(?P<pk>[0-9a-fA-F-]{36})/semi-stock/$` | GET → semi_stock |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | material_issues.view_metalprocessingsource |
| retrieve | material_issues.view_metalprocessingsource |
| handoff | material_issues.confirm_metalprocessingexternalhandoff |
| allocation | material_issues.change_metalprocessingexternalorder |
| returns | material_issues.confirm_metalprocessingexternalreturn |
| close | material_issues.close_metalprocessingexternalorder |
| semi_stock | material_issues.view_metalprocessingsource |

## 委外加工 (outsourcing)

3 个已注册处理类，22 条路由注册，14 个映射中的权限码。

### OutsourcingFactoryViewSet

源码：[apps/outsourcing/api/views.py:102](../../src/backend/apps/outsourcing/api/views.py#L102)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| outsourcing-factory-list | `api/v1/^outsourcing-factories/$` | GET → list；POST → create |
| outsourcing-factory-options | `api/v1/^outsourcing-factories/options/$` | GET → options |
| outsourcing-factory-detail | `api/v1/^outsourcing-factories/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| outsourcing-factory-disable | `api/v1/^outsourcing-factories/(?P<pk>[^/.]+)/disable/$` | POST → disable |
| outsourcing-factory-related-orders | `api/v1/^outsourcing-factories/(?P<pk>[^/.]+)/related-orders/$` | GET → related_orders |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | outsourcing.view_outsourcingfactory |
| retrieve | outsourcing.view_outsourcingfactory |
| create | outsourcing.add_outsourcingfactory |
| partial_update | outsourcing.change_outsourcingfactory |
| disable | outsourcing.disable_outsourcingfactory |
| options | outsourcing.view_outsourcingfactory |
| related_orders | outsourcing.view_outsourcingfactory |

类内直接权限判断：

- 第 151 行：`request.user.has_perm('outsourcing.view_outsourcingorder')`

### OutsourcingOrderViewSet

源码：[apps/outsourcing/api/views.py:221](../../src/backend/apps/outsourcing/api/views.py#L221)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| outsourcing-order-list | `api/v1/^outsourcing-orders/$` | GET → list；POST → create |
| outsourcing-order-options | `api/v1/^outsourcing-orders/options/$` | GET → options |
| outsourcing-order-source-plans | `api/v1/^outsourcing-orders/source-plans/$` | GET → source_plans |
| outsourcing-order-source-product-bom | `api/v1/^outsourcing-orders/source-products/(?P<schedule_product_id>[^/.]+)/bom/$` | GET → source_product_bom |
| outsourcing-order-detail | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/$` | GET → retrieve；DELETE → destroy |
| outsourcing-order-cancel | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/cancel/$` | POST → cancel |
| outsourcing-order-complete | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/complete/$` | POST → complete |
| outsourcing-order-confirm-dispatch | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/confirm-dispatch/$` | POST → confirm_dispatch |
| outsourcing-order-confirm-raw-return | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/confirm-raw-return/$` | POST → confirm_raw_return |
| outsourcing-order-confirm-reconciliation | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/confirm-reconciliation/$` | POST → confirm_reconciliation |
| outsourcing-order-confirm-return | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/confirm-return/$` | POST → confirm_return |
| outsourcing-order-dispatch-context | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/dispatch-context/$` | GET → dispatch_context |
| outsourcing-order-product-file | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/product-files/(?P<file_id>[^/.]+)/$` | GET → product_file |
| outsourcing-order-reconciliation | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/reconciliation/$` | GET → reconciliation |
| outsourcing-order-revoke-dispatched | `api/v1/^outsourcing-orders/(?P<pk>[^/.]+)/revoke-dispatched/$` | POST → revoke_dispatched |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | outsourcing.view_outsourcingorder |
| retrieve | outsourcing.view_outsourcingorder |
| create | outsourcing.add_outsourcingorder |
| destroy | outsourcing.delete_outsourcingorder |
| cancel | outsourcing.cancel_outsourcingorder |
| revoke_dispatched | outsourcing.cancel_outsourcingorder |
| confirm_dispatch | outsourcing.confirm_dispatch_outsourcingorder |
| dispatch_context | outsourcing.confirm_dispatch_outsourcingorder |
| confirm_return | outsourcing.confirm_return_outsourcingorder |
| reconciliation | outsourcing.view_outsourcingorder |
| confirm_raw_return | outsourcing.return_raw_outsourcingorder |
| confirm_reconciliation | outsourcing.reconcile_outsourcingorder |
| complete | outsourcing.complete_outsourcingorder |
| product_file | outsourcing.view_outsourcingorder |
| options | outsourcing.view_outsourcingorder |
| source_plans | outsourcing.view_outsourcingorder |
| source_product_bom | outsourcing.view_outsourcingorder |

类内直接权限判断：

- 第 361 行：`request.user.has_perm('outsourcing.return_raw_outsourcingorder')`

### UnifiedOutsourcingOrderViewSet

源码：[apps/outsourcing/api/unified_views.py:20](../../src/backend/apps/outsourcing/api/unified_views.py#L20)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| unified-outsourcing-order-list | `api/v1/^unified-outsourcing-orders/$` | GET → list |
| unified-outsourcing-order-options | `api/v1/^unified-outsourcing-orders/options/$` | GET → options |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | outsourcing.view_outsourcingorder 或 material_issues.view_metalprocessingsource |
| options | outsourcing.view_outsourcingorder 或 material_issues.view_metalprocessingsource |

类内直接权限判断：

- 第 37 行：`request.user.has_perm(VIEW_PERMISSIONS[0])`

## 车间基础资料 (workshop_config)

4 个已注册处理类，22 条路由注册，9 个映射中的权限码。

### WorkshopViewSet

源码：[apps/workshop_config/api/views.py:101](../../src/backend/apps/workshop_config/api/views.py#L101)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| workshop-config-workshop-list | `api/v1/^workshop-config/workshops/$` | GET → list |
| workshop-config-workshop-detail | `api/v1/^workshop-config/workshops/(?P<pk>[^/.]+)/$` | GET → retrieve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | 空值：结合权限类判断 |
| retrieve | 空值：结合权限类判断 |

### WorkshopEmployeeViewSet

源码：[apps/workshop_config/api/views.py:132](../../src/backend/apps/workshop_config/api/views.py#L132)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| workshop-config-employee-list | `api/v1/^workshop-config/employees/$` | GET → list；POST → create |
| workshop-config-employee-summary | `api/v1/^workshop-config/employees/summary/$` | GET → summary |
| workshop-config-employee-detail | `api/v1/^workshop-config/employees/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workshop_config.view_workshopemployee |
| retrieve | workshop_config.view_workshopemployee |
| summary | workshop_config.view_workshopemployee |
| create | workshop_config.add_workshopemployee |
| update | workshop_config.change_workshopemployee |
| partial_update | workshop_config.change_workshopemployee |

### CraftViewSet

源码：[apps/workshop_config/api/views.py:181](../../src/backend/apps/workshop_config/api/views.py#L181)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| workshop-config-craft-list | `api/v1/^workshop-config/crafts/$` | GET → list；POST → create |
| workshop-config-craft-summary | `api/v1/^workshop-config/crafts/summary/$` | GET → summary |
| workshop-config-craft-detail | `api/v1/^workshop-config/crafts/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workshop_config.view_craft |
| retrieve | workshop_config.view_craft |
| summary | workshop_config.view_craft |
| create | workshop_config.add_craft |
| update | workshop_config.change_craft |
| partial_update | workshop_config.change_craft |

### OperationViewSet

源码：[apps/workshop_config/api/views.py:224](../../src/backend/apps/workshop_config/api/views.py#L224)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| workshop-config-operation-list | `api/v1/^workshop-config/operations/$` | GET → list；POST → create |
| workshop-config-operation-summary | `api/v1/^workshop-config/operations/summary/$` | GET → summary |
| workshop-config-operation-detail | `api/v1/^workshop-config/operations/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workshop_config.view_operation |
| retrieve | workshop_config.view_operation |
| summary | workshop_config.view_operation |
| create | workshop_config.add_operation |
| update | workshop_config.change_operation |
| partial_update | workshop_config.change_operation |

## 工价与报工 (workshop_reporting)

6 个已注册处理类，14 条路由注册，8 个映射中的权限码。

### ReportingContextView

源码：[apps/workshop_reporting/api/views.py:60](../../src/backend/apps/workshop_reporting/api/views.py#L60)。

权限类：HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| workshop-reporting-context | `api/v1/workshop-reporting/context/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

类内直接权限判断：

- 第 72 行：`request.user.has_perm(required_permission)`

### PlanWageStatusView

源码：[apps/workshop_reporting/api/views.py:140](../../src/backend/apps/workshop_reporting/api/views.py#L140)。

权限类：HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| workshop-reporting-plan-wage-statuses | `api/v1/workshop-reporting/plan-wage-statuses/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

类内直接权限判断：

- 第 147 行：`request.user.has_perm('workshop_reporting.view_wagescheme')`
- 第 148 行：`request.user.has_perm('workshop_reporting.view_workreport')`
- 第 205 行：`request.user.has_perm('workshop_reporting.add_workreport')`
- 第 206 行：`request.user.has_perm('workshop_reporting.view_workreport')`

### WorkReportDayListView

源码：[apps/workshop_reporting/api/views.py:424](../../src/backend/apps/workshop_reporting/api/views.py#L424)。

权限类：HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| work-report-day-list | `api/v1/workshop-reporting/work-report-days/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

类内直接权限判断：

- 第 429 行：`request.user.has_perm('workshop_reporting.view_workreport')`

### WorkReportDayDetailView

源码：[apps/workshop_reporting/api/views.py:445](../../src/backend/apps/workshop_reporting/api/views.py#L445)。

权限类：HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| work-report-day-detail | `api/v1/workshop-reporting/work-report-days/<str:production_date>/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

类内直接权限判断：

- 第 450 行：`request.user.has_perm('workshop_reporting.view_workreport')`

### WageSchemeViewSet

源码：[apps/workshop_reporting/api/views.py:223](../../src/backend/apps/workshop_reporting/api/views.py#L223)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| wage-scheme-list | `api/v1/workshop-reporting/^wage-schemes/$` | GET → list；POST → create |
| wage-scheme-history | `api/v1/workshop-reporting/^wage-schemes/history-schemes/$` | GET → history |
| wage-scheme-detail | `api/v1/workshop-reporting/^wage-schemes/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |
| wage-scheme-approve | `api/v1/workshop-reporting/^wage-schemes/(?P<pk>[^/.]+)/approve/$` | POST → approve |
| wage-scheme-change | `api/v1/workshop-reporting/^wage-schemes/(?P<pk>[^/.]+)/change/$` | POST → change |
| wage-scheme-return-scheme | `api/v1/workshop-reporting/^wage-schemes/(?P<pk>[^/.]+)/return/$` | POST → return_scheme |
| wage-scheme-submit | `api/v1/workshop-reporting/^wage-schemes/(?P<pk>[^/.]+)/submit/$` | POST → submit |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | workshop_reporting.view_wagescheme |
| retrieve | workshop_reporting.view_wagescheme |
| history | workshop_reporting.view_wagescheme |
| create | workshop_reporting.add_wagescheme |
| partial_update | workshop_reporting.change_wagescheme |
| submit | workshop_reporting.submit_wagescheme |
| change | workshop_reporting.change_wagescheme |
| approve | workshop_reporting.approve_wagescheme |
| return_scheme | workshop_reporting.approve_wagescheme |

### WorkReportViewSet

源码：[apps/workshop_reporting/api/views.py:350](../../src/backend/apps/workshop_reporting/api/views.py#L350)。

权限类：HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| work-report-list | `api/v1/workshop-reporting/^work-reports/$` | POST → create |
| work-report-price-context | `api/v1/workshop-reporting/^work-reports/price-context/$` | GET → price_context |
| work-report-detail | `api/v1/workshop-reporting/^work-reports/(?P<pk>[^/.]+)/$` | GET → retrieve；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| create | workshop_reporting.add_workreport |
| retrieve | workshop_reporting.view_workreport |
| partial_update | workshop_reporting.change_workreport |
| price_context | workshop_reporting.view_workreport |

## 系统字典与基础资料 (reference_data)

37 个已注册处理类，151 条路由注册，0 个映射中的权限码。

### PublishedOptionsBatchView

源码：[apps/reference_data/api/views.py:961](../../src/backend/apps/reference_data/api/views.py#L961)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| published-options-batch | `api/v1/reference-data/options-batch/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### PublishedConfigVersionView

源码：[apps/reference_data/api/views.py:952](../../src/backend/apps/reference_data/api/views.py#L952)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| published-config-version | `api/v1/reference-data/published-version/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ReferenceDataSummaryView

源码：[apps/reference_data/api/views.py:1018](../../src/backend/apps/reference_data/api/views.py#L1018)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| reference-data-summary | `api/v1/reference-data/summary/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### MasterDataSummaryView

源码：[apps/reference_data/api/views.py:1042](../../src/backend/apps/reference_data/api/views.py#L1042)。

权限类：IsAuthenticated、HasActiveEmployee、MasterDataSummaryPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| master-data-summary | `api/v1/reference-data/master-data-summary/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ProductionDataSummaryView

源码：[apps/reference_data/api/views.py:1070](../../src/backend/apps/reference_data/api/views.py#L1070)。

权限类：IsAuthenticated、HasActiveEmployee、ProductionDataSummaryPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| production-data-summary | `api/v1/reference-data/production-data-summary/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### PublishedOptionsView

源码：[apps/reference_data/api/views.py:980](../../src/backend/apps/reference_data/api/views.py#L980)。

权限类：IsAuthenticated、HasActiveEmployee。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| reference-data-options | `api/v1/reference-data/options/<str:type_code>/` | 普通 APIView，见源码方法 |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### DictionaryTypeViewSet

源码：[apps/reference_data/api/views.py:419](../../src/backend/apps/reference_data/api/views.py#L419)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| dictionary-type-list | `api/v1/^reference-data/dictionary-types/$` | GET → list；POST → create |
| dictionary-type-detail | `api/v1/^reference-data/dictionary-types/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| dictionary-type-activate | `api/v1/^reference-data/dictionary-types/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| dictionary-type-archive | `api/v1/^reference-data/dictionary-types/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| dictionary-type-deactivate | `api/v1/^reference-data/dictionary-types/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ReferenceDictionaryViewSet

源码：[apps/reference_data/api/views.py:428](../../src/backend/apps/reference_data/api/views.py#L428)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| dictionary-item-list | `api/v1/^reference-data/dictionary-items/$` | GET → list；POST → create |
| dictionary-item-detail | `api/v1/^reference-data/dictionary-items/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| dictionary-item-activate | `api/v1/^reference-data/dictionary-items/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| dictionary-item-archive | `api/v1/^reference-data/dictionary-items/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| dictionary-item-deactivate | `api/v1/^reference-data/dictionary-items/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ConfigReleaseViewSet

源码：[apps/reference_data/api/views.py:865](../../src/backend/apps/reference_data/api/views.py#L865)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| config-release-list | `api/v1/^reference-data/config-releases/$` | GET → list；POST → create |
| config-release-detail | `api/v1/^reference-data/config-releases/(?P<pk>[^/.]+)/$` | GET → retrieve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### SystemParameterViewSet

源码：[apps/reference_data/api/views.py:897](../../src/backend/apps/reference_data/api/views.py#L897)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| system-parameter-list | `api/v1/^reference-data/system-parameters/$` | GET → list |
| system-parameter-detail | `api/v1/^reference-data/system-parameters/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### CountryViewSet

源码：[apps/reference_data/api/views.py:440](../../src/backend/apps/reference_data/api/views.py#L440)。

权限类：IsAuthenticated、HasActiveEmployee、StandardMasterDataPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| country-list | `api/v1/^reference-data/countries/$` | GET → list；POST → create |
| country-detail | `api/v1/^reference-data/countries/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| country-activate | `api/v1/^reference-data/countries/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| country-archive | `api/v1/^reference-data/countries/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| country-deactivate | `api/v1/^reference-data/countries/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### CurrencyViewSet

源码：[apps/reference_data/api/views.py:447](../../src/backend/apps/reference_data/api/views.py#L447)。

权限类：IsAuthenticated、HasActiveEmployee、StandardMasterDataPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| currency-list | `api/v1/^reference-data/currencies/$` | GET → list；POST → create |
| currency-detail | `api/v1/^reference-data/currencies/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| currency-activate | `api/v1/^reference-data/currencies/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| currency-archive | `api/v1/^reference-data/currencies/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| currency-deactivate | `api/v1/^reference-data/currencies/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ExchangeRateViewSet

源码：[apps/reference_data/api/views.py:760](../../src/backend/apps/reference_data/api/views.py#L760)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| exchange-rate-list | `api/v1/^reference-data/exchange-rates/$` | GET → list；POST → create |
| exchange-rate-detail | `api/v1/^reference-data/exchange-rates/(?P<pk>[^/.]+)/$` | GET → retrieve |
| exchange-rate-correct | `api/v1/^reference-data/exchange-rates/(?P<pk>[^/.]+)/correct/$` | POST → correct |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### UnitViewSet

源码：[apps/reference_data/api/views.py:454](../../src/backend/apps/reference_data/api/views.py#L454)。

权限类：IsAuthenticated、HasActiveEmployee、StandardMasterDataPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| unit-list | `api/v1/^reference-data/units/$` | GET → list；POST → create |
| unit-detail | `api/v1/^reference-data/units/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| unit-activate | `api/v1/^reference-data/units/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| unit-archive | `api/v1/^reference-data/units/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| unit-deactivate | `api/v1/^reference-data/units/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### IncotermViewSet

源码：[apps/reference_data/api/views.py:724](../../src/backend/apps/reference_data/api/views.py#L724)。

权限类：IsAuthenticated、HasActiveEmployee、StandardMasterDataPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| incoterm-list | `api/v1/^reference-data/incoterms/$` | GET → list；POST → create |
| incoterm-detail | `api/v1/^reference-data/incoterms/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| incoterm-activate | `api/v1/^reference-data/incoterms/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| incoterm-archive | `api/v1/^reference-data/incoterms/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| incoterm-deactivate | `api/v1/^reference-data/incoterms/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### PaymentMethodViewSet

源码：[apps/reference_data/api/views.py:731](../../src/backend/apps/reference_data/api/views.py#L731)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| payment-method-list | `api/v1/^reference-data/payment-methods/$` | GET → list；POST → create |
| payment-method-detail | `api/v1/^reference-data/payment-methods/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| payment-method-activate | `api/v1/^reference-data/payment-methods/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| payment-method-archive | `api/v1/^reference-data/payment-methods/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| payment-method-deactivate | `api/v1/^reference-data/payment-methods/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TransportMethodViewSet

源码：[apps/reference_data/api/views.py:737](../../src/backend/apps/reference_data/api/views.py#L737)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| transport-method-list | `api/v1/^reference-data/transport-methods/$` | GET → list；POST → create |
| transport-method-detail | `api/v1/^reference-data/transport-methods/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| transport-method-activate | `api/v1/^reference-data/transport-methods/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| transport-method-archive | `api/v1/^reference-data/transport-methods/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| transport-method-deactivate | `api/v1/^reference-data/transport-methods/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### PortViewSet

源码：[apps/reference_data/api/views.py:743](../../src/backend/apps/reference_data/api/views.py#L743)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| port-list | `api/v1/^reference-data/ports/$` | GET → list；POST → create |
| port-detail | `api/v1/^reference-data/ports/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| port-activate | `api/v1/^reference-data/ports/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| port-archive | `api/v1/^reference-data/ports/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| port-deactivate | `api/v1/^reference-data/ports/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### CourierViewSet

源码：[apps/reference_data/api/views.py:754](../../src/backend/apps/reference_data/api/views.py#L754)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| courier-list | `api/v1/^reference-data/couriers/$` | GET → list；POST → create |
| courier-detail | `api/v1/^reference-data/couriers/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| courier-activate | `api/v1/^reference-data/couriers/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| courier-archive | `api/v1/^reference-data/couriers/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| courier-deactivate | `api/v1/^reference-data/couriers/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### NumberRuleViewSet

源码：[apps/reference_data/api/views.py:412](../../src/backend/apps/reference_data/api/views.py#L412)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| number-rule-list | `api/v1/^reference-data/number-rules/$` | GET → list |
| number-rule-detail | `api/v1/^reference-data/number-rules/(?P<pk>[^/.]+)/$` | GET → retrieve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ProductCategoryViewSet

源码：[apps/reference_data/api/views.py:461](../../src/backend/apps/reference_data/api/views.py#L461)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| product-category-list | `api/v1/^reference-data/product-categories/$` | GET → list；POST → create |
| product-category-detail | `api/v1/^reference-data/product-categories/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| product-category-activate | `api/v1/^reference-data/product-categories/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| product-category-archive | `api/v1/^reference-data/product-categories/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| product-category-deactivate | `api/v1/^reference-data/product-categories/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ProductionUnitViewSet

源码：[apps/reference_data/api/views.py:494](../../src/backend/apps/reference_data/api/views.py#L494)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| production-unit-list | `api/v1/^reference-data/production-units/$` | GET → list；POST → create |
| production-unit-detail | `api/v1/^reference-data/production-units/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| production-unit-activate | `api/v1/^reference-data/production-units/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| production-unit-archive | `api/v1/^reference-data/production-units/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| production-unit-deactivate | `api/v1/^reference-data/production-units/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ProductColorViewSet

源码：[apps/reference_data/api/views.py:501](../../src/backend/apps/reference_data/api/views.py#L501)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| product-color-list | `api/v1/^reference-data/product-colors/$` | GET → list；POST → create |
| product-color-detail | `api/v1/^reference-data/product-colors/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| product-color-activate | `api/v1/^reference-data/product-colors/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| product-color-archive | `api/v1/^reference-data/product-colors/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| product-color-deactivate | `api/v1/^reference-data/product-colors/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |
| product-color-image | `api/v1/^reference-data/product-colors/(?P<pk>[^/.]+)/image/$` | GET → image；POST → image；DELETE → image |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### ProductItemViewSet

源码：[apps/reference_data/api/views.py:579](../../src/backend/apps/reference_data/api/views.py#L579)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| product-item-list | `api/v1/^reference-data/product-items/$` | GET → list；POST → create |
| product-item-detail | `api/v1/^reference-data/product-items/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| product-item-activate | `api/v1/^reference-data/product-items/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| product-item-archive | `api/v1/^reference-data/product-items/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| product-item-deactivate | `api/v1/^reference-data/product-items/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### FabricMaterialViewSet

源码：[apps/reference_data/api/views.py:597](../../src/backend/apps/reference_data/api/views.py#L597)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| fabric-material-list | `api/v1/^reference-data/fabric-materials/$` | GET → list；POST → create |
| fabric-material-detail | `api/v1/^reference-data/fabric-materials/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| fabric-material-activate | `api/v1/^reference-data/fabric-materials/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| fabric-material-archive | `api/v1/^reference-data/fabric-materials/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| fabric-material-deactivate | `api/v1/^reference-data/fabric-materials/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### FabricSpecificationViewSet

源码：[apps/reference_data/api/views.py:606](../../src/backend/apps/reference_data/api/views.py#L606)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| fabric-specification-list | `api/v1/^reference-data/fabric-specifications/$` | GET → list；POST → create |
| fabric-specification-detail | `api/v1/^reference-data/fabric-specifications/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| fabric-specification-activate | `api/v1/^reference-data/fabric-specifications/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| fabric-specification-archive | `api/v1/^reference-data/fabric-specifications/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| fabric-specification-deactivate | `api/v1/^reference-data/fabric-specifications/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### FabricWidthViewSet

源码：[apps/reference_data/api/views.py:613](../../src/backend/apps/reference_data/api/views.py#L613)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| fabric-width-list | `api/v1/^reference-data/fabric-widths/$` | GET → list；POST → create |
| fabric-width-detail | `api/v1/^reference-data/fabric-widths/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| fabric-width-activate | `api/v1/^reference-data/fabric-widths/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| fabric-width-archive | `api/v1/^reference-data/fabric-widths/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| fabric-width-deactivate | `api/v1/^reference-data/fabric-widths/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TubeProductNameViewSet

源码：[apps/reference_data/api/views.py:620](../../src/backend/apps/reference_data/api/views.py#L620)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| tube-product-name-list | `api/v1/^reference-data/tube-product-names/$` | GET → list；POST → create |
| tube-product-name-detail | `api/v1/^reference-data/tube-product-names/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| tube-product-name-activate | `api/v1/^reference-data/tube-product-names/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| tube-product-name-archive | `api/v1/^reference-data/tube-product-names/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| tube-product-name-deactivate | `api/v1/^reference-data/tube-product-names/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TubeThicknessViewSet

源码：[apps/reference_data/api/views.py:627](../../src/backend/apps/reference_data/api/views.py#L627)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| tube-thickness-list | `api/v1/^reference-data/tube-thicknesses/$` | GET → list；POST → create |
| tube-thickness-detail | `api/v1/^reference-data/tube-thicknesses/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| tube-thickness-activate | `api/v1/^reference-data/tube-thicknesses/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| tube-thickness-archive | `api/v1/^reference-data/tube-thicknesses/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| tube-thickness-deactivate | `api/v1/^reference-data/tube-thicknesses/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TubeDiameterViewSet

源码：[apps/reference_data/api/views.py:634](../../src/backend/apps/reference_data/api/views.py#L634)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| tube-diameter-list | `api/v1/^reference-data/tube-diameters/$` | GET → list；POST → create |
| tube-diameter-detail | `api/v1/^reference-data/tube-diameters/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| tube-diameter-activate | `api/v1/^reference-data/tube-diameters/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| tube-diameter-archive | `api/v1/^reference-data/tube-diameters/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| tube-diameter-deactivate | `api/v1/^reference-data/tube-diameters/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TubeMaterialViewSet

源码：[apps/reference_data/api/views.py:641](../../src/backend/apps/reference_data/api/views.py#L641)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| tube-material-list | `api/v1/^reference-data/tube-materials/$` | GET → list；POST → create |
| tube-material-detail | `api/v1/^reference-data/tube-materials/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| tube-material-activate | `api/v1/^reference-data/tube-materials/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| tube-material-archive | `api/v1/^reference-data/tube-materials/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| tube-material-deactivate | `api/v1/^reference-data/tube-materials/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TubeShapeViewSet

源码：[apps/reference_data/api/views.py:648](../../src/backend/apps/reference_data/api/views.py#L648)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| tube-shape-list | `api/v1/^reference-data/tube-shapes/$` | GET → list；POST → create |
| tube-shape-detail | `api/v1/^reference-data/tube-shapes/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| tube-shape-activate | `api/v1/^reference-data/tube-shapes/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| tube-shape-archive | `api/v1/^reference-data/tube-shapes/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| tube-shape-deactivate | `api/v1/^reference-data/tube-shapes/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### TubeCoatingColorViewSet

源码：[apps/reference_data/api/views.py:655](../../src/backend/apps/reference_data/api/views.py#L655)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| tube-coating-color-list | `api/v1/^reference-data/tube-coating-colors/$` | GET → list；POST → create |
| tube-coating-color-detail | `api/v1/^reference-data/tube-coating-colors/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| tube-coating-color-activate | `api/v1/^reference-data/tube-coating-colors/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| tube-coating-color-archive | `api/v1/^reference-data/tube-coating-colors/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| tube-coating-color-deactivate | `api/v1/^reference-data/tube-coating-colors/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### AccessoryProductNameViewSet

源码：[apps/reference_data/api/views.py:662](../../src/backend/apps/reference_data/api/views.py#L662)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| accessory-product-name-list | `api/v1/^reference-data/accessory-product-names/$` | GET → list；POST → create |
| accessory-product-name-detail | `api/v1/^reference-data/accessory-product-names/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| accessory-product-name-activate | `api/v1/^reference-data/accessory-product-names/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| accessory-product-name-archive | `api/v1/^reference-data/accessory-product-names/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| accessory-product-name-deactivate | `api/v1/^reference-data/accessory-product-names/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### AccessorySpecificationViewSet

源码：[apps/reference_data/api/views.py:679](../../src/backend/apps/reference_data/api/views.py#L679)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| accessory-specification-list | `api/v1/^reference-data/accessory-specifications/$` | GET → list；POST → create |
| accessory-specification-detail | `api/v1/^reference-data/accessory-specifications/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| accessory-specification-activate | `api/v1/^reference-data/accessory-specifications/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| accessory-specification-archive | `api/v1/^reference-data/accessory-specifications/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| accessory-specification-deactivate | `api/v1/^reference-data/accessory-specifications/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### AccessoryColorViewSet

源码：[apps/reference_data/api/views.py:697](../../src/backend/apps/reference_data/api/views.py#L697)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| accessory-color-list | `api/v1/^reference-data/accessory-colors/$` | GET → list；POST → create |
| accessory-color-detail | `api/v1/^reference-data/accessory-colors/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| accessory-color-activate | `api/v1/^reference-data/accessory-colors/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| accessory-color-archive | `api/v1/^reference-data/accessory-colors/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| accessory-color-deactivate | `api/v1/^reference-data/accessory-colors/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

### AccessoryMaterialViewSet

源码：[apps/reference_data/api/views.py:715](../../src/backend/apps/reference_data/api/views.py#L715)。

权限类：IsAuthenticated、HasActiveEmployee、ReferenceDataManagementPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| accessory-material-list | `api/v1/^reference-data/accessory-materials/$` | GET → list；POST → create |
| accessory-material-detail | `api/v1/^reference-data/accessory-materials/(?P<pk>[^/.]+)/$` | GET → retrieve；PUT → update；PATCH → partial_update |
| accessory-material-activate | `api/v1/^reference-data/accessory-materials/(?P<pk>[^/.]+)/activate/$` | POST → activate |
| accessory-material-archive | `api/v1/^reference-data/accessory-materials/(?P<pk>[^/.]+)/archive/$` | POST → archive |
| accessory-material-deactivate | `api/v1/^reference-data/accessory-materials/(?P<pk>[^/.]+)/deactivate/$` | POST → deactivate |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

## 个人保存视图 (preferences)

1 个已注册处理类，4 条路由注册，3 个映射中的权限码。

### SavedViewViewSet

源码：[apps/preferences/api/views.py:16](../../src/backend/apps/preferences/api/views.py#L16)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| saved-view-list | `api/v1/^saved-views/$` | GET → list；POST → create |
| saved-view-detail | `api/v1/^saved-views/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PATCH → partial_update |
| saved-view-archive | `api/v1/^saved-views/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/archive/$` | POST → archive |
| saved-view-set-default | `api/v1/^saved-views/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-default/$` | POST → set_default |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | preferences.view_savedview |
| retrieve | preferences.view_savedview |
| create | preferences.add_savedview |
| partial_update | preferences.change_savedview |
| set_default | preferences.change_savedview |
| archive | preferences.change_savedview |

## 个人邮箱 (email_accounts)

1 个已注册处理类，4 条路由注册，0 个映射中的权限码。

### EmailAccountViewSet

源码：[apps/email_accounts/api/views.py:30](../../src/backend/apps/email_accounts/api/views.py#L30)。

权限类：IsAuthenticated、HasActiveEmployee、OwnEmailAccountPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| email-account-list | `api/v1/^email-accounts/$` | GET → list；POST → create |
| email-account-detail | `api/v1/^email-accounts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve；PUT → update；PATCH → partial_update；DELETE → destroy |
| email-account-set-default | `api/v1/^email-accounts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/set-default/$` | POST → set_default |
| email-account-test-send | `api/v1/^email-accounts/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/test-send/$` | POST → test_send |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| — | 无 action_permission_map，检查直接鉴权/自定义权限类 |

## 联系人导入 (imports)

1 个已注册处理类，4 条路由注册，1 个映射中的权限码。

### ContactImportViewSet

源码：[apps/imports/api/views.py:19](../../src/backend/apps/imports/api/views.py#L19)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| contact-import-list | `api/v1/^contact-imports/$` | POST → create |
| contact-import-template | `api/v1/^contact-imports/template/$` | GET → template |
| contact-import-detail | `api/v1/^contact-imports/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |
| contact-import-records | `api/v1/^contact-imports/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/records/$` | GET → records |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| create | customers.import_customercontact |
| retrieve | customers.import_customercontact |
| template | customers.import_customercontact |
| records | customers.import_customercontact |

## 审计 (audit)

2 个已注册处理类，3 条路由注册，2 个映射中的权限码。

### CustomerAuditLogNestedViewSet

源码：[apps/audit/api/views.py:58](../../src/backend/apps/audit/api/views.py#L58)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| customer-audit-log-list | `api/v1/customers/<uuid:customer_pk>/audit-logs/` | GET → list |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | audit.view_auditlog |

### AuditLogViewSet

源码：[apps/audit/api/views.py:41](../../src/backend/apps/audit/api/views.py#L41)。

权限类：IsAuthenticated、HasActiveEmployee、BusinessActionPermission。

| 路由名 | 路径 | HTTP → 操作 |
| --- | --- | --- |
| audit-log-list | `api/v1/^audit-logs/$` | GET → list |
| audit-log-detail | `api/v1/^audit-logs/(?P<pk>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$` | GET → retrieve |

| 操作键 | 当前权限码（列表为任一满足） |
| --- | --- |
| list | audit.view_all_auditlog |
| retrieve | audit.view_all_auditlog |

## 框架与接口文档辅助入口

这些入口不是业务模块权限，单列保证注册清单完整。AllowAny 文档入口的开放策略在员工启用前核对，不将其计为业务写权限。

| 路径 | 处理类 | 权限类 |
| --- | --- | --- |
| api/schema/ | drf_spectacular.views.SpectacularAPIView | AllowAny |
| api/v1/ | rest_framework.routers.APIRootView | IsAuthenticated、HasActiveEmployee |
| api/v1/<drf_format_suffix:format> | rest_framework.routers.APIRootView | IsAuthenticated、HasActiveEmployee |
| api/v1/ | rest_framework.routers.APIRootView | IsAuthenticated、HasActiveEmployee |
| api/v1/<drf_format_suffix:format> | rest_framework.routers.APIRootView | IsAuthenticated、HasActiveEmployee |
| api/v1/ | rest_framework.routers.APIRootView | IsAuthenticated、HasActiveEmployee |
| api/v1/<drf_format_suffix:format> | rest_framework.routers.APIRootView | IsAuthenticated、HasActiveEmployee |
| api/docs/ | drf_spectacular.views.SpectacularSwaggerView | AllowAny |

## 前端页面路由

全局守卫目前主要验证登录；菜单过滤和页面内判断不等于完整后端权限覆盖。

| 页面名 | 路径 | 标题 | 源码行 |
| --- | --- | --- | --- |
| login | /login |  | 101 |
| home | / | 业务工作台 | 106 |
| customers | /customers | 客户管理 | 119 |
| customer-create | /customers/new | 客户管理 | 132 |
| customer-duplicates | /customers/duplicates | 重复客户中心 | 146 |
| customer-inquiries | /customers/:customerId/inquiries | 客户管理 | 159 |
| customer-quotations | /customers/:customerId/quotations | 客户管理 | 168 |
| customer-samples | /customers/:customerId/samples | 客户管理 | 177 |
| customer-orders | /customers/:customerId/orders | 客户管理 | 186 |
| customer-detail | /customers/:customerId | 客户管理 | 195 |
| customer-edit | /customers/:customerId/edit | 客户管理 | 204 |
| contacts | /contacts | 客户管理 | 213 |
| customer-contacts | /customers/:customerId/contacts | 客户管理 | 226 |
| customer-timeline | /customers/:customerId/timeline | 客户时间线 | 241 |
| customer-tasks | /customers/:customerId/tasks | 客户任务 | 250 |
| customer-complaints | /customers/:customerId/complaints | 客户客诉 | 260 |
| customer-transfer | /customers/:customerId/transfer | 客户转移 | 270 |
| complaints | /complaints | 客诉管理 | 279 |
| complaint-detail | /complaints/:complaintId | 客诉详情 | 291 |
| inquiries | /inquiries | 询盘管理 | 303 |
| inquiry-create | /inquiries/new | 新建询盘 | 317 |
| inquiry-edit | /inquiries/:inquiryId/edit | 编辑询盘 | 331 |
| inquiry-detail | /inquiries/:inquiryId | 询盘详情 | 345 |
| quotation-price-history | /quotations/price-history | 历史价格趋势 | 360 |
| quotation-versions | /quotations/:quotationId/versions | 报价版本树与差异 | 374 |
| quotation-preview | /quotations/:quotationId/preview | 报价管理 | 388 |
| quotation-packaging | /quotations/:quotationId/packaging/:lineId | 报价管理 | 402 |
| boms | /boms | 生产管理 / BOM 管理 | 416 |
| sales-orders | /sales-orders | 销售管理 / 销售订单 | 430 |
| sales-order-create | /sales-orders/new | 销售管理 / 销售订单 | 444 |
| sales-order-edit | /sales-orders/:orderId/edit | 销售管理 / 销售订单 | 453 |
| sales-order-detail | /sales-orders/:orderId | 销售管理 / 销售订单 | 462 |
| bom-create | /boms/new | 生产管理 / BOM管理 / 新建BOM | 471 |
| bom-preview | /boms/:bomId/preview | 生产管理 / BOM 管理 | 485 |
| bom-edit | /boms/:bomId/edit | 生产管理 / BOM 管理 | 498 |
| production-tasks | /production-tasks | 生产管理 / 生产订单 | 512 |
| production-task-create | /production-tasks/new | 生产管理 / 生产订单 | 526 |
| production-task-edit | /production-tasks/:taskId/edit | 生产管理 / 生产订单 | 540 |
| production-task-detail | /production-tasks/:taskId | 生产管理 / 生产订单 | 554 |
| samples | /samples | 样品管理 / 打样申请 | 568 |
| sample-request-new | /samples/request/new |  | 583 |
| sample-new | /samples/new | 样品跟进 / 创建打样申请 | 588 |
| sample-inventory | /samples/inventory | 样品管理 | 602 |
| sample-inventory-receipt-detail | /samples/inventory/receipts/:receiptId | 样品管理 | 614 |
| sample-outbound | /samples/outbound | 样品管理 | 626 |
| sample-outbound-detail | /samples/outbound/documents/:outboundId | 样品管理 | 638 |
| sample-loans | /samples/loans | 样品管理 | 650 |
| sample-loan-detail | /samples/loans/documents/:loanId | 样品管理 | 662 |
| sample-warehouse-review | /samples/:sampleId/warehouse-review | 样品跟进 / 仓库核对材料 | 674 |
| sample-materials | /samples/:sampleId/materials | 样品跟进 / 填写材料需求 | 685 |
| sample-director-review | /samples/:sampleId/director-review | 样品跟进 / 厂长确认打样申请 | 696 |
| sample-edit | /samples/:sampleId/edit | 样品管理 | 707 |
| sample-detail | /samples/:sampleId | 样品流程 | 721 |
| sample-fees | /samples/:sampleId/fees | 样品费用处理 | 735 |
| sample-fulfillment | /samples/:sampleId/fulfillment | 样品管理 | 747 |
| quotations | /quotations | 报价管理 | 759 |
| quotation-edit | /quotations/:quotationId/edit | 报价管理 | 773 |
| tasks | /tasks | 任务中心 | 787 |
| task-detail | /tasks/:taskId | 任务详情 | 800 |
| products | /products | 产品管理 | 813 |
| raw-materials | /raw-materials | 产品管理 | 826 |
| workshop-configuration | /workshop/configuration | 生产车间 / 生产配置 | 839 |
| workshop-scheduling | /workshop/scheduling | 生产车间 / 计划排产 | 853 |
| workshop-metalworking-plan | /workshop/plans/metalworking | 生产车间 / 内部计划 | 868 |
| workshop-cutting-plan | /workshop/plans/cutting | 生产车间 / 内部计划 | 883 |
| workshop-sewing-plan | /workshop/plans/sewing | 生产车间 / 内部计划 | 898 |
| workshop-assembly-plan | /workshop/plans/assembly | 生产车间 / 内部计划 | 913 |
| wage-schemes | /workshop/wage-schemes | 生产车间 / 工价方案 | 928 |
| wage-scheme-new | /workshop/wage-schemes/new | 生产车间 / 工价方案 / 新增 | 934 |
| wage-scheme-change | /workshop/wage-schemes/:schemeId/change | 生产车间 / 工价方案 / 变更 | 940 |
| wage-scheme-detail | /workshop/wage-schemes/:schemeId | 生产车间 / 工价方案 / 详情 | 946 |
| work-report-days | /workshop/work-reports | 生产车间 / 报工记录 | 952 |
| work-report-new | /workshop/work-reports/new | 生产车间 / 报工记录 / 新增 | 958 |
| work-report-edit | /workshop/work-reports/:reportId/edit | 生产车间 / 报工记录 / 编辑 | 964 |
| work-report-day-detail | /workshop/work-reports/days/:productionDate | 生产车间 / 报工记录 / 日期明细 | 970 |
| material-issues | /workshop/material-issues | 生产车间 / 生产领料 | 976 |
| material-issue-new | /workshop/material-issues/new | 生产车间 / 生产领料 / 新增 | 986 |
| material-issue-edit | /workshop/material-issues/:issueId/edit | 生产车间 / 生产领料 / 修改 | 996 |
| material-issue-detail | /workshop/material-issues/:issueId | 生产车间 / 生产领料 / 领料单详情 | 1006 |
| finished-goods-inventory | /inventory/finished-goods | 仓库管理 / 成品库存 | 1016 |
| material-inventory | /inventory/materials | 仓库管理 / 材料库存 | 1030 |
| purchase-inbounds | /purchase-inbound | 采购管理 / 采购入库 | 1045 |
| material-inventory-detail | /inventory/materials/:stockItemId | 仓库管理 / 材料库存 / 订单追溯 | 1060 |
| workshop-outsourcing | /workshop/outsourcing | 生产车间 / 委外加工 | 1070 |
| workshop-outsourcing-new | /workshop/outsourcing/new | 生产车间 / 委外加工 / 新增外发单 | 1084 |
| workshop-outsourcing-metal-processing | /workshop/outsourcing/metal-processing |  | 1098 |
| workshop-outsourcing-rework-detail | /workshop/outsourcing/rework/:orderId | 生产车间 / 委外加工 / 外发单详情 | 1103 |
| workshop-outsourcing-detail | /workshop/outsourcing/:orderId | 生产车间 / 委外加工 / 外发单详情 | 1117 |
| workshop-outsourcing-factories | /workshop/outsourcing/factories | 生产车间 / 委外加工 / 加工厂管理 | 1131 |
| workshop-outsourcing-factory-detail | /workshop/outsourcing/factories/:factoryId | 生产车间 / 委外加工 / 加工厂详情 | 1145 |
| workshop-scheduling-new | /workshop/scheduling/new | 生产车间 / 新增排产 | 1159 |
| workshop-scheduling-edit | /workshop/scheduling/:scheduleId/edit | 生产车间 / 编辑排产 | 1173 |
| workshop-scheduling-detail | /workshop/scheduling/:scheduleId | 生产车间 / 排产详情 | 1187 |
| material-purchase-inbound | /purchase-inbound/order/:purchaseOrderId | 采购管理 / 采购入库 / 仓库收货 | 1201 |
| material-quality-confirmation | /purchase-inbound/quality | 采购管理 / 采购入库 / 品质确认 | 1216 |
| purchase-returns | /purchase-returns | 采购管理 / 退货明细 | 1231 |
| manual-material-inbound | /inventory/materials/inbound | 仓库管理 / 材料库存 / 材料入库 | 1246 |
| material-inbound-details | /inventory/material-inbounds | 仓库管理 / 入库明细 | 1261 |
| purchase-orders | /purchase-orders | 采购管理 / 采购订单 | 1276 |
| purchase-order-create | /purchase-orders/new | 采购管理 / 采购订单 | 1291 |
| purchase-order-create-details | /purchase-orders/new/details | 采购管理 / 采购订单 | 1306 |
| purchase-order-confirm | /purchase-orders/:id/confirm | 采购管理 / 采购订单 | 1321 |
| purchase-sheet-template-select | /purchase-orders/:id/templates | 采购管理 / 采购订单 | 1336 |
| supplier-purchase-sheets | /supplier-purchase-sheets | 采购管理 / 供应商采购表 | 1351 |
| supplier-purchase-sheet-editor | /supplier-purchase-sheets/:id | 采购管理 / 供应商采购表 | 1366 |
| purchase-contract-templates | /purchase-contract-templates | 采购管理 / 采购合同模板 | 1381 |
| suppliers | /suppliers | 采购管理 / 采购订单 / 供应商管理 | 1396 |
| supplier-create | /suppliers/new | 采购管理 / 供应商 | 1411 |
| supplier-edit | /suppliers/:supplierId/edit | 采购管理 / 供应商 | 1426 |
| email-account-settings | /settings/email-accounts | 系统配置 | 1441 |
| reference-data-settings | /settings/reference-data | 系统配置 | 1454 |
| master-data-center | /settings/master-data | 系统配置 | 1467 |
| production-data | /settings/production-data | 系统配置 | 1480 |
| inquiry-handling-settings | /settings/inquiry-handling-time | 系统设置 / 询盘处理时限 | 1493 |
| number-rules | /settings/number-rules | 系统配置 | 1499 |
| not-found | /:pathMatch(.*)* | 页面不存在 | 1512 |

## 侧栏条目

| 名称 | 路由 | 当前菜单权限 |
| --- | --- | --- |
| 工作台 | { name: 'home' } | 未声明 |
| 客户管理 | 分组 | 按子项 |
| 客户列表 | { name: 'customers' } | customers.view_customeraccount |
| 客诉管理 | { name: 'complaints' } | customers.view_customercomplaint |
| 询盘管理 | { name: 'inquiries' } | inquiries.view_inquiry |
| 报价管理 | { name: 'quotations' } | quotations.view_quotation |
| 销售订单 | { name: 'sales-orders' } | 未声明 |
| 任务中心 | { name: 'tasks' } | workflow.view_businesstask |
| 分析中心 | 无路由 | customers.view_customeraccount |
| 样品管理 | 分组 | 按子项 |
| 打样申请 | { name: 'samples' } | samples.view_samplerequest |
| 样品库 | { name: 'sample-inventory' } | samples.view_sampleinventoryline |
| 产品管理 | 分组 | 按子项 |
| 产品信息 | { name: 'products' } | products.view_productinformation |
| 原料信息 | { name: 'raw-materials' } | products.view_rawmaterialinformation |
| 生产管理 | 分组 | 按子项 |
| 生产订单 | { name: 'production-tasks' } | production_tasks.view_productiontask |
| BOM 管理 | { name: 'boms' } | boms.view_bom |
| 采购管理 | 分组 | 按子项 |
| 采购订单 | { name: 'purchase-orders' } | ['procurement.view_purchaseorder', 'procurement.view_supplier'] |
| 采购入库 | { name: 'purchase-inbounds' } | ['inventory.receive_material', 'inventory.quality_confirm_material'] |
| 退货明细 | { name: 'purchase-returns' } | procurement.view_purchaseorder |
| 生产车间 | 分组 | 按子项 |
| 生产配置 | { name: 'workshop-configuration' } | workshop_config.view_workshop |
| 计划排产 | { name: 'workshop-scheduling' } | production_scheduling.view_productionschedule |
| 内部计划 | { name: 'workshop-metalworking-plan' } | production_scheduling.view_productionschedule |
| 委外加工 | { name: 'workshop-outsourcing' } | ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'] |
| 生产领料 | { name: 'material-issues' } | material_issues.view_materialissue |
| 工价方案 | { name: 'wage-schemes' } | workshop_reporting.view_wagescheme |
| 报工记录 | { name: 'work-report-days' } | workshop_reporting.view_workreport |
| 仓库管理 | 分组 | 按子项 |
| 成品库存 | { name: 'finished-goods-inventory' } | inventory.view_finishedgoodsreceipt |
| 材料库存 | { name: 'material-inventory' } | inventory.view_materialinbound |
| 不良品库存 | 无路由 | inventory.view_finishedgoodsreceipt |
| 库存预警 | 无路由 | inventory.view_finishedgoodsreceipt |
