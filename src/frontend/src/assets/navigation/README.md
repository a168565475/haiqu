# 全局侧栏资源

- `hitree-rail-mark.png`：此前按用户确认的 h、叶片、HiTree 品牌图制作，保持原资源。
- `house.svg`、`warehouse.svg`、`calendar.svg`：Lucide 0.468.0 官方资源，原样保存。来源：<https://github.com/lucide-icons/lucide/tree/0.468.0/icons>；许可见 `lucide-LICENSE`。
- `document-lines.svg`：Bootstrap Icons v1.11.3 的 `file-text.svg`，原样保存，仅调整本地文件名。来源：<https://github.com/twbs/icons/blob/v1.11.3/icons/file-text.svg>；许可见 `bootstrap-icons-LICENSE`。

SVG 在侧栏中以 CSS mask 使用原始路径，并继承正常/选中状态的文字颜色；没有增加运行时依赖。其余图标复用已安装的 IconPark，厂房水平翻转以对齐参考图烟囱方向。
