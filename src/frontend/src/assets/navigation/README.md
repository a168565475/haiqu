# 全局侧栏资源

- `hitree-rail-mark.png`：此前按用户确认的 h、叶片、HiTree 品牌图制作，保持原资源。
- `house.svg`、`warehouse.svg`、`calendar.svg`：Lucide 0.468.0 官方资源，原样保存。来源：<https://github.com/lucide-icons/lucide/tree/0.468.0/icons>；许可见 `lucide-LICENSE`。
- `document-lines.svg`：Bootstrap Icons v1.11.3 的 `file-text.svg`，原样保存，仅调整本地文件名。来源：<https://github.com/twbs/icons/blob/v1.11.3/icons/file-text.svg>；许可见 `bootstrap-icons-LICENSE`。

上述 SVG 是历史侧栏资源及其许可记录，本轮保留原文件。2026-10-16 用户确认二级图标方案后，当前侧栏不再依赖这些 CSS mask 或旧 IconPark 图标。

一级菜单、底部入口及浮层标题使用 `components/navigation/ConfirmedSidebarIcon.vue` 中的12项本地矢量图标，按2026-10-16用户确认图的具体轮廓与双色细节实现，不以单色库图标替代。设计来源与逐项对照见 `qa/artifacts/sidebar-confirmed-icons-20261016/`；深炭轮廓、品牌橙点缀及默认/悬停/选中状态由侧栏局部样式管理，没有新增运行时依赖。

二级35项使用 `components/navigation/ConfirmedSecondarySidebarIcon.vue`，逐项沿用已预览的 `docs/designs/sidebar_motion_20261016/secondary-icons.js` 图案。画布24px、描边1.7px、导航内显示22px。一级悬停D+B、二级A+D，选中分别为第1种浅橙底与第3种橙色色轨；详细规范见项目根 `DESIGN.md` 的10.2.1节。
