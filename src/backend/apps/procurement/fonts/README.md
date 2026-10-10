# 采购合同 PDF 字体及图标

字体使用确认稿的 Noto Sans SC 常规 / 粗体和 Noto Serif SC 粗体。随应用提供文件，PDF 按使用字符嵌入子集，避免依赖服务器或收件人的本地字体。字体资源约 34.2 MiB，不增加 Python 运行依赖。

来源：Google Fonts 官方 CSS API（2026-09-10），使用 `css2?family=Noto%20Sans%20SC:wght@400`、`@700` 和 `Noto%20Serif%20SC:wght@700`。旧版浏览器响应为未压缩 EOT，按头部 FontDataSize 提取末尾原始 TrueType 数据；没有修改字形。授权见本目录两份 OFL 文件。

- https://github.com/google/fonts/tree/main/ofl/notosanssc
- https://github.com/google/fonts/tree/main/ofl/notoserifsc

`pdf-picture.png` 为确认原型节点 2104:2493 中的 Element Plus Picture 图标导出资源，经 Chromium 在 4 倍像素密度下栅格化，仅用于合同无图片空态。原始 SVG 保留于采购 QA 目录。
