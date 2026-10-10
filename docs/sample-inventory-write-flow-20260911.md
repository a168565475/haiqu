# 样品库存真实写流程验收 · 2026-09-11

## 范围与环境

真实前端当前构建产物，通过样品管理 → 样品库进入批量入库、出库、借出；浏览器1920×1080。所有 `/api/**` 转发到 `http://127.0.0.1:18001` 的独立Django服务，无模拟业务响应，不写日常业务库。

服务容器：`haiqu-sample-flow-qa`，数据库：`qa_sample_application_20260910`。已有 `src/backend/tmp/sample_application_qa_server.py` 在启动前强制核对数据库名称，上传目录独立。当前服务保留用于接下来编辑/费用/物流隔离验收。

启动命令（项目根目录；同名容器已存在时不要重复创建）：

```powershell
docker compose run -d --no-deps --name haiqu-sample-flow-qa -p 127.0.0.1:18001:8000 -e POSTGRES_DB=qa_sample_application_20260910 -e DEV_AUTO_LOGIN_ENABLED=true -e DEV_AUTO_LOGIN_USERNAME=qa_sample_flow backend python /app/tmp/sample_application_qa_server.py
```

隔离库存在询盘0008/0009、生产任务0010/0011共4项未应用迁移；本次未应用这些无关迁移，库存验收接口正常。后端自动化测试使用另一套 `test_qa_sample_application_20260910` 测试数据库。

## 实際执行

- `src/backend/tmp/sample_inventory_flow_qa_seed.py` 仅允许专用隔离库，事务内生成2条完成样品及独立成品仓、库区、库位，不伪造业务提交响应。
- `qa/sample_inventory_write_flow_20260911.cjs` 使用真实Session/CSRF与界面控件，批量两行各入库4；第一行出库1（业务员带走）、借出1（填写借用人和用途）；返回样品库存重新GET核对。
- 本次通过的前置单：`QA-SAM-B0812ECFDD`；入库 `RK-202609-000012`，出库 `CK-202609-000007`，借出 `JC-202609-000007`。三次业务提交均返回201。
- 样品库存实际返回：received=4、outbound=1、loaned=1、available=2。第二行未出借，剩余4。
- 入库详情真实返回两行对应成品入库单与选择的库位。额外Docker只读查询核对成品入库记录：`CPRK-202609-000062` 入库4/剩余2，`CPRK-202609-000063` 入库4/剩余4。
- 浏览器 errors=[]；截图与完整JSON：`outputs/sample_inventory_write_flow_20260911/`。已人工检查填写弹窗及最终库存截图。

之前失败为验收脚本定位隐藏输入、未等待加载完成和多遮罩严格选择器错误；修正脚本后重新使用独立前置记录跑完整流程。没有为了使验收通过改产品规则或接口。可重复验收前先重新运行seed脚本，不在旧已入库的样品上重复提交相同数量。

## 测试结果

- 打样后端全量：115项通过，190.528秒。命令 `docker exec -e POSTGRES_DB=qa_sample_application_20260910 haiqu-backend python manage.py test apps.samples.tests --keepdb --noinput --verbosity 1`；日志 `outputs/sample-goal-backend-20260911-tests.log`。
- 前端最新全量：415项/413通过/2失败；打样相关31文件227项全部通过。两项失败在无关基础资料中心模拟接口缺失，不改测试绕过。
- 最新类型检查和生产构建通过；项目未配置lint。

库存三类提交的成功链路已完成真实端到端验收。权限、并发冲突、数量上限及异常回滚另由组件和后端专项覆盖，不将浏览器成功链路等同于所有失败分支端到端覆盖。完整打样目标的编辑、费用、物流写流程与总审查仍需继续。
