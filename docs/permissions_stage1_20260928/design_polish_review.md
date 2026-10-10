# 权限管理预览设计规范优化记录

日期：2026-09-28。用户已通过四页签、左侧角色与右侧矩阵的布局，要求读取设计规范后再优化。此次仅修改阶段 1 原型与文档，未实施权限后端、修改真实账号或写入业务数据。

## 依据与取舍

依据 [DESIGN.md 第 10 章](../../DESIGN.md)、现有 [PageContainer](../../src/frontend/src/layouts/PageContainer.vue)、[颜色与字体 token](../../src/frontend/src/styles/crm/_tokens.scss) 和 [AppWindowDialog](../../src/frontend/src/components/common/AppWindowDialog.vue)。原型保留已通过的页面组织，不增加新权限规则。

| 项目 | 优化结果 |
| --- | --- |
| 色彩 | 暖色底与内容面；品牌橙 #c84e28、规范文字与边框色；选中和悬停分别采用 #fff4e6、#fff6ea |
| 字体 | Noto Serif SC 标题 34/44px；Noto Sans SC 正文；浏览器实际字体信息已核实 |
| 壳层与间距 | 230px 侧栏、64px 顶栏、单层 14px 内容边距；控件组间距 14px |
| 控件与表格 | 32px 按钮和单行控件、14px 复选框；44px 表头、40px 行高；明确列宽与层次字体 |
| 标签 | Strong 实色胶囊，24px 高、最小宽 56px、白字、无边框 |
| 操作组织 | 角色数量紧邻标题，各页签新建操作位于标题右侧；文本搜索按回车确认 |
| 图标 | 直接从已安装的 IconPark 组件生成静态 SVG，不使用字符替代导航图标 |
| 弹窗 | 本地构建真实 AppWindowDialog 组件；44px 标题栏、32px 窗口按钮、16px 图标；拖动、缩放、最大化、最小化与还原 |
| 滚动 | 页面整体固定，角色列表和矩阵分别滚动；长弹窗只滚动正文，标题与底部操作可见 |

规范中 10.5 的单层 14px 页面边距及当前 PageContainer 优先于旧章节中的 28px 外边距。公共 token 中仍有旧的 36px 按钮、38px 输入、52px 行高；此次仅在原型使用规范要求的最新尺寸，避免扩大为全站控件变更。权限矩阵属于设置表单，不添加没有业务意义的分页；员工、团队与记录示例仅展示当前少量数据和 48px 底部说明。

## 实际验证

- 本地 Vite 构建弹窗运行文件，Sass 编译原型样式成功；未运行或替换 ERP 正式构建。
- 原有交互检查 **23 项通过**：[报告](../../qa/permissions_stage1_20260928/preview_verification.json)。
- 设计与弹窗检查 **24 项通过**：[报告](../../qa/permissions_stage1_20260928/design_polish_verification.json)。包含四页签控件与行高、真实字体、品牌色、列宽、回车搜索、拖动缩放与窗口还原、长内容内部滚动。
- Chrome 1920×1080 实际页面无整体溢出、无 JavaScript 错误、无外部 HTTP 请求。已逐图查看角色、员工、团队、授权记录、变更确认与长内容窗口截图。
- [角色页](../../qa/permissions_stage1_20260928/roles_1920.png)、[员工页](../../qa/permissions_stage1_20260928/employees_1920.png)、[团队页](../../qa/permissions_stage1_20260928/teams_1920.png)、[记录页](../../qa/permissions_stage1_20260928/history_1920.png)、[权限差异弹窗](../../qa/permissions_stage1_20260928/permission_diff_1920.png)、[长窗口滚动](../../qa/permissions_stage1_20260928/window_scroll_1920.png)。优化前截图保存在同一 QA 目录的 before_design_polish 文件夹。

## 复现与范围

从 ERP 根目录执行：

```powershell
node qa/permissions_stage1_20260928/build_preview.cjs
node qa/permissions_stage1_20260928/verify_preview.cjs
node qa/permissions_stage1_20260928/verify_design_polish.cjs
```

[打开管理原型](management_preview.html)。HTML 引用同目录 preview_assets 中的本地构建产物，可直接通过 file:// 打开。字体使用本机已安装的 Noto 字体，其他电脑缺少时会回退；上述字体证据仅针对当前验收电脑。原型中的演示操作仅保留在页面内存，刷新恢复。构建脚本直接引用现有业务弹窗，未复制或修改其生产源码；正式业务实现与权限验收仍属于后续阶段。
