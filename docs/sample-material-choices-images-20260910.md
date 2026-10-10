# 打样材料选择与图片继承验收

2026-09-10。本次沿用现有 BOM 编辑交互和打样页面布局，未修改 Figma、数据库结构或后端状态流程。

## 完成内容

1. 管材材料名称读取有效的管材品名维护数据。
2. 管材规格通过配置中的直径、厚度级联选择，保存组合文字。历史规格保留原值，不自动清空或改写。
3. 颜色下拉读取有效颜色配置，展示并保存“颜色 - 色卡 - 色号”；历史材料主档中的颜色文字仍保留。
4. 五金件、塑料件、辅料、包材移除手动添加材料、添加一行和抽屉新增下一条入口。通过选材弹窗按品名分组、搜索和多选；跨组选择保留，重复选入不重复加行，需求数量由用户填写。
5. 材质改为下拉选择。管材、面料、辅料读取对应维护配置；五金、塑料件、包材没有独立材质配置表，采用现有有效材料主档的去重材质作为最小兼容来源。
6. 创建页、厂长确认和材料需求页的产品图片使用打样参考图，支持错误占位。仓库通过原有“查看原申请”入口查看该图。
7. 询盘创建打样时，一张有效附件自动带入；多张附件由用户选择。支持上传替换或移除；替换不会删除、改写原询盘附件。

## 文件范围

前端业务与类型：
- `src/frontend/src/views/samples/SampleApplicationCreateView.vue`
- `src/frontend/src/views/samples/sampleApplication.scss`
- `src/frontend/src/api/sampleApplication.ts`、`sampleMaterials.ts`
- `src/frontend/src/types/sample.ts`、`sampleApplication.ts`、`sampleMaterial.ts`
- `src/frontend/src/utils/sampleMaterial.ts`

现有组件调整：
- `src/frontend/src/components/samples/SampleMaterialEditor.vue`
- `SampleMaterialFieldInput.vue`、`SampleMaterialLineDrawer.vue`、`SampleMaterialPicker.vue`
- `SampleMaterialApplicationInfo.vue`、`SampleApplicationSummary.vue`

新增共用组件：`src/frontend/src/components/samples/SampleProductImage.vue`。

后端：
- `src/backend/apps/samples/material_reference_selectors.py`
- `src/backend/apps/samples/form_selectors.py`
- `src/backend/apps/samples/application_services.py`
- `src/backend/apps/samples/api/application_serializers.py`
- `src/backend/apps/samples/api/material_serializers.py`、`material_views.py`

复用现有 `PinyinFilterSelect`、材料分区、选材弹窗、行编辑抽屉、全屏、未保存保护、Warm ERP Token 和 Element Plus 基础控件。没有新增依赖或普通 CSS。

## 数据与权限边界

- 管材配置没有完整规格表，当前以“直径 × 厚度”组合；未引入新的规格维护模块。
- 当前询盘图片属于整张询盘附件，没有与产品行一对一关联。因此多图不猜测产品对应关系。
- 可继承图片须为未归档、扫描通过的 PNG/JPEG，且属于来源询盘；沟通插图不作为产品附件。
- 同时要求原附件查看权限和 `accessible_inquiries(request, 'view_inquiry')` 数据范围。只有样品创建临时授权，不能获得该询盘图片。
- 原有校验、幂等、ETag 并发控制、状态与操作权限保持。图片替换失败不会删除原图。
- 配置缺失时不能自由创建受控字段选项；历史文字快照仍可展示。材料数量和有效单位仍按原规则校验。
- 仅调整颜色入参最大长度至 500 以容纳三段显示文字，不迁移数据库。

## 验证结果

- 前端 8 个专项文件，49 项测试通过，包含材料分组、配置控件、跨页选择、取消、连续编辑、图片继承和替换。
- 后端 33 项测试通过，覆盖应用提交、材料接口、图片继承、替换不影响原询盘，以及只有样品创建数据授权时拒绝继承图片。
- `npm run type-check` 通过。
- 最后一次 `npm run build` 通过，仍有原有第三方 PURE 注释和大包警告。
- 项目未配置 lint 脚本；未新增 lint 依赖。
- 已进行独立只读代码审查并修复图片数据权限问题。

```powershell
# 在 src/frontend 执行
npm run test -- src/components/samples/SampleMaterialEditor.spec.ts src/views/samples/SampleApplicationCreateView.spec.ts src/views/samples/SampleMaterialFlow.spec.ts src/api/sampleApplication.spec.ts src/api/sampleMaterials.spec.ts src/utils/sampleMaterial.spec.ts src/api/sampleWarehouse.spec.ts src/utils/sampleWarehouse.spec.ts
npm run type-check
npm run build

# 在项目根目录执行，使用现有 Docker 后端和独立测试数据库
docker exec haiqu-backend python manage.py test apps.samples.tests.test_application_api apps.samples.tests.test_application_image_inheritance apps.samples.tests.test_material_reference_api apps.samples.tests.test_material_api --keepdb --noinput
```

## 浏览器验收

真实 Chrome，1920×1080，所有 API 转发到独立 Django 服务及 `qa_sample_application_20260910` 隔离数据库，没有模拟接口返回，也没有将验收记录写入正式业务库。

路径：询盘详情“创建样品” → 单图继承 / 多图选择与上传替换 → 提交厂长 → 确认交打样部 → 管材配置选择 → 全屏抽屉 → 四类品名分组 → 保存刷新 → 提交仓库 → 查看原申请图片。

实测侧栏 230px、顶栏 64px、抽屉宽 600px；无横向溢出。新增询盘图片下拉导致数量区下移的问题已修正，小预览缩为 100px，右侧上传区仍为 310px，数量区完整位于页脚上方。人工查看创建页、管材表格、抽屉、分组选材、原申请图片截图。

最终运行：`qa/sample_material_choices_images.cjs`，结果 PASS；截图及 JSON 在 `outputs/sample_material_choices_images_20260910/`。黑色图片为隔离验收使用的有效 PNG 测试图，不是真实产品照片。

没有进行本次新增交互与 Figma 的逐像素比较，不宣称新增下拉和弹层已逐像素一致。现有页面结构沿用原实现。

## 手工检查

1. 打开待填写材料需求：管材新增一行，选择品名、规格、材质和颜色，填写数量及单位，保存后刷新确认保留。
2. 切换五金、塑料、辅料、包材：通过“选择数据 / 选择辅料 / 选择包材”按品名筛选，检查没有手动新增按钮。
3. 从带图片的询盘创建样品：检查单图自动显示、多图可选；替换后产品图片同步改变，原询盘附件保持不变。
