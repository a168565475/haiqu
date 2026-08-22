# haiqu ERP CRM 数据库说明

## 当前落地结果

- PostgreSQL：17
- Django：5.2
- 业务表：71 张
- public Schema 总表数：81 张（含 Django 自带认证、会话等 10 张表）
- PostgreSQL 扩展：btree_gist、pg_trgm
- 自定义数据库完整性触发器：18 个
- 业务编号序列：4 个
- 业务动作权限：13 项
- 初始化组织：HAIQU / 海趣
- 初始化字典：15 项

数据库结构以 Django Migration 为唯一变更入口，haiqu_erp_schema.sql 是本次迁移完成后的只读结构快照，不应直接代替后续 Migration。

## 执行 Migration

    docker compose exec -T backend python manage.py migrate --noinput

检查模型与 Migration 是否一致：

    docker compose exec -T backend python manage.py makemigrations --check --dry-run
    docker compose exec -T backend python manage.py migrate --check

## 初始化数据

Migration 会自动写入：

- 1 个根组织：HAIQU / 海趣
- 客户关注等级：4 项
- 沟通类型：6 项
- 询价来源：5 项

初始化数据使用确定性 UUID，并采用“仅在不存在时创建”的方式，不覆盖已有业务配置。

## 基础测试数据

测试夹具不会随 Migration 自动写入，避免污染正式或开发数据。仅在独立测试数据库中按需执行：

    docker compose exec -T backend python manage.py loaddata basic_test_data

夹具包含 6 条对象：测试员工、客户账户、交易主体、联系人、草稿询价和询价明细。

## 数据库层保护

关键规则同时落在 PostgreSQL 层，防止脚本、后台任务或批量导入绕过 Django 校验：

- 审计日志只允许新增，不允许修改或删除
- 组织父子层级和联系人来源链禁止循环
- 客户、交易主体、联系人、询价、报价、样品之间必须属于同一客户账户
- 已提交询价和活动中的样品申请至少保留一条明细
- 已锁定报价版本的商业数据、快照和明细不可篡改
- 已寄出样品的收件、地址和物流快照不可篡改
- 已完成客户合并必须恰好有一个存续客户和至少一个来源客户
- 沟通记录关联的联系人、询价、报价、样品必须属于同一客户

## Schema 快照

haiqu_erp_schema.sql 由当前数据库执行 pg_dump --schema-only --no-owner --no-privileges 生成，包含表、索引、约束、函数和触发器，不包含业务数据和密码。
