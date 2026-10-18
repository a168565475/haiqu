# 全局主题配色

本目录是运行界面的唯一公共配色来源。组件按用途取颜色，不自行写冷蓝、暖橙或白底。

2026-10-17留白与动态：两套主题同时提供`table-frame-border`、`spotlight-fill/edge`；表格外缘和内部网格分开取色。`_semantic.scss`提供筛选卡14/16/10、内容卡10/14/0、工具栏内收2/间隔10的共用变量，页面显式使用。`_motion.scss`的`erp-button-motion`只给实体操作按钮启用；`_spotlight.scss`配合`vGlassSpotlight`用于顶部导航和客户筛选卡，光标移动用rAF合并，光斑层不拦截点击。减少动态模式、触屏和打印停用跟随；不调整输入框已认可材质或任何控件高度。

| 文件 | 职责 |
| --- | --- |
| _blue-gray.scss / _warm.scss | 每套主题完整色表，含背景、文字、边框、玻璃、菜单、统计卡、12组Tag及浏览器原生控件色系 |
| _semantic.scss | 把色表导出成 --erp-* 用途变量；共享字体、材质参数和间距 |
| _components.scss | 将用途变量映射为按钮、表格、输入、下拉、提示气泡、分页及 Element Plus 变量 |
| _controls.scss | 接管组件库颜色、主题渐变/高光/阴影和控件圆角；统一业务弹窗输入控件尺寸，纸面/表格例外由作用域保留，不改变其他布局和动画 |
| _list.scss | 显式接入的业务列表共用骨架、筛选控件、表格边缘与分页；不影响内嵌任务 |
| ../theme.scss | 主题选择器、变量输出和配色完整性检查 |
| ../../theme.ts | 可用主题、默认主题、浏览器保存和切换 |

## 弹窗表单控件规范

所有业务弹窗必须使用 `AppWindowDialog`。弹窗里的单行输入、选择器、日期、级联、自动完成和数字输入统一复用客户列表筛选框的控件参数：高度 `32px`、左右内边距 `12px`、控件圆角使用 `--erp-radius-control`，表面使用 `--erp-input-surface`，阴影使用 `--erp-input-shadow`，边缘和悬停/聚焦状态分别使用 `--erp-input-border`、`--erp-input-hover-border`、`--erp-input-focus-border`。输入文字与占位文字使用对应的 `--erp-input-*` 语义色，禁用态使用 `--erp-input-disabled-*`。

文本域沿用同一套表面、边缘、阴影、文字和禁用态，只保留业务所需的最小高度与可调整方向。弹窗局部样式不得重新设置旧的 `5px` 圆角、`10px` 内边距、纯色背景或独立阴影；特殊纸面、打印和表格内编辑控件必须通过明确的作用域保留例外。新增弹窗先接入 `AppWindowDialog`，再复用这套全局控件规则，不在业务页面复制一份输入框颜色。

当前默认冷蓝银，可在“主题”切换暖色。两套主题有意共用已确认的12组Tag，主题切换不改变业务状态的含义。

新增深色时：

1. 提供完整的 _dark.scss 色表，逐项对应现有用途；color-scheme设为dark，分别定义文字、透明表面、遮罩和图标，不能只反转背景。
2. 在theme.scss注册html[data-theme='dark']及预览作用域，并将它加入完整性检查。取得确认后，在theme.ts的可用主题中启用dark。
3. 验证真实页面、浮层、禁用态、对比度、刷新后的主题保持；菜单动画和布局不用改。

组件示例：表头用var(--erp-table-header-background)，正文用var(--erp-table-text)，品牌按钮表面用var(--erp-button-primary-surface)，纯颜色位置仍用var(--erp-button-primary-background)。不要用“浅色/深色”判断散落在各组件里。

2026-10-17：新增按钮表面/高光阴影、输入表面、导航强调色/页签底线/管理员文字、Logo滤色和统计分隔线角色，两套色表保持完整对应。外骨架16px圆角，控件8px圆角；按钮/输入高度不改变。Logo使用原PNG明暗，不用单色蒙版；客户表头按最新确认调整为38px，行40px及列宽保持。

CSS变量在运行时切换。CRM旧Sass颜色变量仅作为兼容别名，不再保存独立色值；计算透明度用color-mix，不把CSS变量传给只接受编译期颜色的Sass函数。

玻璃材质分两层用途：`glass-background`是45%白色纯颜色（遮罩等只能接颜色的位置继续用它）；`glass-surface`是骨架表面，冷色叠同一视口坐标的细反光，暖色直接引用原背景。背景柔光仍只由`page-background`统一绘制。色表与截图要共同校准，不能仅以透明度或blur数值正确判定视觉还原。

当前独立列表范围以`src/frontend/src/config/glassListRoutes.ts`的41个路由登记为准，另含此前已确认的客户列表；涵盖CRM、样品、产品/原料、采购、生产/车间、仓库台账及5个设置列表。后续详情、表单、内嵌表格、业务浮层与登录的颜色接入清单见`docs/designs/remaining_pages_theme_20261017/README.md`；旧`non-list-theme-audit.md`保留为迁移前记录。独立大屏、真实内容/纸面例外及数据不足未验收分支见新报告，不能把全局主题接通当作全站完成或深色视觉验收。

2026-10-17剩余业务页面：两套色表同步增加`shadow-color`、`overlay-scrim-color`、`login-background`、`login-art-filter`和`chart-series-1..5`。局部阴影只替换颜色与原透明比例，保留位置、模糊和扩散；内侧1px边框使用对应边框角色。普通实体主按钮保留全局渐变材质，不能被局部纯色background覆盖；disabled/text/link/plain保持各自用途。登录滤镜只作用于该页面的装饰图片，历史报价保留原系列含义和顺序。

2026-10-17列表推广：`_list.scss`通过`.erp-glass-list`显式接入询盘、报价、销售订单与独立任务中心，将卡片/工具栏留白、完整输入材质、38px表头、40px普通行、单层表格外缘和40/28分页共同实现；客户详情内嵌任务不接入。客户列表现有实现继续保持原样。更多筛选浮层用`.erp-list-filter-popover`接入相同32px控件，业务字段与查询时机不由样式决定。

后续扩大到全部登记列表：原生表格、按钮与输入分别用`erp-list-native-table`、`erp-list-button`、`erp-list-control`显式复用。分类目录/真实统计/Tab/报工左右联动仍按业务结构排列；颜色来自同一语义变量。无筛选字段的页面不放无效筛选按钮；有筛选字段的页面常驻“重置 → 应用筛选”。

用户明确主题主要用于换色：`_blue-gray.scss` / `_warm.scss`及未来确认的色表只负责颜色和表面材质；`_primitives.scss`、`_semantic.scss`中的共享尺寸和`_list.scss`布局不复制进新主题。卡片大小、间距、圆角、字号、按钮/输入高度、表头/行高与动画时序保持固定。另两套未来配色尚未确认，当前不预置。正式要求见DESIGN.md 10.0与10.2.4，实际验收见本轮报告。
