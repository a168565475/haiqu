# HAIQU ERP 设计规范

正式设计规则以第 10 章为准。本轮基础项与 10 批共 50 项通用规则已逐批确认，2026-09-30 经用户批准合并；第 11—15 批仅登记源码差异与页面例外，不增加通用规则项。审核来源与实施差异见 10.21。规范确认不等于全部 ERP 页面已经实施或验收。

第 1—9 章保留原 Claude / Anthropic 参考资料，仅供理解历史设计来源；其中颜色、尺寸、组件示例不能作为 ERP 当前实施标准。

## 1. Visual Theme & Atmosphere

Claude's interface is a literary salon reimagined as a product page — warm, unhurried, and quietly intellectual. The entire experience is built on a parchment-toned canvas (`#f5f4ed`) that deliberately evokes the feeling of high-quality paper rather than a digital surface. Where most AI product pages lean into cold, futuristic aesthetics, Claude's design radiates human warmth, as if the AI itself has good taste in interior design.

The signature move is the custom Anthropic Serif typeface — a medium-weight serif with generous proportions that gives every headline the gravitas of a book title. Combined with organic, hand-drawn-feeling illustrations in terracotta (`#c96442`), black, and muted green, the visual language says "thoughtful companion" rather than "powerful tool." The serif headlines breathe at tight-but-comfortable line-heights (1.10–1.30), creating a cadence that feels more like reading an essay than scanning a product page.

What makes Claude's design truly distinctive is its warm neutral palette. Every gray has a yellow-brown undertone (`#5e5d59`, `#87867f`, `#4d4c48`) — there are no cool blue-grays anywhere. Borders are cream-tinted (`#f0eee6`, `#e8e6dc`), shadows use warm transparent blacks, and even the darkest surfaces (`#141413`, `#30302e`) carry a barely perceptible olive warmth. This chromatic consistency creates a space that feels lived-in and trustworthy.

**Key Characteristics:**
- Warm parchment canvas (`#f5f4ed`) evoking premium paper, not screens
- Custom Anthropic type family: Serif for headlines, Sans for UI, Mono for code
- Terracotta brand accent (`#c96442`) — warm, earthy, deliberately un-tech
- Exclusively warm-toned neutrals — every gray has a yellow-brown undertone
- Organic, editorial illustrations replacing typical tech iconography
- Ring-based shadow system (`0px 0px 0px 1px`) creating border-like depth without visible borders
- Magazine-like pacing with generous section spacing and serif-driven hierarchy

## 2. Color Palette & Roles

### Primary
- **Anthropic Near Black** (`#141413`): The primary text color and dark-theme surface — not pure black but a warm, almost olive-tinted dark that's gentler on the eyes. The warmest "black" in any major tech brand.
- **Terracotta Brand** (`#c96442`): The core brand color — a burnt orange-brown used for primary CTA buttons, brand moments, and the signature accent. Deliberately earthy and un-tech.
- **Coral Accent** (`#d97757`): A lighter, warmer variant of the brand color used for text accents, links on dark surfaces, and secondary emphasis.

### Secondary & Accent
- **Error Crimson** (`#b53333`): A deep, warm red for error states — serious without being alarming.
- **Focus Blue** (`#3898ec`): Standard blue for input focus rings — the only cool color in the entire system, used purely for accessibility.

### Surface & Background
- **Parchment** (`#f5f4ed`): The primary page background — a warm cream with a yellow-green tint that feels like aged paper. The emotional foundation of the entire design.
- **Ivory** (`#faf9f5`): The lightest surface — used for cards and elevated containers on the Parchment background. Barely distinguishable but creates subtle layering.
- **Pure White** (`#ffffff`): Reserved for specific button surfaces and maximum-contrast elements.
- **Warm Sand** (`#e8e6dc`): Button backgrounds and prominent interactive surfaces — a noticeably warm light gray.
- **Dark Surface** (`#30302e`): Dark-theme containers, nav borders, and elevated dark elements — warm charcoal.
- **Deep Dark** (`#141413`): Dark-theme page background and primary dark surface.

### Neutrals & Text
- **Charcoal Warm** (`#4d4c48`): Button text on light warm surfaces — the go-to dark-on-light text.
- **Olive Gray** (`#5e5d59`): Secondary body text — a distinctly warm medium-dark gray.
- **Stone Gray** (`#87867f`): Tertiary text, footnotes, and de-emphasized metadata.
- **Dark Warm** (`#3d3d3a`): Dark text links and emphasized secondary text.
- **Warm Silver** (`#b0aea5`): Text on dark surfaces — a warm, parchment-tinted light gray.

### Semantic & Accent
- **Border Cream** (`#f0eee6`): Standard light-theme border — barely visible warm cream, creating the gentlest possible containment.
- **Border Warm** (`#e8e6dc`): Prominent borders, section dividers, and emphasized containment on light surfaces.
- **Border Dark** (`#30302e`): Standard border on dark surfaces — maintains the warm tone.
- **Ring Warm** (`#d1cfc5`): Shadow ring color for button hover/focus states.
- **Ring Subtle** (`#dedc01`): Secondary ring variant for lighter interactive surfaces.
- **Ring Deep** (`#c2c0b6`): Deeper ring for active/pressed states.

### Gradient System
- Claude's design is **gradient-free** in the traditional sense. Depth and visual richness come from the interplay of warm surface tones, organic illustrations, and light/dark section alternation. The warm palette itself creates a "gradient" effect as the eye moves through cream → sand → stone → charcoal → black sections.

## 3. Typography Rules

### Font Family
- **Headline**: `Anthropic Serif`, with fallback: `Georgia`
- **Body / UI**: `Anthropic Sans`, with fallback: `Arial`
- **Code**: `Anthropic Mono`, with fallback: `Arial`

*Note: These are custom typefaces. For external implementations, Georgia serves as the serif substitute and system-ui/Inter as the sans substitute.*

### Hierarchy

| Role | Font | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|------|--------|-------------|----------------|-------|
| Display / Hero | Anthropic Serif | 64px (4rem) | 500 | 1.10 (tight) | normal | Maximum impact, book-title presence |
| Section Heading | Anthropic Serif | 52px (3.25rem) | 500 | 1.20 (tight) | normal | Feature section anchors |
| Sub-heading Large | Anthropic Serif | 36–36.8px (~2.3rem) | 500 | 1.30 | normal | Secondary section markers |
| Sub-heading | Anthropic Serif | 32px (2rem) | 500 | 1.10 (tight) | normal | Card titles, feature names |
| Sub-heading Small | Anthropic Serif | 25–25.6px (~1.6rem) | 500 | 1.20 | normal | Smaller section titles |
| Feature Title | Anthropic Serif | 20.8px (1.3rem) | 500 | 1.20 | normal | Small feature headings |
| Body Serif | Anthropic Serif | 17px (1.06rem) | 400 | 1.60 (relaxed) | normal | Serif body text (editorial passages) |
| Body Large | Anthropic Sans | 20px (1.25rem) | 400 | 1.60 (relaxed) | normal | Intro paragraphs |
| Body / Nav | Anthropic Sans | 17px (1.06rem) | 400–500 | 1.00–1.60 | normal | Navigation links, UI text |
| Body Standard | Anthropic Sans | 16px (1rem) | 400–500 | 1.25–1.60 | normal | Standard body, button text |
| Body Small | Anthropic Sans | 15px (0.94rem) | 400–500 | 1.00–1.60 | normal | Compact body text |
| Caption | Anthropic Sans | 14px (0.88rem) | 400 | 1.43 | normal | Metadata, descriptions |
| Label | Anthropic Sans | 12px (0.75rem) | 400–500 | 1.25–1.60 | 0.12px | Badges, small labels |
| Overline | Anthropic Sans | 10px (0.63rem) | 400 | 1.60 | 0.5px | Uppercase overline labels |
| Micro | Anthropic Sans | 9.6px (0.6rem) | 400 | 1.60 | 0.096px | Smallest text |
| Code | Anthropic Mono | 15px (0.94rem) | 400 | 1.60 | -0.32px | Inline code, terminal |

### Principles
- **Serif for authority, sans for utility**: Anthropic Serif carries all headline content with medium weight (500), giving every heading the gravitas of a published title. Anthropic Sans handles all functional UI text — buttons, labels, navigation — with quiet efficiency.
- **Single weight for serifs**: All Anthropic Serif headings use weight 500 — no bold, no light. This creates a consistent "voice" across all headline sizes, as if the same author wrote every heading.
- **Relaxed body line-height**: Most body text uses 1.60 line-height — significantly more generous than typical tech sites (1.4–1.5). This creates a reading experience closer to a book than a dashboard.
- **Tight-but-not-compressed headings**: Line-heights of 1.10–1.30 for headings are tight but never claustrophobic. The serif letterforms need breathing room that sans-serif fonts don't.
- **Micro letter-spacing on labels**: Small sans text (12px and below) uses deliberate letter-spacing (0.12px–0.5px) to maintain readability at tiny sizes.

## 4. Component Stylings

### Buttons

**Warm Sand (Secondary)**
- Background: Warm Sand (`#e8e6dc`)
- Text: Charcoal Warm (`#4d4c48`)
- Padding: 0px 12px 0px 8px (asymmetric — icon-first layout)
- Radius: comfortably rounded (8px)
- Shadow: ring-based (`#e8e6dc 0px 0px 0px 0px, #d1cfc5 0px 0px 0px 1px`)
- The workhorse button — warm, unassuming, clearly interactive

**White Surface**
- Background: Pure White (`#ffffff`)
- Text: Anthropic Near Black (`#141413`)
- Padding: 8px 16px 8px 12px
- Radius: generously rounded (12px)
- Hover: shifts to secondary background color
- Clean, elevated button for light surfaces

**Dark Charcoal**
- Background: Dark Surface (`#30302e`)
- Text: Ivory (`#faf9f5`)
- Padding: 0px 12px 0px 8px
- Radius: comfortably rounded (8px)
- Shadow: ring-based (`#30302e 0px 0px 0px 0px, ring 0px 0px 0px 1px`)
- The inverted variant for dark-on-light emphasis

**Brand Terracotta**
- Background: Terracotta Brand (`#c96442`)
- Text: Ivory (`#faf9f5`)
- Radius: 8–12px
- Shadow: ring-based (`#c96442 0px 0px 0px 0px, #c96442 0px 0px 0px 1px`)
- The primary CTA — the only button with chromatic color

**Dark Primary**
- Background: Anthropic Near Black (`#141413`)
- Text: Warm Silver (`#b0aea5`)
- Padding: 9.6px 16.8px
- Radius: generously rounded (12px)
- Border: thin solid Dark Surface (`1px solid #30302e`)
- Used on dark theme surfaces

### Cards & Containers
- Background: Ivory (`#faf9f5`) or Pure White (`#ffffff`) on light surfaces; Dark Surface (`#30302e`) on dark
- Border: thin solid Border Cream (`1px solid #f0eee6`) on light; `1px solid #30302e` on dark
- Radius: comfortably rounded (8px) for standard cards; generously rounded (16px) for featured; very rounded (32px) for hero containers and embedded media
- Shadow: whisper-soft (`rgba(0,0,0,0.05) 0px 4px 24px`) for elevated content
- Ring shadow: `0px 0px 0px 1px` patterns for interactive card states
- Section borders: `1px 0px 0px` (top-only) for list item separators

### Inputs & Forms
- Text: Anthropic Near Black (`#141413`)
- Padding: 1.6px 12px (very compact vertical)
- Border: standard warm borders
- Focus: ring with Focus Blue (`#3898ec`) border-color — the only cool color moment
- Radius: generously rounded (12px)

### Navigation
- Sticky top nav with warm background
- Logo: Claude wordmark in Anthropic Near Black
- Links: mix of Near Black (`#141413`), Olive Gray (`#5e5d59`), and Dark Warm (`#3d3d3a`)
- Nav border: `1px solid #30302e` (dark) or `1px solid #f0eee6` (light)
- CTA: Terracotta Brand button or White Surface button
- Hover: text shifts to foreground-primary, no decoration

### Image Treatment
- Product screenshots showing the Claude chat interface
- Generous border-radius on media (16–32px)
- Embedded video players with rounded corners
- Dark UI screenshots provide contrast against warm light canvas
- Organic, hand-drawn illustrations for conceptual sections

### Distinctive Components

**Model Comparison Cards**
- Opus 4.5, Sonnet 4.5, Haiku 4.5 presented in a clean card grid
- Each model gets a bordered card with name, description, and capability badges
- Border Warm (`#e8e6dc`) separation between items

**Organic Illustrations**
- Hand-drawn-feeling vector illustrations in terracotta, black, and muted green
- Abstract, conceptual rather than literal product diagrams
- The primary visual personality — no other AI company uses this style

**Dark/Light Section Alternation**
- The page alternates between Parchment light and Near Black dark sections
- Creates a reading rhythm like chapters in a book
- Each section feels like a distinct environment

## 5. Layout Principles

### Spacing System
- Base unit: 8px
- Scale: 3px, 4px, 6px, 8px, 10px, 12px, 16px, 20px, 24px, 30px
- Button padding: asymmetric (0px 12px 0px 8px) or balanced (8px 16px)
- Card internal padding: approximately 24–32px
- Section vertical spacing: generous (estimated 80–120px between major sections)

### Grid & Container
- Max container width: approximately 1200px, centered
- Hero: centered with editorial layout
- Feature sections: single-column or 2–3 column card grids
- Model comparison: clean 3-column grid
- Full-width dark sections breaking the container for emphasis

### Whitespace Philosophy
- **Editorial pacing**: Each section breathes like a magazine spread — generous top/bottom margins create natural reading pauses.
- **Serif-driven rhythm**: The serif headings establish a literary cadence that demands more whitespace than sans-serif designs.
- **Content island approach**: Sections alternate between light and dark environments, creating distinct "rooms" for each message.

### Border Radius Scale
- Sharp (4px): Minimal inline elements
- Subtly rounded (6–7.5px): Small buttons, secondary interactive elements
- Comfortably rounded (8–8.5px): Standard buttons, cards, containers
- Generously rounded (12px): Primary buttons, input fields, nav elements
- Very rounded (16px): Featured containers, video players, tab lists
- Highly rounded (24px): Tag-like elements, highlighted containers
- Maximum rounded (32px): Hero containers, embedded media, large cards

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat (Level 0) | No shadow, no border | Parchment background, inline text |
| Contained (Level 1) | `1px solid #f0eee6` (light) or `1px solid #30302e` (dark) | Standard cards, sections |
| Ring (Level 2) | `0px 0px 0px 1px` ring shadows using warm grays | Interactive cards, buttons, hover states |
| Whisper (Level 3) | `rgba(0,0,0,0.05) 0px 4px 24px` | Elevated feature cards, product screenshots |
| Inset (Level 4) | `inset 0px 0px 0px 1px` at 15% opacity | Active/pressed button states |

**Shadow Philosophy**: Claude communicates depth through **warm-toned ring shadows** rather than traditional drop shadows. The signature `0px 0px 0px 1px` pattern creates a border-like halo that's softer than an actual border — it's a shadow pretending to be a border, or a border that's technically a shadow. When drop shadows do appear, they're extremely soft (0.05 opacity, 24px blur) — barely visible lifts that suggest floating rather than casting.

### Decorative Depth
- **Light/Dark alternation**: The most dramatic depth effect comes from alternating between Parchment (`#f5f4ed`) and Near Black (`#141413`) sections — entire sections shift elevation by changing the ambient light level.
- **Warm ring halos**: Button and card interactions use ring shadows that match the warm palette — never cool-toned or generic gray.

## 7. Do's and Don'ts

### Do
- Use Parchment (`#f5f4ed`) as the primary light background — the warm cream tone IS the Claude personality
- Use Anthropic Serif at weight 500 for all headlines — the single-weight consistency is intentional
- Use Terracotta Brand (`#c96442`) only for primary CTAs and the highest-signal brand moments
- Keep all neutrals warm-toned — every gray should have a yellow-brown undertone
- Use ring shadows (`0px 0px 0px 1px`) for interactive element states instead of drop shadows
- Maintain the editorial serif/sans hierarchy — serif for content headlines, sans for UI
- Use generous body line-height (1.60) for a literary reading experience
- Alternate between light and dark sections to create chapter-like page rhythm
- Apply generous border-radius (12–32px) for a soft, approachable feel

### Don't
- Don't use cool blue-grays anywhere — the palette is exclusively warm-toned
- Don't use bold (700+) weight on Anthropic Serif — weight 500 is the ceiling for serifs
- Don't introduce saturated colors beyond Terracotta — the palette is deliberately muted
- Don't use sharp corners (< 6px radius) on buttons or cards — softness is core to the identity
- Don't apply heavy drop shadows — depth comes from ring shadows and background color shifts
- Don't use pure white (`#ffffff`) as a page background — Parchment (`#f5f4ed`) or Ivory (`#faf9f5`) are always warmer
- Don't use geometric/tech-style illustrations — Claude's illustrations are organic and hand-drawn-feeling
- Don't reduce body line-height below 1.40 — the generous spacing supports the editorial personality
- Don't use monospace fonts for non-code content — Anthropic Mono is strictly for code
- Don't mix in sans-serif for headlines — the serif/sans split is the typographic identity

## 8. Responsive Behavior

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Small Mobile | <479px | Minimum layout, stacked everything, compact typography |
| Mobile | 479–640px | Single column, hamburger nav, reduced heading sizes |
| Large Mobile | 640–767px | Slightly wider content area |
| Tablet | 768–991px | 2-column grids begin, condensed nav |
| Desktop | 992px+ | Full multi-column layout, expanded nav, maximum hero typography (64px) |

### Touch Targets
- Buttons use generous padding (8–16px vertical minimum)
- Navigation links adequately spaced for thumb navigation
- Card surfaces serve as large touch targets
- Minimum recommended: 44x44px

### Collapsing Strategy
- **Navigation**: Full horizontal nav collapses to hamburger on mobile
- **Feature sections**: Multi-column → stacked single column
- **Hero text**: 64px → 36px → ~25px progressive scaling
- **Model cards**: 3-column → stacked vertical
- **Section padding**: Reduces proportionally but maintains editorial rhythm
- **Illustrations**: Scale proportionally, maintain aspect ratios

### Image Behavior
- Product screenshots scale proportionally within rounded containers
- Illustrations maintain quality at all sizes
- Video embeds maintain 16:9 aspect ratio with rounded corners
- No art direction changes between breakpoints

## 9. Agent Prompt Guide

### Quick Color Reference
- Brand CTA: "Terracotta Brand (#c96442)"
- Page Background: "Parchment (#f5f4ed)"
- Card Surface: "Ivory (#faf9f5)"
- Primary Text: "Anthropic Near Black (#141413)"
- Secondary Text: "Olive Gray (#5e5d59)"
- Tertiary Text: "Stone Gray (#87867f)"
- Borders (light): "Border Cream (#f0eee6)"
- Dark Surface: "Dark Surface (#30302e)"

### Example Component Prompts
- "Create a hero section on Parchment (#f5f4ed) with a headline at 64px Anthropic Serif weight 500, line-height 1.10. Use Anthropic Near Black (#141413) text. Add a subtitle in Olive Gray (#5e5d59) at 20px Anthropic Sans with 1.60 line-height. Place a Terracotta Brand (#c96442) CTA button with Ivory text, 12px radius."
- "Design a feature card on Ivory (#faf9f5) with a 1px solid Border Cream (#f0eee6) border and comfortably rounded corners (8px). Title in Anthropic Serif at 25px weight 500, description in Olive Gray (#5e5d59) at 16px Anthropic Sans. Add a whisper shadow (rgba(0,0,0,0.05) 0px 4px 24px)."
- "Build a dark section on Anthropic Near Black (#141413) with Ivory (#faf9f5) headline text in Anthropic Serif at 52px weight 500. Use Warm Silver (#b0aea5) for body text. Borders in Dark Surface (#30302e)."
- "Create a button in Warm Sand (#e8e6dc) with Charcoal Warm (#4d4c48) text, 8px radius, and a ring shadow (0px 0px 0px 1px #d1cfc5). Padding: 0px 12px 0px 8px."
- "Design a model comparison grid with three cards on Ivory surfaces. Each card gets a Border Warm (#e8e6dc) top border, model name in Anthropic Serif at 25px, and description in Olive Gray at 15px Anthropic Sans."

### Iteration Guide
1. Focus on ONE component at a time
2. Reference specific color names — "use Olive Gray (#5e5d59)" not "make it gray"
3. Always specify warm-toned variants — no cool grays
4. Describe serif vs sans usage explicitly — "Anthropic Serif for the heading, Anthropic Sans for the label"
5. For shadows, use "ring shadow (0px 0px 0px 1px)" or "whisper shadow" — never generic "drop shadow"
6. Specify the warm background — "on Parchment (#f5f4ed)" or "on Near Black (#141413)"
7. Keep illustrations organic and conceptual — describe "hand-drawn-feeling" style

---

# 10. HAIQU ERP 正式设计规则：全局控件、反馈与列表布局

> 状态：本轮基础项和 10 批共 50 项均已确认，并于 2026-09-30 批准写入。后续新增或修改页面按本章执行；不要求在此次文档更新中批量改造旧代码。
>
> 适用范围：全局控件、颜色、页面边距、滚动、弹层、反馈及媒体导航规则适用于 ERP 全部页面。10.3—10.10 的列表结构适用于客户、联系人、产品、样品、订单、采购、库存、生产任务等数据列表页。
>
> 表单页、详情页、工作台、看板和报表页的专有布局按各自已确认原型，不机械套用列表结构；共享控件和全局规则仍按本章执行。
>
> 优先级：用户最新明确确认高于旧原型、旧规范和旧代码；页面特有的已确认原型用于业务布局和明确批准的例外，其余共享规则以本章为准。本章高于第 1—9 章历史参考。发现差异先说明来源和影响，不从当前代码自行提取为新规范。

## 10.0 ERP 全局控件高度

- 所有按钮高度统一为 `32px`，包括主按钮、次要按钮、文字按钮、图标按钮、弹窗按钮、抽屉按钮、表格操作按钮和分页按钮。
- 图标按钮的基准尺寸为 `32 × 32px`；带文字按钮的宽度由文字、图标和水平内边距共同决定。
- 所有单行表单控件高度统一为 `32px`，包括 Input、Select、DatePicker、TimePicker、Cascader、TreeSelect、Autocomplete 和 InputNumber。
- 筛选区和工具栏内的按钮、输入框、选择器及其他单行操作控件高度统一为 `32px`。
- 多行文本域、富文本编辑器、上传拖拽区、图片选择区等内容型控件不固定为 `32px`，高度由对应页面原型和内容需求决定；其内部操作按钮仍为 `32px`。
- Tag 保持本章 `10.11` 规定的 `24px` 高度，不属于按钮或表单输入控件。
- 本节是 ERP 全局规则，高于前文通用组件示例以及旧页面中已有的 `36px`、`38px` 控件高度。后续新增页面和后续被修改页面必须执行；本次规范更新不要求立即批量重构未涉及的旧页面。

## 10.1 设计与验收基准

- 正式设计、开发和视觉验收统一使用 `1920 × 1080` 桌面端视口。
- 页面存在已确认的 Figma 节点时，必须读取真实设计数据，不得只根据截图猜测尺寸。
- 不得自行修改原型中的颜色、布局、按钮、圆角、间距、字号、表格密度或元素数量。
- `1440 × 900` 只作为兼容性检查：使用 `64px` 折叠侧栏、同样只计算一次的 `14px` 内容边距和表格内部横向滚动，不作为独立的像素级设计基准，除非另有已确认原型。

## 10.2 全局页面壳层

- 展开侧栏宽度：`230px`。
- 折叠侧栏宽度：`64px`。
- 顶部导航栏高度：`64px`。
- 页面外层上下左右内边距统一为 `14px`，由 `PageContainer` 单独负责；页面根节点不得重复叠加。此值覆盖旧版左右 `28px`、顶部 `26px`、底部 `18px` 和兼容窗口 `24px` 的边距。打印页面按打印规则可为零。
- 页面背景：`#f6f3ec`；主要内容表面：`#fcfbf7`。
- 页面本身不得出现横向滚动；超宽表格只能在表格容器内部滚动。
- Header、Sidebar、内容区必须分别布局，禁止通过整体缩放适配不同分辨率。

### 10.2.1 左侧菜单栏

- 品牌统一使用 `HiTree` 艺术字，不显示额外的 `ERP · CRM` 副标题。
- 菜单背景：`#1c1c1a`。
- 一级菜单高度：`44px`；二级菜单高度：`40px`。
- 一级菜单和二级菜单均使用统一的 IconPark 图标体系，尺寸和描边风格保持一致。
- 当前二级菜单使用近白色背景，并在左侧显示 `4px` 品牌色指示条。
- 同一时间只展开当前业务分组；菜单内容超高时由侧栏内部滚动。
- “系统配置”固定在菜单底部区域。
- 全量更新菜单视觉时，必须保留原有权限过滤、路由地址、展开逻辑和滚动能力。

### 10.2.2 页面高度与纵向滚动（全部页面）

- 浏览器窗口和 ERP 外层布局以可视区域为边界。页面实际内容（含上下内边距）未超过内容区可用高度时，不得因固定高度、`min-height`、重复内边距或占位区域产生纵向滚动条。
- 页面确需按视口计算高度时，必须扣除实际顶部导航高度、外层容器上下内边距及页内外边距；不同页面壳层不得复用未经核对的 `100vh - 固定值`。能使用弹性布局和 `min-height: 0` 时优先使用。
- 内容确实超出可用高度时，必须有明确的纵向滚动容器，且能滚到最后一个内容和操作按钮；不得用 `overflow: hidden` 截断内容。表单、详情、设置、工作台等页面优先由主内容区滚动。
- 需要固定标题、工具栏或分页的列表页，可让表格内容区独立滚动；分页和底部操作始终可见。表格内部滚动时，浏览器窗口及页面主内容区不应同时滚动。
- 页面不得同时出现无必要的父子两层纵向滚动。侧栏菜单和弹窗按各自独立滚动规则处理。
- 验收时分别检查内容较少和内容超出两种状态，并在 `1920 × 1080` 及窄窗口验证：前者不出现空白滚动，后者能实际滚到最末内容，而不是只看有没有滚动条。

## 10.3 列表页固定结构

列表页自上而下统一按照以下顺序组织：

1. 页面标题、数据总数和页面级操作。
2. 快捷统计条（仅在存在真实统计接口时显示）。
3. 常用筛选区。
4. 批量操作与表格工具栏。
5. 数据表格。
6. 分页区。

快捷统计不是所有列表页的必需模块。没有真实统计数据时应直接省略，并收紧后续区域位置，不得显示伪造数字或空白占位条。

## 10.4 垂直节奏

### 10.4.1 含快捷统计条

- 标题操作区高度：`46px`。
- 标题操作区到快捷统计条：`4px`。
- 快捷统计条高度：`46px`。
- 快捷统计条到筛选区：`17px`。
- 筛选控件高度：`32px`。
- 筛选区底部到操作工具栏顶部：`10px`。
- 工具栏容器高度：`32px`；内部控件高度：`32px`。
- 操作工具栏底部到数据表格顶部：`14px`。

### 10.4.2 不含快捷统计条

- 标题操作区到筛选区：`17px`。
- 筛选区、工具栏和表格之间的其余间距沿用上一节。

以上为当前确认的紧凑布局。旧版本中“筛选区到操作栏约 27px”的规则已废止，不得恢复。

## 10.5 标题和页面级操作

- ERP 页面外层内边距统一为 `14px`，由 `PageContainer` 集中管理；页面根节点不得再次叠加外层内边距。打印页面可按打印规则使用零内边距。
- 页面标题使用 `Noto Serif SC`，字号 `34px`、行高 `44px`，保持高识别度但不额外放大。
- 数据总数紧邻标题显示，不单独制作统计卡片；使用真实结果，未取得总数不能编造为 `0`。
- 页面级操作放在标题区域右侧，包括导入、导出、新建等操作。
- 次要页面按钮参考尺寸：`110 × 32px`。
- 主要页面按钮参考尺寸：`140 × 32px`。上述宽度为参考；长文案按内容扩展，不强行截断或固定所有页面宽度。
- 按钮圆角：`5px`；图标尺寸：`16px`；图标与文字间距：`8px`。
- 同一标题区最多保留一个高强调主按钮。
- “新建”属于页面级操作，不得放入表格工具栏。

## 10.6 快捷统计条

- 使用高度 `46px` 的整行平铺结构，不使用独立卡片、阴影或图标卡片。
- 每一项水平、垂直居中。
- 指标标题字号：`13px`；数字字号：`12px`。
- 当前项底部使用 `4px` 品牌色指示线。可交互指标使用 `46px` 外层单元格和 `32px` 内部按钮，名称和数值同行并预留指示线；纯展示指标保留文字，不强加按钮。
- 指标必须来自真实汇总接口，禁止使用当前页数据临时推算全部统计。
- 指标数量、语义、宽度、是否可点及点击后筛选或跳转由具体页面确认；客户列表的统计项不能直接复制到其他业务列表。没有统计接口则省略整条及其空隙，加载、失败、无权限不能伪装为真实 `0`。

## 10.7 筛选区

- 所有输入框、选择器和筛选按钮高度统一为 `32px`。
- 同一行控件间距：`14px`。
- 所有搜索框最大宽度为 `250px`，窄窗口可更窄；此上限覆盖旧版 `410px` 参考宽度，也适用于其他区域的搜索框。其他常用参考宽度：主状态 `160px`、分类/等级 `142px`、第三筛选项 `176px`、更多筛选 `130px`，不强套至所有模块。
- 首行最多展示“搜索 + 3 个高频筛选 + 更多筛选”；低频条件统一放入“更多筛选”。
- 搜索框按 Enter 执行查询；常用 Select 选择或清空后立即查询，页面有特殊业务流程时以已确认交互为准。
- “更多筛选”应保留应用和重置能力，并继续承载页面已有的低频条件。
- 控件圆角：`5px`；键盘焦点色：`#3898ec`。
- 筛选字段必须来自当前业务的数据模型，不得为了套用布局复制客户页面的字段。

## 10.8 批量操作与工具栏

- 工具栏容器高度：`32px`；工具栏内所有按钮、输入框和选择器高度统一为 `32px`。
- 左侧放置已选数量和批量操作；右侧放置排序、列设置、保存视图和刷新。
- 刷新按钮固定放在工具栏最右侧，并使用完整按钮外观。
- 列表页不显示“密度”按钮，表格默认且固定使用超紧凑密度。
- 当前页面不支持的操作应直接省略，不得保留空白按钮或占位。
- 未选择数据时，批量操作按钮保持可见但处于禁用状态。
- 页面级“新建”按钮不得重复出现在工具栏。

## 10.9 数据表格（默认超紧凑）

- 表格宽度：`100%`。
- 表头高度：`44px`。
- 默认数据行高度：`34px`，单行显示；不自动拼成“主字段 + 次字段”双行。旧版 `40px` 双行及 `52px` 行高均不是默认值，列名和顺序仍按页面已确认原型。
- 单元格水平内边距：`16px`。
- Checkbox 视觉尺寸：`14px`。
- 表格外层圆角：`5px`；通用列表用 `1px #DDD6C9` 外框和横向分隔线，默认不加竖线；页面已确认网格例外按其原型。外框由一层绘制，最后一行不叠底边。悬停底 `#FFF6EA`、选中底 `#FFF4E6`，选中再悬停保留选中底；固定列与滚动首末行保持颜色和边界连续。
- 表头文字：`12px / 18px`（字号 / 行高）、字重 `500`，背景 `#F0EADF`、文字 `#6F6A61`；普通单元格：`12px / 18px`、`#4D4C48`；名称等主字段：`13px / 20px`、`#1F1D18`；次要编号或说明：`11px / 16px`、`#6F6A61`；金额：`13px`、字重 `600`；日期：`13px`。
- 双行样式保留，仅在用户明确要求的页面使用：主行 `20px` 加次行 `16px`，共 `36px` 内容；原 `40px` 行高可作为已确认双行例外，不得裁切、重叠或作为全局默认。
- 表格内 Tag 高度保持 `24px`；`14px` 复选框、Tag 和 `32px` 三点操作按钮必须在默认 `34px` 行内垂直居中。复选框内的勾和半选横线也须居中，普通、半选、禁用均需验收。
- `34px` 行内的 `32px` 按钮上下仅余各 `1px`；`2px` 外圈加 `2px` 偏移需要额外显示空间，必须核对首末行及固定列的溢出、层级和焦点留白，不能裁圈、改内圈、缩按钮或恢复更高默认行。
- 表头、普通文字、次要信息和占位符必须分别使用对应文字色，不得全部使用纯黑或浏览器默认色。
- 每一列必须显式设置宽度，禁止浏览器自动平均分配列宽。
- Checkbox 列建议宽度：`50px`，可固定在左侧。
- 名称/编号列默认不固定；只有明确业务需求和原型依据时才允许固定。
- 操作列建议宽度：`80px`，固定在右侧。
- 三点操作图标使用居中的 `16px` SVG：水平排列 3 个直径 `2px` 的圆点，净间距 `3px`；按钮 `32 × 32px`，不使用字符或手调位移。
- 超长文字使用省略号，并通过 Tooltip 提供完整内容。
- 表体允许垂直滚动，但分页区必须始终保留在表格容器底部。
- 列较多时使用表格内部横向滚动，不压缩已确认列宽，不产生整页横向滚动。
- 具体列名、顺序和宽度属于页面级业务规则，应按对应 Figma 原型单独定义，不能把客户表格列宽作为所有页面的通用值。
- 客户列表与询盘列表是原列表结构的首批确认页面；其他新增或后续被修改的数据列表页应执行最新规则。未涉及的页面不在本次文档更新中批量重构；如业务内容无法在 `34px` 单行内无损展示，须单独确认双行或其他例外，不得自行增高。

## 10.10 分页区

- 分页区容器高度：`48px`，内部控件高度统一为 `32px`，上下各保留约 `8px` 间距，不保留大面积空白。
- 左侧显示总数量；右侧依次显示每页数量、上一页、页码和下一页。
- 高密度列表默认：`50 条/页`；如业务量明显较小，可由页面需求另行确认。
- 每页数量选择器参考尺寸：`136 × 32px`。
- 页码、上一页和下一页按钮参考尺寸：`38 × 32px`。
- 分页控件间距：`10px`。
- 当前页使用 `#FFF4E6` 浅底、`#C84E28` 文字和 `1px` 品牌橙边框，悬停保持当前页状态；其他页沿用普通按钮，首页的上一页和末页的下一页禁用。
- 分页必须继续调用真实列表接口，不能只在前端截取当前数据。

## 10.11 ERP 共享视觉变量与标签

### 颜色

- 页面背景：`#f6f3ec`。
- 内容表面：`#fcfbf7`。
- 次级表面及只读底：`#F0EADF`。
- 禁用底：`#E8E1D5`，不整框叠透明度。
- Hover 行：`#fff6ea`。
- 选中行：`#fff4e6`。
- 主文字：`#1f1d18`。
- 常规文字：`#4d4c48`。
- 次要文字：`#6f6a61`。
- 弱化文字：`#968f84`。
- 普通边框：`1px #DDD6C9`；较强边框：`#C9C0B2`。
- 品牌按钮主色：`#C84E28`；默认 Tag 的 Brand 色仍为 `#C96442`，两者用途不同，不自动互换。
- 深底反白文字：`#FAF9F5`。
- 键盘焦点色：`#3898ec`。

### 字体、间距和圆角

- 页面标题：`Noto Serif SC`。
- 界面文字和数据：`Noto Sans SC`。
- 常用间距刻度：`4 / 8 / 12 / 16 / 24 / 28px`。
- 按钮、输入框、选择器、表格和分页的默认圆角：`5px`。

### Tag

- 所有表示状态、类型或属性的 Tag，沿用 Figma `00C2_标签` → `Warm ERP/Tag` 右侧 `Emphasis=Strong` 的形态，并纳入本轮已确认扩展颜色；不使用 `Soft` 形态，不改为深色文字。扩展组获得批准不表示 Figma 或代码已同步。
- 两字标签的基准尺寸为 `56 × 24px`；较长文本按内容扩展，最小宽度为 `56px`。
- 水平内边距为 `8px`，文字水平、垂直居中。
- 圆角为 `999px`，不显示边框。
- 字体为 `Noto Sans SC Medium`，字号 `12px`，行高 `18px`，字重 `500`。
- 文字统一使用反白色 Token `color/text/inverse`，当前值为 `#FAF9F5`。
- 默认组保留以下六种语义颜色：
  - Brand：`color/status/brand`，`#C96442`。
  - Info：`color/status/info`，`#3898EC`。
  - Success：`color/status/success`，`#4F7D4B`。
  - Warning：`color/status/warning`，`#B8781E`。
  - Danger：`color/status/danger`，`#B53333`。
  - Neutral：`color/status/neutral`，`#5E5D59`。
- 扩展组保留用户提供的六个 RGB 原值：

  | 扩展色 | RGB | 十六进制 |
  | --- | --- | --- |
  | 1 | rgb(235, 80, 80) | #EB5050 |
  | 2 | rgb(240, 168, 0) | #F0A800 |
  | 3 | rgb(70, 194, 111) | #46C26F |
  | 4 | rgb(0, 174, 209) | #00AED1 |
  | 5 | rgb(250, 129, 24) | #FA8118 |
  | 6 | rgb(240, 67, 125) | #F0437D |

- 两组高度、最小宽度、内边距、圆角、字体和 `#FAF9F5` 反白文字一致；使用哪组由用户在使用时选择。扩展颜色不按色相自动绑定业务状态，不自动全局替换。
- 后续新增或被修改页面的 Tag 必须遵循本规范；本轮不批量重构现有页面。
- Badge、通知圆点、按钮和提示框不属于 Tag，不应用本规则。

## 10.12 页面状态与真实数据

每个列表页至少需要覆盖以下状态：

- 正常数据。
- 首次加载。
- 空数据。
- 筛选无结果。
- 接口错误和重试。
- 无权限。
- 行悬停和行选中。
- 批量按钮禁用与启用。
- 键盘焦点。
- 分页切换。
- 表格横向滚动。

空数据和无结果状态必须说明原因并给出下一步操作；错误状态必须提供重试入口。

- 页面只能展示真实 API 数据，不得为了贴近原型示例引入 Mock 或硬编码业务数据。
- 接口缺失字段统一显示 `—`，不得自行推断风险、状态、金额或日期。
- 修改列表视觉时不得破坏 API、Router、Permission、数据结构、查询、筛选、分页、保存视图、批量操作和详情跳转。

## 10.13 修改流程与完成门禁

### 修改前

1. 阅读项目 `AGENTS.md`、本文件和当前页面对应的已确认 Figma 原型。
2. 检查 Git 状态和现有未提交改动，只修改本任务必需文件。
3. 检查设计变量、SCSS 变量和已封装的 Button、Input、Select、Checkbox、Tag、IconButton、Table、Pagination 等基础组件。
4. 检查当前列表页代码、API、类型、路由、权限和测试，确认哪些功能必须保留。
5. 区分共享规则与页面专有布局；只有列表页套用 10.3—10.10 列表结构，表单、详情、看板等沿用各自确认布局，共享控件仍遵守本章。

### 实施中

- 页面已有原型时先更新并确认原型，再修改前端页面。
- 样式统一使用 SCSS / Sass，不为单个页面新增普通 CSS。
- 优先复用设计变量、SCSS mixin 和现有基础组件，避免重复开发。
- 不为组件化而过度拆分，不全局重构，不批量格式化无关文件。
- 页面业务语义、字段和操作必须来自真实需求，不能机械复制客户列表。

### 完成前

1. 执行 TypeScript 类型检查。
2. 执行相关组件和页面测试。
3. 执行生产构建。
4. 在真实浏览器以 `1920 × 1080` 截图，逐项核对 Sidebar、Header、标题、按钮、筛选、间距、表格、列宽、字体、颜色、分页和页面溢出。
5. 检查所有按钮、单行表单控件、筛选区控件、工具栏控件和分页控件的实际渲染高度是否为 `32px`。
6. 页面要求兼容 1440 时，再以 `1440 × 900` 检查折叠侧栏、内容边距和表格内部横向滚动。
7. 检查加载、空数据、错误、无权限、选中、悬停、焦点、禁用、分页和横向滚动状态。
8. 已知的无关测试失败应单独报告，不得为了让全量检查通过而修改任务范围外的模块。

只有在代码检查、业务功能和真实浏览器视觉验证均通过后，才可以宣布完成。项目能编译不等于列表页已经完成。

## 10.14 通用业务弹窗组件

- 后续新增或修改的表单、详情、配置、预览和业务处理弹窗统一使用 `AppWindowDialog`，不得继续直接使用 `ElDialog`。
- 组件必须支持拖动、右下角调整大小、最小化、最大化、恢复和关闭，并在浏览器尺寸变化后把窗口限制在可视区域内。
- 弹窗初始宽度和高度由调用页面根据业务内容显式传入；组件最小尺寸默认为 `360 × 180px`，距视口四周至少保留 `16px` 安全边距。
- 当完整内容能够放入浏览器可视区域时，调用页面应优先增大弹窗初始尺寸以完整展示内容，不得因沿用偏小的默认高度制造无必要的滚动条；只有内容确实超出可视区域或用户主动缩小窗口时，才允许内容区内部滚动。
- `.el-dialog.app-window-dialog` 根节点 `padding` 固定为 `0`；标题栏高度为 `44px`，内容区和底部操作区分别管理自己的间距与滚动，不依赖根节点内边距。
- `.app-window-dialog__actions` 绝对定位于窗口右上角，使用 `top: 0; right: 0; width: 96px; height: 32px`；最小化、最大化、关闭按钮均为 `32 × 32px`，图标为 `16 × 16px` 并在按钮内水平、垂直居中。
- 标题栏右侧必须为三个窗口控制按钮预留至少 `104px`，标题过长时使用省略号，不得与控制按钮重叠。
- 弹窗内容超过调用高度时，只允许内容区内部滚动；标题栏和底部操作按钮保持可见。
- 提交过程中可以通过 `showClose`、`closeOnClickModal` 和 `closeOnPressEscape` 阻止误关闭，但不得破坏最小化、最大化和视口自适应能力。
- 仅包含一句提示和确认/取消操作、且不承载表单或业务详情的系统级确认，可继续使用 `ElMessageBox`；其余业务弹窗必须使用 `AppWindowDialog`。
- 外圆角 `5px`、`1px #DDD6C9` 边、表面 `#FCFBF7`；标题 `16px / 22px`、字重 `600`；内容内边距 `16px`；底部上下 `12px`、左右 `24px`，按钮间距 `10px`。
- 蒙层为 `34%` 深色；窗口内按钮保留 `2px #3898EC` 外焦点圈和 `2px` 偏移，不被外框裁切。处于活动且未最小化的模态窗口约束 Tab 焦点；关闭后恢复触发位置。Esc、蒙层关闭及未保存保护按页面原规则，不擅自放开。

## 10.15 按钮、图标与通用焦点

- 按钮与单行控件高 32px，通用圆角 5px；品牌按钮、普通浅底、暖沙次按钮、危险实心和文字按钮按任务强调程度选用。不能仅凭按钮名称强绑配色，同一区域避免多个高强调主按钮。
- 按下态只在按住时生效；松手仍停留恢复悬停，移开恢复默认。持续选中是独立状态，不借用按下色。

| 类型 | 默认背景 / 边框 | 悬停背景 / 边框 | 按下背景 / 边框 | 文字 |
| --- | --- | --- | --- | --- |
| 品牌主按钮 | #C84E28 / 同背景 | #B94320 / 同背景 | #9F351A / 同背景 | #FAF9F5 |
| 普通浅底 | #FCFBF7 / #DDD6C9 | #F0EADF / #C9C0B2 | #E8E1D5 / #C9C0B2 | #1F1D18 |
| 暖沙次按钮 | #E8E6DC / #DDD6C9 | #DEDCD1 / #DEDCD1 | #D1CFC5 / #D1CFC5 | #4D4C48 |
| 危险实心 | #B53333 / 同背景 | #9F2D2D / 同背景 | #862626 / 同背景 | #FAF9F5 |
| 文字按钮 | 透明 / 无可见边框 | 透明 / 无可见边框 | 透明 / 无可见边框 | #C84E28 → #B94320 → #9F351A |

- 有边框按钮均为 1px 边。危险实心用于需强提醒的破坏性动作，不任意为普通动作加红。文字按钮悬停、按下有下划线，禁用后无下划线、保持透明底。
- 有边框按钮禁用统一底 #E8E1D5、字 #6F6A61、边 #DDD6C9；文字按钮禁用仅灰字。透明度保持 1，不响应悬停/按下、点击/键盘操作，Tab 跳过；原因就近可见，不能仅依赖禁用控件悬停。
- 键盘焦点为 2px #3898EC 外圈、偏移 2px；保留外侧空间，不能被裁切。普通输入框聚焦用 1px 蓝边；错误输入框保留红边并加此蓝外圈。
- 图标按钮 32 × 32px、SVG 16 × 16px，整体与图形都水平垂直居中；三点参数见 10.9。按钮有可读名称，悬停/聚焦显示名称气泡，禁用原因仍在旁边说明。
- 加载按钮保持所属类型的默认配色、原宽高，显示转圈和“处理中…”，停止悬停/按下变色并保留当前焦点。拦住重复点击、Enter、Space 及表单提交入口；结束依据真实请求结果。加载不等同普通禁用，审核小样的 2 秒和 140px 宽度不是全局规则。

## 10.16 文本输入、只读禁用与悬浮提示

| 状态 | 背景 | 文字 | 普通边框 | 交互 |
| --- | --- | --- | --- | --- |
| 可编辑 | #FCFBF7 | #1F1D18 | 1px #DDD6C9 | 可修改；焦点边 #3898EC |
| 只读 | #F0EADF | #4D4C48 | 1px #DDD6C9 | 可聚焦、选取复制；不可修改，焦点蓝边且底不变 |
| 禁用 | #E8E1D5 | #6F6A61 | 1px #DDD6C9 | 不可操作，不响应悬停/按下/点击焦点，Tab 跳过 |

- 单行输入高 32px、圆角 5px；悬停不加粗、不叠第二圈边。只读标签明确“只读”，禁用鼠标表示不可操作、原因就近说明，不整框减透明度。文本域沿用上述状态；选择器按 10.17 专门实现，只读不能机械套原生 select 的 readonly。
- 错误输入保持 #FCFBF7 正常表面，用 1px #B53333 红边和错误图标；聚焦仍红边，并加 2px #3898EC 外圈、偏移 2px。
- 字段错误和普通说明使用脱离文档流的悬浮气泡，不增加说明行、不挤下方内容。共同参数：表面 #FCFBF7、圆角 5px、文字 12px / 18px，上下内边距 8px、左右 12px，最大宽 300px 且受视口约束。普通说明为 #1F1D18 字和 1px #DDD6C9 边；错误为 #B53333 字和 1px 红边。
- 鼠标移入、聚焦或点击图标可显示；同一时刻只显示一个，允许移入气泡阅读。支持 Esc 和外部点击关闭，Esc 后不得因仍悬停/聚焦立即重开；需新的主动触发。按视口翻转、滚动重定位，避免被容器截断。重要业务规则须持续可见，不仅放在气泡中。
- 必填星号 #B53333 放标签前，标签仍正常文字色，并解释“带 * 的字段为必填”。初始空白不自动全部变红，实际校验失败再显示错误。哪些字段必填、何时校验按模块既有确认。
- 占位文字 #968F84，只放简短示例；输入后的实际内容为 #1F1D18，字段标签持续保留。单位、格式限制和重要操作要求不能仅放占位提示。

## 10.17 选择与高级表单控件

### 下拉与选项

- 输入区 32px / 圆角 5px，底 #FCFBF7、1px #DDD6C9 边、字 #1F1D18、箭头 #6F6A61；聚焦蓝边，悬停不加粗。只读用 #F0EADF / #4D4C48，只展示值、可聚焦复制、不展开/清空；禁用用 #E8E1D5 / #6F6A61、不展开且 Tab 跳过。
- 面板底 #FCFBF7、1px #DDD6C9 边、圆角 5px；选项高 32px，列表区最高 240px，超出内部滚动。至少与触发控件同宽，长文本可增宽但不超视口；浮层不推动正文，优先向下、空间不足向上或限高，避免被祖先容器裁切。
- 普通选项字 #1F1D18；悬停/键盘活动底 #FFF6EA，选中底 #FFF4E6、#C84E28 字和勾，选中再悬停保留选中底。禁用字 #6F6A61、底不变、无悬停/选择，补“不可选”或具体原因。
- ↑↓移动活动项、跳过禁用，不立即改值；Enter 确认并关闭，Esc/Tab 关闭。单选面板与多选面板的提交方式不同，按下节执行。

### 单选与复选

- 单选视觉 14 × 14px、圆形；未选底 #FCFBF7 / 边 #DDD6C9；选中 #C84E28 边加 6px 品牌橙圆点。标签字 #1F1D18，操作区至少高 32px，可点击文字；悬停仅改品牌橙边，焦点沿用蓝外圈。组内只选一个，同组方向键换选。
- 复选视觉 14 × 14px、圆角 2px；未选底 #FCFBF7 / 边 #DDD6C9；勾选和半选底/边 #C84E28，勾/横线 #FAF9F5。悬停、焦点及标签操作区沿用单选，Space 切换；半选表示子项未全选，不新增业务值。
- 两者禁用为 #E8E1D5 底 / #DDD6C9 边 / #6F6A61 字及圆点、勾、横线，保留原状态、不可改、无悬停变化、Tab 跳过；原因就近显示。复选框方框在操作区/34px 行中居中，勾和半选横线在 14px 画布内居中，普通/半选/禁用逐态验收。

### 多选、日期、数字与文本域

- 多选输入区保持 32px / 5px，选 1 项显示名称，多项显示“已选 N 项”，不叠标签撑高；展开查看完整名称逐项勾选，选项 32px、复选框 14px / 2px 且居中。沿用选项颜色；↑↓移活动项，Space 勾选并保持面板，Enter 完成关闭，Esc/Tab 关闭。只读展示完整值可复制、不展开/删除；禁用不操作，不由此新增 Tag 配色。
- 日期输入区沿用 32px / 5px、暖灰边和蓝焦点。日历格 32 × 32px，悬停 #FFF6EA，选中品牌橙底 / #FAF9F5 字，今天为橙色描边；禁用灰底灰字不可点。日历面板为表面底、1px 暖灰边、5px 圆角，按视口上下避让；只读可复制但不展开，禁用不聚焦。日期格式、范围和时区按模块。
- 数字输入整体高 32px，左减、右加各 32 × 32px，数字居中、单一描边和蓝焦点；到业务边界时仅对应方向禁用。只读可复制、隐藏加减、不可修改；禁用灰底灰字不可操作。负数、小数位、上下限、步长由业务指定，审核样例 0—9 不是规则；不采用上下各 16px 的拆分按钮。
- 多行文本域不强制 32px；常规备注参考 3 行、文字 13px / 20px、上下内边距 8px / 左右 10px，示例总高 78px，仅作参考。实际高度及是否允许拖高按页面；内容超出内部滚动，不持续撑高。底、1px 边、5px 圆角、只读/禁用/焦点/错误气泡沿用输入规则，字数上限、计数器和必填按业务。

## 10.18 抽屉、操作菜单、页签与折叠区

- 抽屉从右侧展开，底 #FCFBF7、1px 暖灰边、左侧圆角 5px、右侧贴边；标题栏 44px、标题 16px / 22px、关闭按钮 32px 且留外焦点空间，内容内边距 16px，底部按钮 32px。标题/底部固定，仅内容滚动；宽度按页面且不超视口；已有拖宽能力继续保留，是否提供拖宽按页面要求，提供时焦点为 #3898EC，关闭恢复触发位置。Esc、蒙层、未保存保护按页面；示例宽 520px 和页脚 56px 不作为全局固定值。
- 操作菜单与侧栏导航分开：每项高 32px、文字 13px，底 #FCFBF7、1px #DDD6C9 边、5px 圆角；悬停 #FFF6EA、危险文字 #B53333、禁用灰字且原因就近可见。↑↓移动、Enter 执行实际允许操作、Esc 关闭返回触发按钮、Tab 关闭并离开；浮层避让视口，不推正文。权限、显示项和确认步骤按原业务。
- 页签高 32px、文字 13px / 20px；默认 #6F6A61、选中 #C84E28 / 字重 600 / 2px 底部标记，悬停暖灰底。左右键只移焦点，Enter/Space 激活，禁用跳过，组内一个 Tab 入口；名称单行，超宽在自身区域滚动，聚焦时滚入可见位置并留至少 4px 外圈空间。切换是否保存编辑按页面。
- 折叠区标题高 32px、文字 13px、箭头 16px；普通深字/暖灰悬停，展开箭头转 90°并用品牌橙，外角 5px、1px 暖灰边、内容内边距 12px。Enter/Space 展开收起，保留已填内容，默认可多区同时展开；需单开、跨页记忆或加载数据按页面确认。侧栏仍按 10.2.1 只展开当前业务分组，不套多开规则。

## 10.19 开关与状态反馈

### 开关

- 操作区 52 × 32px；轨道 40 × 20px 在操作区居中，圆角 999px；圆点 16px，在轨道内上下居中、两端各 2px 间距，圆点 #FAF9F5。旁边以“开启/关闭”表达状态。
- 开启底 #C84E28 → #B94320 → #9F351A；关闭底 #5E5D59 → #4D4C48 → #1F1D18，依次为默认/悬停/按下。焦点为 2px 蓝外圈、偏移 2px。
- 禁用轨道 #E8E1D5、边 #DDD6C9、圆点 #6F6A61，保持原位置、无悬停/操作，原因就近显示；只读用可复制状态文字。Space/Enter 切换，字段含义、默认值、保存方式按业务。

### 空状态与加载

- 分清暂无记录、筛选无结果、加载失败、无权限：图标 32px、标题 13px / 20px / 字重 500，说明 12px / 18px / #6F6A61，间距 8px、内边距 16px、暖色表面、5px 圆角。图文居中，高度按可用空间；示例 168px 不是全局高度。
- 暂无记录的下一步按业务；无结果可清除筛选；错误可重试；无权限说明限制，恢复入口必须已有权限依据。按钮 32px，不造不存在的操作或空白滚动。
- 品牌加载图形保留 42 × 42px 容器、12px 圆角、#F8EDE8 底，品牌橙三柱宽 4px、参考高 13/18/13px、1.1 秒起伏；此图形不是操作按钮。
- 首次加载可用骨架：#F0EADF 底、#FCFBF7 亮部、5px 圆角、列表行 34px。同一数据集合刷新保留上次结果、明确标注旧结果，加局部 82% 表面色遮罩；只阻止受影响区域重复操作，其他区域继续可用。区域标记 aria-busy，真实请求结束才退出；失败进入错误/重试，不能转成无数据。减少动画时用静态图形与文字。

### 短消息与持续提示条

- 短消息悬浮于顶部居中、距顶 80px；区域宽 480px、最大为视口减 32px，各条填满。表面 #FCFBF7、1px 暖灰边、5px 圆角，上下 8px / 左右 12px；文字 13px / 20px、图标 16px、关闭按钮 32px、最小高 50px，长文换行。多条间距 8px、同内容合并；区域超高内部滚动，不推正文、不抢焦点。
- 信息/成功/警告/错误有不同名称和图标，强调色分别 #3898EC / #4F7D4B / #B8781E / #B53333。普通信息/成功默认 5 秒关闭，悬停/聚焦暂停；警告/错误默认手动关闭，页面特例须已确认。普通提示以 status 播报，警告/错误以 alert 播报；关闭时焦点仍位于消息内部才恢复触发位置，自动关闭不改变当前焦点。成功须来自真实结果。
- 行内提示条背景：信息 #E6F3FD、成功 #E8F0E2、警告 #FAEEDB、错误 #F6E4E1；1px 暖灰边、5px 圆角、内边距 12px、图标 16px、正文 13px / 20px、标题字重 500，高度随内容。强调色同短消息，正文保持暖深色。
- 行内提示占正文空间，仅用于持续可见的规则；字段错误/普通说明仍用气泡。只有非关键说明可关闭，关闭按钮 32px；不能擅自让重要规则或影响操作的错误消失。是否附加操作按页面要求。

## 10.20 上传、图片与导航状态图形

### 上传及附件

- 上传区 #F6F3EC 底、1px #DDD6C9 虚线、5px 圆角、内边距 16px，图标 32px、标题 13px / 20px、说明 12px / 18px；悬停边 #C9C0B2，拖入品牌橙边 / #FFF4E6 底。高度按内容，内部按钮 32px。
- 附件卡参考最小高 52px、上下 8px / 左右 10px、圆角 5px；文件图块 32px / 图标 16px；文件名 12px / 18px，大小/状态 11px / 16px；长名省略并用悬浮气泡展示完整。列表参考上限 240px，内容多时内部滚动，实际高度按页面确认。
- 禁用底 #E8E1D5、不选择/拖入，原因就近说明；只读隐藏选择和移除入口，保留文件及状态，查看/下载按权限。类型、大小、数量、扫描处理和删除规则按业务；本地选中、上传中、传输结束、处理、业务完成和失败按真实状态区分，不把本地选中写成已上传。

### 图片与预览

- 产品/业务图默认 contain 等比例完整展示，不裁边；默认单行表格的缩略操作框 32 × 32px、1px 暖灰边 / 1px 内边距 / 图像 28 × 28px、表面底、外角 5px，在 34px 行内居中。详情大图按原型，只有页面明确要求才裁切。
- 无图与加载失败分别显示图标/文字；可预览时支持 Enter/Space 和蓝外圈，不裁焦点。预览用 10.14 的 AppWindowDialog，内容 16px、舞台 #FCFBF7，图像保持比例；关闭回到触发位置，下载/切换按权限和需求。

### 面包屑、步骤与进度

- 面包屑文字 13px / 20px，斜杠分隔、间距 6px；前级 #4D4C48，悬停 #C84E28 加下划线，按下 #9F351A；当前项 #1F1D18 / 字重 500，分隔 #968F84。可点击项操作区高 32px，焦点 2px 蓝外圈、偏移 2px。
- 当前项默认静态；已有 currentClickable/currentClick 配置及行为保留，不能擅改成当前路由跳转。前级有真实路由才作链接；单行超宽在自身区域滚动，聚焦滚入可见并留至少 4px 外圈空间。
- 步骤圆圈 28px、连接线 2px、普通边 #DDD6C9、未开始灰字；完成品牌橙底 / #FAF9F5 的 16px SVG 勾；当前橙边/橙数字、名称深色 / 字重 600；失败 #B53333 边和 16px 叉号，附失败文字。名称 13px / 20px、圈与名间距 8px，连接线按可用宽度计算。它是状态图形，默认不可点击跳步，不套 32px 按钮尺寸；业务状态按模块。
- 进度轨道 6px、圆角 999px、底 #E8E1D5；正常填充 #C84E28、明确完成 #4F7D4B、明确失败 #B53333；外侧文字 13px / 20px、间距 8px、完成/失败图标 16px，宽度按容器，不在细条内塞字。
- 有明确百分比才显示数值；未知显示“未知”，不提供数值或 aria-valuenow，不能伪装 0%。传输 100% 仍可待处理，完成色由明确业务结果决定；计算、超 100%、精度、取整和缺值按模块，不以视觉逻辑替代业务。

## 10.21 来源、维护与实施差异

- 正式规则仅在本文件维护；README 只提供导航。[已确认汇总](qa/design_knowledge_review_20260929/confirmed_design_summary.html)按 5 组收录基础项和 50 项，保留每项规则、审核来源及差异。QA 为审核证据，不作为第二套持续维护的正式参数表。
- 确认记录：会话 01a0ed34-45de-76d1-ac48-9e1513726334；基础项与第 1—10 批共 50 项通用规则逐项/逐批确认，最后对 DESIGN.md 与 README.md 的具体写入方案回复“确认”，于 2026-09-30 合并。第 11—15 批均于 2026-09-30 确认，仅登记源码现状、处理决定、范围和页面例外，不登记为已修复；后续由对应开发任务同步并验收。第 12 批全局页面选项卡采用正式字号 13/20px、刷新按钮 1px 暖灰边框、焦点外侧 2px 偏移。第 13 批只针对 CRM v2 侧栏，采用其真实菜单几何；旧默认侧栏值保留为历史差异，焦点沿用正式蓝 #3898EC。第 14 批登记客诉、客户时间线、生产任务详情和仓库入库明细的页面专用结构；按钮继续32px、标签继续24px、搜索继续不超过250px，多行信息区域才保留页面高度例外。第 15 批登记报工记录、报工表单和采购订单详情的双栏工作区、业务卡片、正文滚动、错误气泡和表格密度；报工数量错误目标沿用气泡，采购单行目标遵守正式34px。新设计元素继续提取、展示差异，再按用户要求分批确认后写入；未确认候选不混入正式规则。

| 审核批次 | 内容 | 原审核稿 | 正式规则位置 |
| --- | --- | --- | --- |
| 基础项 | 底色、边框、主/次按钮、只读禁用 | [边框与底色](qa/design_knowledge_review_20260929/warm_gray_border_form_preview.html)、[主按钮](qa/design_knowledge_review_20260929/primary_button_states_review.html)、[暖沙按钮](qa/design_knowledge_review_20260929/secondary_button_states_review.html)、[输入状态](qa/design_knowledge_review_20260929/input_readonly_disabled_review.html) | 10.11、10.15、10.16 |
| 1 | 只读/禁用文字、边框、焦点、交互 | [第 1 批](qa/design_knowledge_review_20260929/input_details_batch5_review.html) | 10.16 |
| 2 | 普通按钮、禁用、错误气泡、必填、占位 | [第 2 批](qa/design_knowledge_review_20260929/buttons_feedback_batch5_review_v2.html) | 10.15、10.16 |
| 3 | 反白、文字/危险/加载按钮、说明气泡 | [第 3 批](qa/design_knowledge_review_20260929/buttons_help_batch3_review.html) | 10.15、10.16 |
| 4 | 下拉、选项、单选、复选 | [第 4 批](qa/design_knowledge_review_20260929/selection_batch4_review_v2.html) | 10.17 |
| 5 | 表头、单行、边框、两组标签、分页 | [表格/标签](qa/design_knowledge_review_20260929/tables_batch5_revision_review_v2.html)、[边框/分页](qa/design_knowledge_review_20260929/tables_batch5_remaining_review.html) | 10.9—10.11 |
| 6 | 图标、多选、日期、数字、文本域 | [第 6 批](qa/design_knowledge_review_20260929/controls_batch6_review.html) | 10.15、10.17 |
| 7 | 窗口、抽屉、操作菜单、页签、折叠 | [第 7 批](qa/design_knowledge_review_20260929/overlays_batch7_review.html) | 10.14、10.18 |
| 8 | 开关、空状态、加载、消息、提示条 | [第 8 批](qa/design_knowledge_review_20260929/feedback_batch8_review.html) | 10.19 |
| 9 | 上传、图片、面包屑、步骤、进度 | [第 9 批](qa/design_knowledge_review_20260929/media_navigation_batch9_review.html) | 10.20 |
| 10 | 壳层、标题、统计、筛选、工具栏 | [第 10 批](qa/design_knowledge_review_20260929/layout_batch10_review.html) | 10.2—10.10 |
| 11 | 源码差异与页面例外核查（不新增通用参数） | [第 11 批差异记录](qa/design_knowledge_review_20260930/design_batch11_source_diff_review.html) | 10.0—10.20（引用）；本节差异登记 |
| 12 | 全局页面选项卡源码差异与导航例外（不新增通用参数） | [第 12 批差异记录](qa/design_knowledge_review_20260930/design_batch12_source_diff_review.html) | 10.2、10.15、10.18（引用）；本节差异登记 |
| 13 | CRM v2 侧栏与导航基础差异（不新增通用参数） | [第 13 批差异记录](qa/design_knowledge_review_20260930/design_batch13_source_diff_review.html) | 10.2、10.13、10.15、10.18（引用）；本节差异登记 |
| 14 | 客诉、客户时间线、生产任务、仓库详情页面例外（不新增通用参数） | [第 14 批差异记录](qa/design_knowledge_review_20260930/design_batch14_source_diff_review.html) | 10.2、10.3、10.4、10.9、10.15、10.18、10.20（引用）；本节差异登记 |
| 15 | 报工与采购详情页面模式（不新增通用参数） | [第 15 批差异记录](qa/design_knowledge_review_20260930/design_batch15_source_diff_review.html) | 10.2、10.4、10.9、10.10、10.15、10.16、10.18、10.19、10.20（引用）；本节差异登记 |

- 核对来源时先读现有 DESIGN.md、确认原型与真实代码；出现不同值须说明“原规范 / 源码现状 / 本次确认值”，不能假定当前实现就是正确设计。主要核对入口：[页面容器](src/frontend/src/layouts/PageContainer.vue)、[控件变量](src/frontend/src/styles/crm/_tokens.scss)、[既有控件样式](src/frontend/src/styles/crm/_sample-controls.scss)、[业务窗口](src/frontend/src/components/common/AppWindowDialog.vue)、[表格工具栏](src/frontend/src/components/common/DataTableToolbar.vue)。
- 第 11 批的 10 项只作为源码同步差异和页面例外记录：沿用本章已有规则，记录当前值、处理边界和待实施风险，不重复追加到 50 项通用规则，也不把“已确认登记”写成“已修复”。详细证据见 [第 11 批差异记录](qa/design_knowledge_review_20260930/design_batch11_source_diff_review.html) 与其 [结构化记录](qa/design_knowledge_review_20260930/design_batch11_source_diff_review.data.json)。
- 第 12 批的 10 项只作为全局页面选项卡的源码同步差异和导航交互例外记录：沿用本章已有规则，不重复追加到 50 项通用规则，也不把“已确认登记”写成“已修复”。已确认的字号、刷新边框和焦点偏移是本批处理决定，仍需由对应开发任务同步。详细证据见 [第 12 批差异记录](qa/design_knowledge_review_20260930/design_batch12_source_diff_review.html) 与其 [结构化记录](qa/design_knowledge_review_20260930/design_batch12_source_diff_review.data.json)。
- 第 13 批的 10 项只作为 CRM v2 侧栏源码同步差异和导航例外记录：沿用本章已有规则，不重复追加到 50 项通用规则，也不把旧默认侧栏样式当成当前暖色 ERP 规范。焦点源码仍待同步，权限入口位置只记录信息架构和视觉边界。详细证据见 [第 13 批差异记录](qa/design_knowledge_review_20260930/design_batch13_source_diff_review.html) 与其 [结构化记录](qa/design_knowledge_review_20260930/design_batch13_source_diff_review.data.json)。
- 第 14 批的 10 项只作为客诉、客户时间线、生产任务详情和仓库入库明细的页面专用结构与源码同步差异记录：沿用本章已有规则，不重复追加到 50 项通用规则。标题区、工作流卡、时间轴、图片证据卡、双栏编辑区、状态轨道和仓库多信息行只在对应页面使用；客诉按钮目标32px、标签目标24px，时间线搜索不超过250px，仓库焦点采用正式外扩2px。详细证据见 [第 14 批差异记录](qa/design_knowledge_review_20260930/design_batch14_source_diff_review.html) 与其 [结构化记录](qa/design_knowledge_review_20260930/design_batch14_source_diff_review.data.json)。
- 第 15 批的 10 项只作为报工记录、报工表单和采购订单详情的页面专用结构与源码同步差异记录：沿用本章已有规则，不重复追加到 50 项通用规则。报工双栏、上下文条、明细正文滚动、三列基本信息卡和底部操作栏只在对应页面使用；报工数量错误改用正式气泡，采购订单单行表格目标遵守正式34px，供应商完整名单通过悬浮/聚焦查看。详细证据见 [第 15 批差异记录](qa/design_knowledge_review_20260930/design_batch15_source_diff_review.html) 与其 [结构化记录](qa/design_knowledge_review_20260930/design_batch15_source_diff_review.data.json)。
- 本次已解决规范文字冲突：旧页面边距、410px 搜索参考宽度、11px 表头、40px 默认双行和标签只允许六色。源码差异仍保留在汇总中；真实 ERP 输入框未逐页同步，用户反馈的复选图标偏移页仍待定位，不能登记已修复。
- 1920 × 1080 审核小样的浏览器检查属于设计证据；不代表真实页面、API、权限、数据或业务功能已验收。前一轮正式写入阶段仅改正式文档和审核记录；后续组件实施按对应开发任务另计，不能据此认定全部 ERP 页面已经同步。
- 业务字段、必填列表、校验时机、权限、日期/数字口径、上传限制、状态含义、查询/保存/关闭流程按模块已确认方案；视觉提取不能新增业务规则。样例尺寸和演示结果只有明确确认的通用值才能进入规范。
