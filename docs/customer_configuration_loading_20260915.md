# 已发布配置缓存与客户详情加载

> 本文记录前一阶段实现。配置轮询与前端常驻缓存已由 [全局配置按需读取与 Redis 缓存](configuration_on_demand_redis_20260915.md) 替代；客户详情加载及批量接口的调整继续保留。

## 行为

- 正式配置仍保存于 PostgreSQL。业务页面已发布字典采用 Pinia 内存缓存，不持久化到本地文件或 localStorage。
- 可见页面每30秒核对已发布版本及字典类型状态，重新聚焦也核对；更新后自动刷新已加载类型。身份变化清缓存。隐藏页面恢复可见时检查。
- 同时读取不同字典合并为批量请求，最多20类。历史停用项继续携带 current_id 使用原单项接口，避免混入新建业务的可选项。
- 请求失败可重试；旧版本迟到不会覆盖新版；失效后最多重试2次，防止发布持续变化形成无限请求。
- 客户概览并行启动基础信息、汇总、地址和概览内容；保留地址完整度计算，主体/地址编辑版本及编辑选项仅编辑时读取。

## 新增只读接口

接口均要求已登录且员工有效，响应设置 Cache-Control: no-store；前端自行控制版本缓存。

### GET /api/v1/reference-data/published-version/

返回 data.config_version（可为null）与 data.config_revision。revision包含发布记录标识及字典类型更新时间，可识别同一发布版本下的类型停用。

### GET /api/v1/reference-data/options-batch/?type_codes=CUSTOMER_GRADE,CUSTOMER_TYPE

返回 data（类型编码到选项列表）、errors（无效或停用类型的错误）、meta（与版本接口相同的两个字段）。单个类型不可用不阻止其他类型返回；空请求、超过20类、非法编码返回400。一次批量读取统一使用同一份发布快照，不读取未发布草稿。

## 未增加Redis缓存的依据

当前25KB配置快照的热态查询及读取中位约2～3毫秒，主要等待在接口往返及页面初始化依赖。优先减少请求次数和串行等待，避免为了很小收益增加后端缓存维护。若后续快照规模或并发显著增加，再按测量结果引入Redis；不得把缓存作为唯一数据源。

## 环境与验证

无新增依赖、配置项或数据库迁移。沿用现有 Docker Compose 服务，前后端源码热加载后生效；已有浏览器需要刷新一次取得新前端代码。

```powershell
docker compose exec -T -e TZ=Asia/Shanghai frontend npm run test -- --run src/composables/useOptions.spec.ts src/stores/referenceOptions.spec.ts src/api/referenceData.spec.ts src/views/customers/CustomerListLoading.spec.ts src/views/customers/CustomerDetailLoading.spec.ts src/views/customers/customerOverview.spec.ts src/views/customers/customerForm.spec.ts src/stores/auth.spec.ts
docker compose exec -T backend python manage.py test apps.reference_data.tests.test_published_reads --keepdb --noinput --verbosity 1
docker compose exec -T frontend npm run type-check
docker compose exec -T frontend npm run build
```

实测结果及证据见 `qa/customer_config_cache_20260915/report.md`。业务写入在隔离测试数据库中验证；浏览器配置更新为模拟发布，客户入口为真实只读验证。
