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

### 全局配色与主题边界（2026-10-16补充）

- 用户明确要求共用颜色集中管理，便于以后切换深色。颜色的实现入口为 `src/frontend/src/styles/theme/`：主题色表 → 用途变量 → 组件变量。页面只使用用途变量，禁止新增分散的主题色硬编码。
- 默认主题为冷蓝银 `blue-gray`，暖色 `warm` 保留可切换。2026-10-19用户查看实页效果后确认 `dark` 深海蓝配色，作为第三种主题供选择；主题色表必须提供相同用途集合，缺项时构建报错，不重写共用组件和菜单动效。
- 本章色值为对应默认主题的设计值；暖色按独立色表取值。尺寸、布局、业务状态映射和动作时序不随主题改变。菜单此前条目中的橙色细节现表示强调色部位，造型不变，颜色由当前主题提供。
- 基础6组与扩展6组Tag保留已确认的颜色，当前两套主题共用这12组；不强求切换时改变每个色值。禁止重新引入灰色或深灰色状态Tag。
- 旧版单暖色自动保存值不阻止新默认主题。浏览器存储升级为 `haiqu:theme:v2`，此后保留用户主动选择；存储受限仍可在当前页面切换。
- 2026-10-19主题入口移到右上角账号左侧，仅显示主题图标，无文字、无常驻按钮边框，点击区域32px；点击展开主题菜单，不自动切换。菜单提供冷蓝银、暖色 ERP、深海蓝，标明当前选项；选择后沿用浏览器保存机制。侧边栏不再保留主题入口。
- 可见滚动条跟随主题统一配色：轨道、滑块、悬停与按住颜色分别使用 `--erp-scrollbar-track`、`--erp-scrollbar-thumb`、`--erp-scrollbar-thumb-hover`、`--erp-scrollbar-thumb-active`；原生滚动条与 Element Plus 共用这组用途色，原生交互反馈以浏览器能力为准。页面不得用文字色或边框色另行覆盖滑块。配色不改变原尺寸、滚动布局或显隐时机；已确认的“能滚动但隐藏”区域继续保持隐藏。
- 已接入共享壳层、通用控件与表格规则不代表所有历史业务页已完成换肤。业务专有硬编码逐页归入用途色；是否已验收以实施报告为准。打印仍使用白纸黑字。
- 2026-10-17用户再次确认：当前固定布局，后续更新风格主要更换配色。主题色表管理背景/渐变、表面透明度、文字/图标、边框、控件各状态、高光/阴影、状态标签及图表颜色；卡片大小、间距、圆角、字号、控件高度、列宽、滚动布局与菜单动效独立管理，不能随主题一起变化。后续配色按实际确认逐套增加，2026-10-19深海蓝经实页展示后获用户确认；确认范围与实际页面验收范围分别记录。
- 新颜色只修改/新增主题色表并注册，不在各业务页按主题名称分支。页面可以有专有布局，但背景、文字、边缘和控件仍引用统一用途色；确属业务语义的状态映射、真实图片/国旗和打印纸面作为明确例外。旧页面漏接必须记录到实施差异清单，不以全局变量已存在代替页面核验。
- 2026-10-17剩余页面接入：详情、编辑/新建表单、内嵌表格、业务弹窗/抽屉及登录页，沿用相同用途色；页面内覆盖的 Element Plus 变量、SVG 的 fill/stroke 和脚本内样式对象也属于检查范围。普通图片容器底色参与主题，图片内容本身不变；文档正文、打印纸面和专用图片预览画布按明确例外保留。
- 仅配色迁移不得顺带调整既有业务页面几何。本轮保留原控件高度、行高、间距、圆角和字体，包括登录页原输入60px/按钮56px；尺寸规范差异另列，不因换色隐式统一。后续新增或明确调整结构的页面仍按本章相应尺寸规则执行。
- 自定义阴影与遮罩取 `--erp-shadow-color` / `--erp-overlay-scrim-color`，保留原位移、模糊、扩散和透明比例；1px inset 描边属于边框用途，不得用阴影基色代替输入常态/悬停/焦点边框。可操作状态不得误用 disabled 用途色；危险/超量/取消确认继续使用 danger，不能被品牌色覆盖。
- 登录背景和纯装饰SVG换色由 `--erp-login-background` / `--erp-login-art-filter` 管理；真实业务图片不套装饰滤镜。历史报价图表系列由 `--erp-chart-series-1` 至 `-5` 集中管理，当前两主题保留原系列色及顺序，轴线和文字用普通边框/文字角色。新增主题可更换系列色，但须保留系列区分与图例对应。
- 本轮源码接入清单、真实浏览器覆盖和未覆盖原因见 [剩余页面主题接入报告](docs/designs/remaining_pages_theme_20261017/README.md)。独立大屏和并行生产工作台不计入本轮完成范围；不能把源码接入、单测通过或缺数据页面的空壳显示称为全站真实业务验收。

- 常规按钮高度统一为 `32px`，包括主按钮、次要按钮、文字按钮、图标按钮、弹窗按钮、抽屉按钮和表格操作按钮；分页按钮按 `10.10` 的 `28px` 紧凑规格执行。
- 常规图标按钮的基准尺寸为 `32 × 32px`；带文字按钮的宽度由文字、图标和水平内边距共同决定。
- 常规单行表单控件高度统一为 `32px`，包括 Input、Select、DatePicker、TimePicker、Cascader、TreeSelect、Autocomplete 和 InputNumber；分页区内的单行控件按 `10.10` 的 `28px` 紧凑规格执行。
- 筛选区和工具栏内的按钮、输入框、选择器及其他单行操作控件高度统一为 `32px`。
- 多行文本域、富文本编辑器、上传拖拽区、图片选择区等内容型控件不固定为 `32px`，高度由对应页面原型和内容需求决定；其内部操作按钮仍为 `32px`。
- 2026-10-19用户确认三个实页小样后，所有 `AppWindowDialog` 内的普通单行输入、选择器、日期、级联、自动完成和数字输入采用平面表单：高度 `32px`、左右内边距 `10px`、圆角 `5px`、文字 `13px`、纯色 `--erp-color-surface` 底、单层 `1px` 内侧边缘，无渐变及浮起阴影。弹窗专用的 `--erp-dialog-input-border` / `hover-border` / `focus-border` 分别引用主题普通边框、强调边框与焦点色。文本域复用同一套表面与状态色，只按业务内容保留高度；`.paper`、`.quotation-document`、`.a4-canvas`、`.contract-sheet` 保留纸面专用布局。弹窗 `.el-table` 内嵌编辑控件同步采用平面材质、5px 圆角、13px 字号和状态色，只保留原有紧凑高度、内边距、列宽及数字按钮避让。页面筛选区仍为原有 `32px` / `12px` / `8px` 与渐变材质；按钮保持原样，业务窗口使用 `AppWindowDialog` 实心外壳，禁止局部覆盖回玻璃高光或模糊。
- 弹窗控件边界：错误字段的常态/悬停/聚焦边缘保持校验红色；只读文本与禁用输入使用各自语义底色。数字输入的加减按钮保留组件原有避让空间，无按钮时使用左右 `10px`；文本域启用字数统计时底部保留 `22px`，不得遮挡输入内容。选择器内部 readonly input 不等于业务只读字段。
- 现有 `ElMessageBox.prompt` 的原因输入同步采用上述平面表单及校验红边；仅统一控件样式，系统确认 API 和操作行为保持原样。
- Tag 保持本章 `10.11` 规定的 `24px` 高度，不属于按钮或表单输入控件。
- 本节是 ERP 全局规则，高于前文通用组件示例以及旧页面中已有的 `36px`、`38px` 控件高度。后续新增页面和后续被修改页面必须执行；本次规范更新不要求立即批量重构未涉及的旧页面。

## 10.1 设计与验收基准

- 正式设计、开发和视觉验收统一使用 `1920 × 1080` 桌面端视口。
- 页面存在已确认的 Figma 节点时，必须读取真实设计数据，不得只根据截图猜测尺寸。
- 不得自行修改原型中的颜色、布局、按钮、圆角、间距、字号、表格密度或元素数量。
- `1440 × 900` 只作为兼容性检查：使用 `80px` 常驻主栏及覆盖内容的二级浮层、同样只计算一次的 `14px` 外缘留白和表格内部横向滚动，不作为独立的像素级设计基准，除非另有已确认原型。

## 10.2 全局页面壳层

- 常驻主栏宽度：`80px`，各视口统一保留，不再采用展开、折叠或窄屏隐藏模式。
- 二级菜单浮层宽度：`200px`，从主栏顶部展开到主栏下沿；只覆盖工作区，不改变正文宽度，不遮挡顶部导航。
- 顶部导航栏高度：`48px`，距窗口顶部 `0px`，占满全局可用宽度；顶部与下方菜单栏分开成卡片，不拼接成 L 形。
- 全局壳层由 `ErpLayout` 负责左右和底部 `14px` 留白、顶部 `0px`；顶部和下方工作区、菜单栏和正文之间均为 `14px` 间隔；顶栏与主栏的表面、外圆角和描边统一按 `10.2.3` 的玻璃材质规则。
- 2026-10-21 用户确认取消业务页面容器内边距：`PageContainer` 默认、`flush`、桌面及窄屏均为 `padding: 0`。全部列表、详情、表单、设置和未登记的新页面统一执行，不再依赖路由白名单取消内边距。页面外缘只由 `ErpLayout` 保留一层 `14px`；路由覆盖样式及页面根节点不得再增加页面级内边距。卡片、表单分组、控件及打印纸面内部的留白仍按各自规范保留。
- 客户列表骨架的实际边界间距：顶栏底边到主侧栏、筛选卡片顶边均为 `14px`；主侧栏右边到业务卡片左边为 `14px`；筛选卡片与内容卡片之间为 `14px`；整体骨架左、右、下沿距窗口边缘均为 `14px`。顶部继续保持 `48px` 高、距窗口顶部 `0px`；卡片内部按 `10.7 / 10.8` 分别处理，内容卡片底部按 `10.10` 的分页区域规则处理。
- 页面背景与骨架卡片材质按 `10.2.3`；共享表格及业务控件采用C4已确认的冷色，分别按 `10.9`、`10.10`、`10.11`、`10.15—10.17`；Tag按 `10.11` 的C3 v2配色。骨架材质不能覆盖这些专门规则，菜单动效继续执行 `10.2.1`。
- BOM 编辑页已确认的标题规则继续保留：标题栏单行最小高度 `44px`，下方距页签 `14px`，窄屏允许自然换行；标题为 `36px/44px`。该页原有的零容器内边距现已并入全局默认，不再作为路由例外。
- 详情/预览页、客户详情及业务页签统一采用上述零容器内边距；`glassDetailRouteNames` 等路由清单只负责对应布局、控件与滚动方式，不作为边距规则的前提。询盘、报价预览、包装配置标题不增加额外顶部偏移；纯单行标题以 `44px` 为基线，摘要、页签和窄屏按钮换行按内容自然增高；纸面预览内部排版不变。
- 页面本身不得出现横向滚动；超宽表格只能在表格容器内部滚动。
- Header、Sidebar、内容区必须分别布局，禁止通过整体缩放适配不同分辨率。
- 此类卡片布局任务必须检查实际 DOM 的边界坐标差、四边留白、标题实际字体与字号，并保留目标视口截图，不得只看样式声明判断通过。

### 10.2.1 左侧菜单栏

> 2026-10-17九项复核更新：下文历史橙色说明仅描述图标构成，运行颜色按主题变量。默认冷蓝银菜单强调色为 `#246EAE`；选中主图形填强调色、次层保留浅色对比。一级左轨更新为 `4px`、两端圆角，二级仍 `3px`。所有已确认动效时间和触发规则不变。顶部 Logo 保留原 PNG 分面明暗，通过主题滤色转冷蓝，禁止用平色蒙版压掉层次；管理员文字 `#41678B`。活动页签底线 `3px`、蓝色渐变圆顶，中心对齐文字按钮，不包含关闭按钮宽度。这些最新要求替代本节旧钢蓝平填、2px底线及一级3px条。

- 主栏及二级浮层不重复放 Logo；品牌只放在顶部导航最左侧。
- 主栏与二级浮层的骨架表面按 `10.2.3`；普通文字读取 `--erp-menu-text`，强调色读取 `--erp-menu-accent`。默认冷蓝银为 `#111111` / `#476F98`，暖色由独立色表提供；两级图标造型保留，配色读取统一菜单用途变量。
- 主栏依次使用“工作台、客户、样品、产品、生产、采购、车间、仓库、看板”；底部保留权限及配置入口，主题入口按10.0移至右上角。二级菜单保留完整业务名称。业务入口高 `64px`，底部管理入口高 `32px`，二级菜单高至少 `44px`。
- 一级与底部菜单按用户确认的12图标稿使用本地 `ConfirmedSidebarIcon` 矢量组件，不以相近的单色库图标替代。默认深炭色轮廓 `#283133`、品牌橙 `#C84E28` 点缀，客户前人用柔橙填色、次层用浅灰；白孔和包裹封带保留暖白。工作台为四格且左上橙色、客户为前后两人、样品为三张展开色卡、产品为橙封带纸箱、生产为三橙窗厂房、采购为带单包裹购物车、车间为加工机及机台、仓库为三橙条卷帘门、看板为三柱和双斜脚、权限为橙勾盾牌、配置为三滑杆、主题为三色点调色盘。主图标 `26px`、底部图标 `20px`，浮层标题复用对应主图标。
- 二级35项使用 `ConfirmedSecondarySidebarIcon` 本地矢量组件，来源为 `docs/designs/sidebar_motion_20261016/secondary-icons.js` 中已预览图案；统一 `24×24` 画布、`1.7px` 圆角描边、显示 `22px`，延续深炭/品牌橙/浅灰配色，不新增图标依赖。图标造型和橙色细节必须逐项与确认来源核对，尺寸及交互检查不能代替造型验收。
- 主栏字为 `13px/20px`；二级普通和选中文字均为 `15px/24px`，选中加粗600、品牌橙，避免字号改变导致位移；模块标题 `20px/26px`、700；车间副标题“车间作业”为 `12px/18px`、`#8C8983`。
- 一级及底部选中保留预览第1种造型：主题选中底、强调色图标与文字、左侧 `3px` 短竖条。二级选中保留第3种：不透明表面、左侧强调色轨道 `3px`、上下内缩 `4px`，从左侧浅选中色到透明的轻渐变。一级按钮横向内缩 `4px`、圆角 `8px`。默认冷蓝银的选中/悬停为 `#D9E8F6` / `#E8F0F7`；禁用字读取 `--erp-color-text-muted`。主栏与浮层各自的外框按 `10.2.3` 绘制一次。
- 动效按2026-10-16用户确认的分级组合：一级及底部为 **D+B**，未选中图标外层 `200ms` 浮起 `3px`、放大至 `1.07`，内层 `380ms` 轻摆一次；两层各管自己的变换，离开后回位。二级为 **A+D**，一个共享浅色背景随悬停行在 `180ms` 内平滑移动，图标 `380ms` 轻摆一次、文字前移 `3px`；展开或切组时子项 `220ms` 轻滑入，各行错开 `18ms`。不使用持续呼吸。
- 默认与悬停保持双色；已选中项稳定停住，轮廓转品牌橙、浅灰次层转浅橙。悬停不改变实际路由或选中项；离开、关闭、切组、进入选中项或禁用项时清理共享悬停背景。系统要求减少动态时取消摆动、浮起、滑入及动画过渡，保留静态颜色、色轨与正确的背景位置。
- 悬停主栏业务模块 `100ms` 后显示其二级浮层，同一时间只显示一个业务分组；鼠标移出主栏触发项和二级浮层后延迟 `160ms` 收起，进入浮层时取消收起。键盘聚焦/向右键也可打开，选择子项跳转后关闭。
- 点击一级菜单进入指定默认列表并收起浮层：客户→客户列表、样品→打样申请、产品→产品信息、生产→生产订单、采购→采购订单、车间→计划排产、仓库→成品库存。重复点击当前默认页也收起；默认项无权限时保持当前页并展开其他可用子项，不绕过权限。
- 车间二级顺序：计划排产、内部计划、委外加工、生产领料、工价方案、报工记录、生产配置。
- 浮层展开与收起只使用 `transform` 和 `opacity` 的 `180ms` 过渡，不改变布局宽度；系统要求减少动态效果时关闭过渡。不设置折叠按钮，不保留旧展开模式。
- 菜单内容超高时各自在内部滚动；权限及配置入口仅在主栏底部出现一次，并继续按真实权限显示。主题按钮仅改变当前浏览器的界面配色，放在顶栏账号旁。
- 全量更新菜单视觉时，必须保留原有权限过滤、路由地址和滚动能力；无真实路由的入口继续标明未开放，不伪造跳转。

顶部导航（2026-10-16 确认更新）：

- 最左侧使用已确认的树形图标与深色 HiTree 字标。2026-10-16 C6确认：仅ERP顶部导航中的树形图案由橙色改为钢蓝 `#476F98`，字标保留现有深色，图形轮廓、字形和比例不变；透明图片仍以 `120 × 40px` 等比容纳。侧边栏不重复品牌，不因此修改企业其他渠道的品牌资产。
- 中间保留页面页签，右侧保留当前用户和退出登录菜单。页签区域自行横向滚动，不挤走用户入口。
- 工作台固定在第一个、不可关闭、不参与自动淘汰；总数上限仍为 `5`，其余按既有打开顺序淘汰。旧会话恢复时补齐固定工作台，保留权限和未保存离开保护。
- 2026-10-19按顶部工作台页签反馈调整：顶栏仍为48px，页签项与操作按钮高 `32px`、上下居中、项圆角 `8px`，文字 `13px/20px`、选中字重 `600`。当前页使用主题选中衬底和强调色，取消全局页签下划线、不加外框边线；工作台复用 `ConfirmedSidebarIcon` 四格图标，显示18px。关闭按钮及页签逻辑保持原样。此规则只适用于顶部 `GlobalPageTabs`，页面内业务页签继续按10.18。
- 用户按钮高 `32px`；键盘焦点使用正式蓝色 `#3898EC`。48px 顶栏内的页签容器焦点向内绘制 `2px`，避免被滚动容器裁切；内部按钮仍保留外侧焦点。不增加未确认的搜索、通知或头像入口。

### 10.2.2 页面高度与纵向滚动（全部页面）

- 浏览器窗口和 ERP 外层布局以可视区域为边界。页面实际内容（含上下内边距）未超过内容区可用高度时，不得因固定高度、`min-height`、重复内边距或占位区域产生纵向滚动条。
- 页面确需按视口计算高度时，必须扣除实际顶部导航高度、外层容器上下内边距及页内外边距；不同页面壳层不得复用未经核对的 `100vh - 固定值`。能使用弹性布局和 `min-height: 0` 时优先使用。
- 内容确实超出可用高度时，必须有明确的纵向滚动容器，且能滚到最后一个内容和操作按钮；不得用 `overflow: hidden` 截断内容。表单、详情、设置、工作台等页面优先由主内容区滚动。
- 需要固定标题、工具栏或分页的列表页，可让表格内容区独立滚动；分页和底部操作始终可见。表格内部滚动时，浏览器窗口及页面主内容区不应同时滚动。
- 页面不得同时出现无必要的父子两层纵向滚动。侧栏菜单和弹窗按各自独立滚动规则处理。
- 产品管理与原料管理左侧品名卡（2026-10-17标注确认）：外卡不承担滚动，仅品名列表可纵向滚动并隐藏滚动条，禁止横向滚动；保留键盘聚焦、滚轮和末项可达。光斑伪元素的外扩边缘不得制造空滚动条。须检查最终计算样式及全局/局部规则加载顺序，不能只检查源码中是否写了overflow。
- 验收时分别检查内容较少和内容超出两种状态，并在 `1920 × 1080` 及窄窗口验证：前者不出现空白滚动，后者能实际滚到最末内容，而不是只看有没有滚动条。

### 10.2.3 骨架卡片玻璃材质

> 2026-10-16 用户逐项确认 C1，后续已授权实施与全局配色提取。运行源码已接入；实际验收结果见对应实施报告，规范确认不能代替验收。来源见 [设计提取与确认记录](docs/designs/customer_glass_theme_20261016/README.md)。本项替换指定骨架原有的实底、10px圆角及外框规则，C2—C6以各自后续确认记录为准。

- 适用范围：共享顶部导航、主侧栏、二级菜单浮层，以及客户列表筛选外卡和内容外卡（含分页留白区域）。其他业务页面通过共享壳层获得统一材质，不强制增加包装层或改变页面专有布局。
- 页面采用已确认的冷蓝银方向。2026-10-17按用户要求对照原图纠偏：旧生成意图色 `#AFC3D5 / #CCD6DF / #E9EEF2` 实现后偏灰，不能继续作为还原通过的依据；运行色表校准为 `#91B9D9 / #B5D2E8 / #D9EBF7`，左侧叠 `#E2F1FC` 柔光，配合一至两道宽幅半透明白色光弧。光弧经过28px模糊后仍应可见，不能只在卡片缝隙出现细白线。背景由壳层统一绘制，内部容器不重复绘制独立渐变，不新增循环背景动画。校准细值属于实现值，视觉依据仍是原图及后续确认项。
- 指定骨架使用半透明白色磨砂玻璃，白色不透明度范围 `45%—60%`，`backdrop-filter: blur(28px) saturate(140%)`。透明度仅用于表面颜色，不降低整个容器及其文字、图标的不透明度；内层材质可以略实，不为凑层次新增重复外壳。
- 指定外卡圆角统一为 `16px`（2026-10-17用户九项反馈替代24px），四边 `1px` 半透明白色描边，顶部内侧细高光，大而柔的阴影。白边透明度、高光和阴影的具体数值、渐变角度及色标位置须结合实际视口校准，不把生成图的像素值当作原始CSS。
- 2026-10-17边缘校准：白边由65%降至45%，顶部内高光由75%降至28%，阴影减为12px/36px/7%与2px/6px/3%；保留45%白色表面、60%内层表面和28px/140%背景滤镜。不要通过降低整个容器opacity让文字变淡。材质验收须将原图与实际截图在相同视口并排比较，计算样式符合这些值不等于视觉还原通过。
- 冷色材质区分背景柔光与玻璃表面反光：`glass-background`保留纯颜色，`glass-surface`将一条低强度连续弧形反光叠在该颜色上，各骨架使用同一视口坐标，避免每张卡各画一条不衔接的弧。表面反光不再经过背景blur，不覆盖文字、不增加DOM或重复边框。暖色主题保留原表面；遮罩继续使用纯颜色用途变量。
- 2026-10-17用户新增的鼠标柔光：仅顶部导航和客户筛选卡接入共享 `vGlassSpotlight`。光标附近显示半径240px的柔和径向光斑，并在原有1px边框位置局部提亮；光效不拦截点击、不改变尺寸，也不叠出第二道外框。颜色从主题的 `spotlight-fill / spotlight-edge` 读取，默认冷蓝银分别白色22%/85%，暖色20%/80%；离开220ms淡出。每帧最多更新一次位置，移出、取消、窗口失焦或卸载时清理；触屏、粗指针、减少动态和打印关闭光效。当前输入框材质、尺寸及原菜单动效保持。
- 每个可见外框由一层容器绘制；描边计入 `border-box`。保留顶部高 `48px`、距顶部 `0px`、左右及底部 `14px`、骨架之间 `14px`、主栏 `80px`、二级浮层 `200px` ；卡片内边距分别执行10.7/10.8最新约定。不通过新增边框或重复留白改变这些实际边界。
- 筛选卡高度继续由内容自然增长与换行决定。共享按钮和输入圆角更新为 `8px`；客户表格框圆角 `8px`。用户明确不修改按钮/输入高度：普通控件保持 `32px`、分页控件 `28px`；一级菜单项 `8px`、Tag `999px` 圆角保持。
- 一级 D+B、二级 A+D，以及选中第1种/第3种的造型和动态参数全部保留；不改动变换层、关键帧、时长、缓动、触发延迟、路由及键盘逻辑。二级选中保留不透明底层，避免共享悬停背景透出；增加玻璃效果后须检查浮层层叠、裁切和减少动态设置。
- C1材质不覆盖专门规则：标题与统计卡按10.5、表格与分页按10.9—10.10、Tag按10.11、控件按10.15—10.17、Logo按10.2.1的C6确认项。打印继续白纸黑字及原有布局，去掉背景光弧、玻璃模糊和阴影；不支持背景模糊的环境保留冷白可读表面。

### 10.2.4 已接入的共用玻璃列表（2026-10-17）

用户在客户列表确认后要求依次更新询盘、报价、销售订单、任务中心，并扩大为全部独立列表。统一接入`theme/_list.scss`，路由清单集中在`config/glassListRoutes.ts`。通过`.erp-glass-list`显式启用；详情内嵌列表保留对应布局，不机械套用独立列表骨架。客户列表沿用已确认实现。

- 上方为标题与既有筛选，下方为操作工具栏、表格和分页；新建/导出在内容卡左上。保留各页真实总数、更多筛选、字段、列宽、业务编号及原多行信息，不照搬客户统计示意图或改变筛选提交时机。
- 使用10.2.3的玻璃背景、16px圆角、单层1px边框和光斑；外间隔与窗口留白14px只计算一次。标题36px/44px黑体700；筛选内边距14px16px10px，自然换行增高；内容内边距10px14px0；工具栏左右内收2px，距表格10px。
- 本组页面共享输入框完整高光/柔阴影及32px高度、8px圆角，顶部筛选控件12px/18px文字；字段宽度沿用业务页面。更多筛选浮层显式使用`.erp-list-filter-popover`，保留字段与布局，控件同为32px。详情、新建、编辑等弹窗不借本次列表改造重新设计。
- 表头38px、普通行最小40px；业务多行、图片和排产进度按原内容自然增高，不强行裁切到40px。联系人已有舒适密度56px保留，紧凑密度采用40px；此切换与颜色主题无关。表格外围由`.erp-list-table-frame`唯一绘制1px白色72%细边；内网格和表头/表体颜色仍使用全局用途色。内容溢出时优先表格内部滚动；原有统计分析、分类目录和左右联动工作区保留必要的局部滚动。
- 分页区40px、控件28px、间距6px，保持各页默认页容量及选项。实体筛选/工具栏按钮显式启用10.15动态反馈；不把表内文字操作、菜单或禁用状态变成浮起按钮。系统减少动态、触屏和打印规则继续适用。
- 标签改用已确认的Tag用途色，原业务状态与颜色类别映射保持；不得增加灰色标签或凭视觉修改业务状态含义。
- 有筛选字段的独立列表，在常驻筛选尾部统一显示“重置 → 应用筛选”，后者使用主按钮；不能只保留重置、把应用藏入浮层或改叫查询。应用调用页面原筛选动作，重置恢复其默认筛选；原有即时查询不因此全部改成草稿提交。没有筛选字段的列表不新增无效按钮。
- Element Plus表格与原生表格使用同一组用途色、边缘和分页规范；旧页面局部规则、旧密度样式以及固定操作列覆盖层不得覆盖公共材质。原生控件通过显式公共类接入，不以复制一份色值实现“统一”。
- 分类目录项目不允许纵向压缩：单行最小32px，长名称按既有规则换行自然增高，超出可视高度由目录内部滚动；验收须检查文字上下边界及末项可达，不能只验证表格。
- 2026-10-17用户标注的页面例外：客诉独立列表去掉标题说明与4项统计条；询盘编号、任务编号各独立一列，询盘接收日期时间保持同一行；销售订单来源、业务员、跟单员分别成列，不显示V版本及客户编号，客户名前国旗只取客户档案真实国家。上述变化仅适用于指定列表，不把字段拆分或删除推广为所有页面的统一业务规则。
- 产品目录无分页时，内容卡底部留白使用共享`--erp-space-3`（12px）；有分页时沿用原分页留白。按2026-10-17后续标注，颜色值恢复原浅色表面，新增颜色/产品按钮保留全局主按钮材质；“新增产品”移到顶部产品数量后，原高度及权限保留。产品与原料目录选中项采用菜单强调色左侧3px线，选中底色略加强，保留目录内部滚动规则。
- 2026-10-17生产页面标注例外：排产与内部计划去掉标题旁数量描述；搜索框最多250px，刷新与重置/应用成组自然换行，日期输入不挤出筛选区域。内部计划四个页签移至表格内容卡顶部；规格、颜色、材质各独立一列，规格仅剥离独立字段能证实的拼接尾缀，不修改源快照。委外加工厂管理入口采用无下划线按钮，取消“外发单明细”文字。
- 生产配置页保留现有三卡布局、间距和入口，卡片引用工作台玻璃背景、单层边框、圆角、阴影与模糊用途变量；页面底色透明，标题使用36px/44px、700字重。此处不增加工作台倾斜动画，也不改变配置管理业务。验收见[生产页面标注修正](docs/designs/workshop_annotations_20261017/README.md)。
- 同日后续标注：生产配置按内容自然撑高，取消旧视口常量最小高度，避免叠加外层留白产生12px多余滚动；仅真实溢出时保留主内容区滚动。内部计划页签靠左，项高32px、字13px/行20px，取消全宽底轨，选中线引用顶部页签同款3px、4px 4px 1px 1px圆角与`--erp-tab-active-indicator`。生产领料搜索最多250px，去掉标题下库存链路说明。仅限本次指定页面，见[五条后续标注验收](docs/designs/workshop_followup_20261017/README.md)。

参数来源为客户列表确认及本轮扩大实施范围；此前验收见[四列表更新记录](docs/designs/sales_lists_glass_20261017/README.md)，本轮页面清单、漏接项与验证见[全部列表更新记录](docs/designs/all_lists_glass_20261017/README.md)。规范登记不等于验收已通过。

### 10.2.5 客户新增与详情（2026-10-17）

- 同日后续：编辑客户使用`AppWindowDialog`，按“稍微大一点、左侧分区”反馈调整为1040px宽、780px高（受视口限制）；左侧136px导航显示主体资料、地址属性、客户属性、归属与标签，点击定位，滚动同步选中。取消右侧编辑摘要整栏，只有正文纵向滚动，底部仅保留取消与保存，保存后继续停留弹窗。列表、详情在当前页开窗，直接编辑URL保持可用。客户列表菜单文案为“详情”“编辑”，移除“联系人”项；独立联系人模块继续保留。见[编辑弹窗记录](docs/designs/customer_edit_dialog_20261017/README.md)与[尺寸及导航调整](docs/designs/customer_dialog_navigation_20261017/README.md)。

- 新增客户采用10.14的`AppWindowDialog`。按最新“稍微大一点”反馈，初始尺寸920×620px（受视口限制），沿用窗口居中、拖动与最大化；标题和底部操作固定，正文仅在真实溢出时滚动。列表本地打开，直接新增URL保留；联系人输入为名称与邮箱。
- 客户详情沿用10.2.3玻璃材质、单层边框、16px圆角和14px间距，标题36px/44px无衬线700；操作自然换行，页签靠左32px，活动线引用顶部页签材质。概览由真实业务统计、基本资料、互动时间轴和待办/健康构成，宽屏三列、较窄窗口顺排，取消旧固定整页高度。
- 用户确认取消详情“联系人”页签，将全部联系人名称和邮箱放入概览基本资料区，以紧凑行呈现；独立联系人模块及历史字段保留。旧详情联系人链接兼容跳回概览。范围、边界和验证见[客户新增与详情记录](docs/designs/customer_experience_20261017/README.md)。
- 2026-10-17补齐详情内时间轴、任务、询盘、报价、样品、订单、客诉及客户转移：与概览共用玻璃材质、16px外卡、14px间距、32px/8px控件和28px分页。内嵌列表保留客户维度与原业务功能，筛选自然换行，移除旧固定整页高度和父级叠加覆盖；原隐藏统计不借本轮新增展示。任务/客诉创建弹窗仅在客户详情使用对应玻璃分组，独立模块原样。见[全部页签补齐记录](docs/designs/customer_detail_tabs_20261017/README.md)。
- 2026-10-17用户根据其他详情审计明确要求继续修复：审计的25个详情/预览路由通过`glassDetailRoutes.ts`显式接入控件和窗口材质，主面板复用`theme/_detail.scss`的16px玻璃卡，内分组采用8px轻背景且不重复模糊；原业务字段、页签、权限及保存流程保留。销售订单窄屏摘要下排，排产日期/工艺分区按容器宽度换行。详情使用自然高度，管材委外保留其表格工作区滚动；报价/BOM纸面不套玻璃样式。联系人详情/历史抽屉显式局部接入，报价主编辑页仅调整相关卡片，不扩大为完整表单改版。实际修改和数据覆盖边界见[其他详情补齐记录](docs/designs/other_detail_fix_20261017/README.md)。

2026-10-17补充表单与滚动规则：按用户跨页排查要求，已核对的新建/编辑/业务处理页通过`glassFormRoutes.ts`显式接入玻璃控件和窗口，外卡16px、内说明8px。普通长表单使用自然高度，由主内容区承担整页纵滚；采购合同画布、样品填写/材料/仓库审核、领料详情等固定工作区由父容器分配实际高度，内部正文或画布承担滚动，不再用窗口减固定像素估算。样品紧凑表格28px行内控件及合同/报价纸面保留专用规则；询盘需求摘要与时限状态卡使用相同浅色。实际范围和验证边界见[询盘与重复滚动修复记录](docs/designs/inquiry_scroll_fix_20261017/README.md)。

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

> 客户列表标题例外（2026-10-17用户最新确认）：仅 `customers` 路由的“客户列表”标题使用 `Noto Sans SC`、`Microsoft YaHei`、`sans-serif` 字体链，字号 `36px`、行高 `44px`、字重 `700`、`letter-spacing: normal`；标题区高 `44px`。本项明确替代之前24/32，按钮和输入仍保持原高度。总数移至下述 C5 统计卡，不再紧邻标题显示。其他页面标题保持下述默认规则，不批量修改。

> 客户列表统计卡例外（2026-10-16 C5 确认）：筛选区右侧使用 `#1B1B19` 深色统计卡、蓝银柔光、白字和 `24px` 圆角，仅用于客户列表。总数取真实列表响应 `meta.total`，跟随已应用筛选更新，不由当前页行数推算；总数只在卡中显示一处，移除标题旁与分页左侧计数文字，保留分页 `:total` 参数及真实分页逻辑。加载或失败不伪装成真实 `0`。

> C5视觉稿已确认（用户查看带趋势柱的预览后回复“好”）：采用左侧总数、右侧高低错落趋势柱，顶部蓝银柔光；柱体由 `#BCD9F2` 向 `#7E9FBD` 竖向渐变，后方保留浅色半透明底柱。数字默认 `48px / 52px`、字重 `600`、纯白、等宽数字；宽屏卡片参考宽 `360px`，窄屏自然换行，卡片及筛选区高度随内容增长，不锁定截图测得高度。确认图见 `docs/designs/customer_glass_theme_20261016/customer-stat-card-preview.png`，响应式示意见同名HTML。

> 2026-10-17九项反馈及后续边距校准：统计卡参考宽320px、上下12px/左右16px内边距、16px圆角，48/52数字及12根装饰柱保留，图高48px。去掉可见“趋势示意”和“个客户”，示意性质通过可访问名称说明；数字右侧补1px浅色分隔线。常规内容下统计卡自然高96px，筛选外卡按10.7的最新内边距自然高122px，32px筛选控件/按钮与统计卡底部对齐；不设置固定height，窄屏或长数字允许增长。本项替代上述C5旧24px圆角、360px宽和之前114/148px、130px高度。

> 图中数字64与12根趋势柱为设计示意。正式总数只读取真实接口meta.total；趋势指标、周期和接口仍为 `UNKNOWN`。装饰柱不绑定日期、坐标轴或增长率，不冒充正式趋势。用户本轮明确移除可见示意文案，其说明保留在可访问名称中。

> 样品库存统计卡例外（2026-10-17用户标注及口径确认）：筛选区右侧复用上述320px深色卡及全局`stat-*`材质变量，显示当月入库、当月出库、当月借出、当前可用库存四柱，保留当前库存与当月流量的分隔。前三项按服务器本地月份的[月初,下月初)聚合实际数量；第四项为即时库存。四柱共用数量比例，0为零高，加载/失败/缺字段显示未知并允许重试，不用客户列表的装饰柱冒充样品统计。移除原顶部说明、路由切换条及旧四项统计；筛选去外部label但保留无障碍名称，未选择时下拉显示字段名，已选状态仍明确显示真实条件。此项不改变其他样品页面及默认库存筛选。

- 普通 ERP 页面容器内边距统一为 `0`，按 `10.2` 由 `ErpLayout` 独立负责一层 `14px` 外缘留白；页面根节点不得补回内边距。卡片与打印纸面的内部留白按对应规范保留。
- 普通页面标题使用 `Noto Serif SC`，字号 `34px`、行高 `44px`，保持高识别度但不额外放大。
- 普通页面数据总数紧邻标题显示，不单独制作统计卡片；客户列表按上述 C5 例外。使用真实结果，未取得总数不能编造为 `0`。
- 页面级操作放在标题区域右侧，包括导入、导出、新建等操作。
- 次要页面按钮参考尺寸：`110 × 32px`。
- 主要页面按钮参考尺寸：`140 × 32px`。上述宽度为参考；长文案按内容扩展，不强行截断或固定所有页面宽度。
- 按钮圆角：`5px`；图标尺寸：`16px`；图标与文字间距：`8px`。
- 同一标题区最多保留一个高强调主按钮。
- “新建”属于页面级操作，不得放入表格工具栏。

## 10.6 快捷统计条

> 客户列表的 C5 统计卡按 `10.5` 专用例外执行，不套用本节快捷统计条布局，也不扩展到其他业务页。

- 使用高度 `46px` 的整行平铺结构，不使用独立卡片、阴影或图标卡片。
- 每一项水平、垂直居中。
- 指标标题字号：`13px`；数字字号：`12px`。
- 当前项底部使用 `4px` 品牌色指示线。可交互指标使用 `46px` 外层单元格和 `32px` 内部按钮，名称和数值同行并预留指示线；纯展示指标保留文字，不强加按钮。
- 指标必须来自真实汇总接口，禁止使用当前页数据临时推算全部统计。
- 指标数量、语义、宽度、是否可点及点击后筛选或跳转由具体页面确认；客户列表的统计项不能直接复制到其他业务列表。没有统计接口则省略整条及其空隙，加载、失败、无权限不能伪装为真实 `0`。

## 10.7 筛选区

> 2026-10-17客户页更新：控件保持32px高，圆角更新8px；选择器的“全部”是有效默认条件，使用黑色正文，搜索占位使用蓝色次要文字。输入表面使用冷白半透明纵向渐变、顶部细高光和柔阴影；高度不锁死，控件行与右侧统计卡底部对齐。本轮不改按钮或输入高度。

> 客户列表例外（2026-10-16 确认）：标题、关键词、客户状态、等级、国家/地区放在独立浅色卡片中；标题执行 `10.5` 的客户列表专用字体与尺寸规则，总数移至筛选区右侧 C5 深色统计卡。取消“更多筛选”及高级条件；保留“重置 / 应用筛选”。选择条件先保留为草稿，应用、关键词 Enter 或搜索按钮才查询；分页与导出继续使用已应用条件。重置清空条件并恢复默认排序。卡片高度随内容自然增长、控件换行，不设固定高度。外层留白按 `10.2` 仅计算一次，`PageContainer` 不再追加 `padding`。外层卡片的玻璃表面、圆角与描边按 `10.2.3`，卡片内边距上14px、左右16px、下10px，标题与条件最小间隔 `12px`，条件间隔 `8px`；四种控件沿用当前 `250 / 128 / 120 / 140px` 宽度，窄屏搜索框可缩小。此例外优先于本节的立即查询与更多筛选默认规则。

- 所有输入框、选择器和筛选按钮高度统一为 `32px`。
- 同一行控件间距：`14px`。
- 所有搜索框最大宽度为 `250px`，窄窗口可更窄；此上限覆盖旧版 `410px` 参考宽度，也适用于其他区域的搜索框。其他常用参考宽度：主状态 `160px`、分类/等级 `142px`、第三筛选项 `176px`、更多筛选 `130px`，不强套至所有模块。
- 首行最多展示“搜索 + 3 个高频筛选 + 更多筛选”；低频条件统一放入“更多筛选”。
- 搜索框按 Enter 执行查询；常用 Select 选择或清空后立即查询，页面有特殊业务流程时以已确认交互为准。
- “更多筛选”应保留应用和重置能力，并继续承载页面已有的低频条件。
- 控件圆角：`5px`；键盘焦点色：`#3898ec`。
- 筛选字段必须来自当前业务的数据模型，不得为了套用布局复制客户页面的字段。

## 10.8 批量操作与工具栏

> 客户列表例外（2026-10-16 确认）：内容卡片顶部仅放“新建客户 / 导出”，新建不在标题区重复出现；省略尚未开放的导入占位入口。内容外层卡片（含分页留白区域）的玻璃表面、圆角与描边按 `10.2.3`，与筛选卡片间隔 `14px`；内边距上10px、左右14px、底部由分页区留白，工具栏额外左右内收2px，工具栏与表格间隔10px。内部表格自身的实底和边框继续按 `10.9`，不随外卡玻璃化。该页不据通用条目新增批量操作、列设置或保存视图。

- 工具栏容器高度：`32px`；工具栏内所有按钮、输入框和选择器高度统一为 `32px`。
- 左侧放置已选数量和批量操作；右侧放置排序、列设置、保存视图和刷新。
- 刷新按钮固定放在工具栏最右侧，并使用完整按钮外观。
- 列表页不显示“密度”按钮，表格默认且固定使用超紧凑密度。
- 当前页面不支持的操作应直接省略，不得保留空白按钮或占位。
- 未选择数据时，批量操作按钮保持可见但处于禁用状态。
- 页面级“新建”按钮不得重复出现在工具栏。

## 10.9 数据表格（默认超紧凑）

- 页面表格内编辑控件使用 `erp-table-editor` 显式接入共享平面样式：纯色底、5px 圆角、13px 文字和单层 1px 内边缘，不使用渐变或浮起阴影；沿用各表格原有控件高度、留白、列宽和数字按钮避让。只读、禁用、错误、悬停、聚焦状态使用对应主题语义色。2026-10-19 已确认推广到清单中的 20 处页面；筛选区与合同纸张、打印区域保持原规范。

> 2026-10-17最新颜色校准：共享表头更新为 `#D8E9F7`、表体/固定列/空白 `#EFF7FC`、网格 `#DCEBF5`；普通文字仍黑色、Tag v2保持。本项替代下文C4旧色值。客户列表表头按用户后续明确要求改38px，数据行40px以及列宽保留。表格外围独立使用1px白色72%高光边，内部网格仍#DCEBF5，禁止叠边。

> 客户列表例外（2026-10-16 确认）：保留原 12 列、列宽、顺序、风险列及网格结构，表头 `44px`、数据行 `40px`；字体、字号、字重保持原规则，颜色按下方已确认的C4共享配色和10.11的C3标签配色。客户名称下不显示编号，表头为“客户名称”；所有信息单行显示，超长名称和国家可查看完整文本。国家前显示 `16 × 12px` 国旗，沿用基础资料中心的 flagcdn 来源；无效国家代码不加载图片，失败时保留国家名称。表格框四边由 `customer-table-frame` 单独负责，关闭 Element Plus 外围伪元素及补丁重复边线。该页的 `40px` 单行是明确例外，不改全局默认行高。

> 共享表格配色（2026-10-16 C4确认）：适用于客户列表及全局共享表格，替代此前暖色和客户多色文字例外。表头 `#DFE9F3`；表体、固定列及表内剩余空白 `#F5F8FB`；外围与内部网格 `1px #DDE5EE`；悬停 `#EAF2F9`，已有选中/当前行 `#D9E8F6`，不新增行选中功能。表头、普通字段、名称、金额、日期、缺值横线、次要说明、表内空态文字及三点操作统一 `#111111`。Tag优先执行 `10.11` 已确认的C3 v2：基础深彩纯白字、扩展浅底黑字；国旗保留原色。错误提示、危险动作、禁用控件和真实状态图标继续使用其语义色，不被普通表格黑字规则覆盖。

> 配色依据与实现边界：C4采用已确认冷蓝银设计及配套交互颜色，不再沿用此前暖色截图采样。共用颜色并入既有主题变量；清理目标页面内与新变量冲突的硬编码时，仅处理颜色，不改变列、行高、字号、滚动或业务行为。固定列、普通单元格、表内空白及悬停色必须连续。规范已确认不等于全部业务页已接入；实施时逐项报告实际覆盖范围。

- 表格宽度：`100%`。
- 表头高度：`44px`。
- 默认数据行高度：`34px`，单行显示；不自动拼成“主字段 + 次字段”双行。旧版 `40px` 双行及 `52px` 行高均不是默认值，列名和顺序仍按页面已确认原型。
- 单元格水平内边距：`16px`。
- Checkbox 视觉尺寸：`14px`。
- 表格外层圆角：`5px`；通用列表用 `1px #DDE5EE` 外框和横向分隔线，默认不加竖线；页面已确认网格例外按其原型。外框由一层绘制，最后一行不叠底边。悬停底 `#EAF2F9`、选中底 `#D9E8F6`，选中再悬停保留选中底；固定列与滚动首末行保持颜色和边界连续。
- 表头文字：`12px / 18px`（字号 / 行高）、字重 `500`，背景 `#DFE9F3`；普通单元格：`12px / 18px`；名称等主字段：`13px / 20px`；次要编号或说明：`11px / 16px`；金额：`13px`、字重 `600`；日期：`13px`。上述普通文字均为 `#111111`，层级通过既有字号、字重和布局区分。
- 双行样式保留，仅在用户明确要求的页面使用：主行 `20px` 加次行 `16px`，共 `36px` 内容；原 `40px` 行高可作为已确认双行例外，不得裁切、重叠或作为全局默认。
- 表格内 Tag 高度保持 `24px`；`14px` 复选框、Tag 和 `32px` 三点操作按钮必须在默认 `34px` 行内垂直居中。复选框内的勾和半选横线也须居中，普通、半选、禁用均需验收。
- `34px` 行内的 `32px` 按钮上下仅余各 `1px`；`2px` 外圈加 `2px` 偏移需要额外显示空间，必须核对首末行及固定列的溢出、层级和焦点留白，不能裁圈、改内圈、缩按钮或恢复更高默认行。
- 表头、普通文字、次要信息和缺值占位统一显式使用 `#111111`，不依赖浏览器默认色；可点击客户名悬停仍为黑字，可用下划线提示。输入占位、禁用及错误语义按控件规则，不套普通表格文字规则。
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

> 2026-10-16 根据用户“缩小分页控件和区域高度，并更新既有规范”的要求修订。以下紧凑规格替代原分页尺寸；客户列表在卡片布局任务中同步，其他页面按后续任务同步并验收。

- 分页区容器高度：`40px`，内部控件高度统一为 `28px`，上下各保留约 `6px` 间距，内容垂直居中，并保留键盘焦点外圈空间。
- 普通页面左侧显示总数量；右侧依次显示每页数量、上一页、页码和下一页。客户列表按 `10.5` 的 C5 例外移除左侧计数文字，总数仅在统计卡显示；保留分页 `:total` 参数，不改变分页计算与接口请求。
- 高密度列表默认：`50 条/页`；如业务量明显较小，可由页面需求另行确认。
- 每页数量选择器参考尺寸：`112 × 28px`；长文案按内容适当增宽，不截断当前值。下拉面板内选项仍按 `10.17` 保持 `32px` 高。
- 页码、上一页和下一页按钮基准尺寸：`28 × 28px`；页码按钮宽度为最小值，位数增加时按内容扩展，不截断数字。
- 页码及前后页按钮之间间距：`6px`；每页数量选择器与翻页按钮组之间间距：`8px`。
- 分页区文字使用 `Noto Sans SC`、`12px / 18px`；控件圆角保持 `5px`。分页尺寸为通用 `32px` 按钮及单行控件的明确例外，不改变筛选区、工具栏或表单的控件尺寸。
- 当前页使用 `#D9E8F6` 冰蓝底、`#476F98` 文字和 `1px #476F98` 边框，悬停保持当前页状态；其他页沿用10.15的普通浅底按钮及冷色交互，首页的上一页和末页的下一页禁用。控件之外的分页留白沿用所在卡片材质，不额外绘制底条。
- 分页必须继续调用真实列表接口，不能只在前端截取当前数据。

## 10.11 ERP 共享视觉变量与标签

### 颜色

- 2026-10-16 C4已确认以下全局共享表格与控件配色；替代旧暖色值，尺寸和行为不变。控件包括按钮、输入、选择器及其选项、日期/数字/文本域、单选复选和分页。C5客户列表深色统计卡及趋势柱外观已按 `10.5` 专用例外确认；C6顶部Logo仅树形改钢蓝，按 `10.2.1` 执行。不将本条共享配色扩展为其他页面新增布局或更改品牌图形轮廓。
- 页面背景：按 `10.2.3` 的冷蓝银渐变；不将渐变值传给只接受颜色的 `background-color`。
- 通用不透明表面、表体、下拉面板：`#F5F8FB`；表头为 `#DFE9F3`。普通按钮及可编辑输入默认用白色60%背景，详见10.15—10.17；骨架外卡和分页留白按 `10.2.3`，不要将所有子控件再叠一层背景模糊。
- 次级表面及只读底：`#E8F0F7`。
- 禁用底：`#E2EAF2`，禁用文字 `#617182`，不整框叠透明度。
- 表格Hover行：`#EAF2F9`；按钮及选项Hover：`#E8F0F7`；次按钮按下：`#D9E5F0`。
- 选中行、选中选项及当前页底：`#D9E8F6`。
- 主文字及常规文字：`#111111`。
- 次要文字：`#445669`；弱化/占位文字：`#617182`。表格普通文字为明确例外，统一按10.9使用 `#111111`；错误、禁用及Tag按各自语义规则。
- 控件普通边框：`1px #C5D5E4`；悬停/较强边框：`#9FB6CC`；表格边框和网格另用 `#DDE5EE`。
- 品牌按钮默认/悬停/按下：`#476F98` / `#3C628A` / `#315473`；Tag的Brand色槽与按钮主色分开，Tag按下方已确认v2配色，两者不自动互换。
- 深底反白文字：`#FFFFFF`。错误与危险语义仍用 `#B53333` 及10.15的危险按钮状态，不因换主题改为蓝色。
- 键盘焦点色：`#3898ec`。

### 字体、间距和圆角

- 页面标题：`Noto Serif SC`。
- 界面文字和数据：`Noto Sans SC`。
- 常用间距刻度：`4 / 8 / 12 / 16 / 24 / 28px`。
- 按钮、输入框、选择器、表格和分页的默认圆角：`5px`。

### Tag

- 所有表示状态、类型或属性的 Tag，执行2026-10-16用户看过v2配色板后回复“好 可以”确认的12色方案：基础6色为深彩底纯白字，扩展6色保留上一版浅底黑字；全部保留细边框、24px高度和胶囊形态，不使用灰色或深灰色Tag。原Figma `00C2_标签` → `Warm ERP/Tag` 仅保留为历史来源，规范确认不等于运行代码已同步。
- 两字标签的基准尺寸为 `56 × 24px`；较长文本按内容扩展，最小宽度为 `56px`。
- 水平内边距为 `8px`，文字水平、垂直居中。
- 圆角为 `999px`，显示 `1px` 与该色槽配套的细边框；使用 `border-box`，边框计入既定 `24px` 高度。
- 字体为 `Noto Sans SC Medium`，字号 `12px`，行高 `18px`，字重 `500`。
- 基础组文字使用纯白 `#FFFFFF`，不沿用旧暖白 `#FAF9F5`；扩展组文字保持黑色 `#111111`。通过背景色、边框与明确文字区分状态，不能用统一黑字或白字规则覆盖两组差异。
- 基础组保留六种语义色槽，使用以下已确认值。Neutral用鸢尾紫，不恢复历史深灰：

  | 色槽 | 色名 | 背景 | 边框 | 文字 |
  | --- | --- | --- | --- | --- |
  | Brand | 靛蓝 | `#475DB0` | `#394E9D` | `#FFFFFF` |
  | Info | 清海蓝 | `#2F78B7` | `#26699F` | `#FFFFFF` |
  | Success | 孔雀青 | `#197C87` | `#126C77` | `#FFFFFF` |
  | Warning | 莓紫 | `#9D548E` | `#88457B` | `#FFFFFF` |
  | Danger | 玫瑰红 | `#B74D72` | `#A13F62` | `#FFFFFF` |
  | Neutral | 鸢尾紫 | `#765CB6` | `#654AA3` | `#FFFFFF` |

- 扩展组保留上一版浅底、配套边框及黑字方案，使用以下已确认值。历史RGB实底仅保留在配色数据的`old`字段用于核对，不作为当前目标：

  | 扩展色 | 色名 | 背景 | 边框 | 文字 |
  | --- | --- | --- | --- | --- |
  | 1 / 红 | 浅樱红 | `#FAE1E4` | `#E7B1BA` | `#111111` |
  | 2 / 黄 | 柔金黄 | `#F8EBC4` | `#E4CD85` | `#111111` |
  | 3 / 绿 | 浅青柠 | `#E8F2D9` | `#C6DCA7` | `#111111` |
  | 4 / 青 | 冰湖青 | `#DDF2F5` | `#AFD7DF` | `#111111` |
  | 5 / 橙 | 柔杏橙 | `#FBE7D9` | `#E7C0A4` | `#111111` |
  | 6 / 粉 | 浅莓粉 | `#F5DFEF` | `#DDB0CF` | `#111111` |

- 既有客户状态映射保持：活跃→Success；需跟进→Info；高风险/已逾期→Danger；沉默/数据不足/未安排→Neutral；今日跟进/待跟进→Warning。配色板及确认记录见`docs/designs/customer_glass_theme_20261016/README.md`第4.6节。

- 两组高度、最小宽度、内边距、圆角、字号、字重及1px细边的规格一致，底色深浅与文字颜色按上述分组执行；使用哪组由用户在使用时选择。扩展颜色不按色相自动绑定业务状态，不自动全局替换。
- 展示型状态Tag保留只读语义，不因换色新增hover变色、选中态、点击、浮起或呼吸；已有可操作标签按其实际交互另行定义，不将菜单动效搬到Tag。
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

### 10.12.1 按任务需要组织页面，避免多余内容

> 2026-10-30 用户确认并补充：页面和弹窗应保留必要功能，省略明显多余的内容；可能有用但是否需要尚不明确的内容，先沟通再决定。员工选择弹窗中的搜索、筛选属于必要功能，两条重复操作说明不需要。

- **必要功能正常实现。** 根据当前任务保留或实现搜索、筛选、业务必需字段、主要操作及必要的分页等功能；不因追求简洁而删减，也不为每个明确必要的控件逐项询问。
- **明显多余的内容默认不加。** 控件和布局已经表达清楚的操作，不再重复增加说明段落、教学提示或正常状态播报；不为“美化”或“显得完整”堆叠横幅、卡片、图标、徽章、动效等元素。例如本弹窗的“选择后再确认”“当前显示前N位，请缩小筛选范围”等常驻说明，按本次要求省略。这不等于禁止其他页面展示业务确需的计数或分页信息。
- **存在取舍的新增内容先沟通。** 对可能有帮助但并非明确必需、必要性无法确定，或会增加信息负担和操作步骤的内容，先简短说明它解决什么问题、为什么建议增加及相应代价，按用户当前沟通节奏确认是否添加。不要先做出来再让用户删，也不要把明显冗余的内容逐项拿来询问；其他不依赖该决定的工作继续推进。
- **必要状态按实际情况出现。** 加载、空结果、错误、权限受限和必要的风险确认就近、简短展示，帮助用户理解当前状态并继续操作；不将正常使用过程写成常驻教学，也不以精简为由隐藏错误或取消必要保护。
- **沿用已确认设计，移除多余占位。** 不为增加装饰擅改既有视觉风格。删除说明时一并移除专用容器、空白占位和无效引用。新增内容前先判断：它是否帮助完成当前任务，是否已由现有界面表达，是否值得占用页面空间或增加操作。
- 本规则用于后续开发和用户明确要求修改的范围，不授权自动清理全站既有页面或改写已确认设计。

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
5. 检查常规按钮、单行表单控件、筛选区控件和工具栏控件的实际渲染高度是否为 `32px`；分页控件为 `28px`，分页区为 `40px`，并核对每页数量选择器、页码、前后页按钮及焦点外圈均完整可见。
6. 页面要求兼容 1440 时，再以 `1440 × 900` 检查 `80px` 常驻主栏、二级浮层不挤正文、内容边距和表格内部横向滚动。
7. 检查加载、空数据、错误、无权限、选中、悬停、焦点、禁用、分页和横向滚动状态。
8. 已知的无关测试失败应单独报告，不得为了让全量检查通过而修改任务范围外的模块。

只有在代码检查、业务功能和真实浏览器视觉验证均通过后，才可以宣布完成。项目能编译不等于列表页已经完成。

## 10.14 通用业务弹窗组件

- 后续新增或修改的表单、详情、配置、预览和业务处理弹窗统一使用 `AppWindowDialog`，不得继续直接使用 `ElDialog`。
- 组件必须支持拖动、右下角调整大小、最小化、最大化、恢复和关闭，并在浏览器尺寸变化后把窗口限制在可视区域内。
- 弹窗初始宽度和高度由调用页面根据业务内容显式传入；组件最小尺寸默认为 `360 × 180px`，距视口四周至少保留 `16px` 安全边距。
- 普通弹窗整体（含标题和底部按钮）最多占浏览器高度的 80%，内容未达到该上限时自动增高，不得因偏小的调用高度或正文另设限高而提前出现滚动条。显式高度作为工作区下限，也必须服从 80% 上限；最大化和用户主动调整大小后使用可视区域边界。
- `.el-dialog.app-window-dialog` 根节点 `padding` 固定为 `0`；标题栏高度为 `44px`，内容区和底部操作区分别管理自己的间距与滚动，不依赖根节点内边距。
- `.app-window-dialog__actions` 绝对定位于窗口右上角，使用 `top: 0; right: 0; width: 96px; height: 32px`；最小化、最大化、关闭按钮均为 `32 × 32px`，图标为 `16 × 16px` 并在按钮内水平、垂直居中。
- 标题栏右侧必须为三个窗口控制按钮预留至少 `104px`，标题过长时使用省略号，不得与控制按钮重叠。
- 弹窗整体达到 80% 上限后，只允许超出的内容区内部滚动；标题栏和底部操作按钮保持可见。表格、图片与 PDF 的专用查看区保留自身滚动边界。
- 提交过程中可以通过 `showClose`、`closeOnClickModal` 和 `closeOnPressEscape` 阻止误关闭，但不得破坏最小化、最大化和视口自适应能力。
- 仅包含一句提示和确认/取消操作、且不承载表单或业务详情的系统级确认，可继续使用 `ElMessageBox`；其余业务弹窗必须使用 `AppWindowDialog`。
- 外圆角 `5px`、`1px #DDD6C9` 边、表面 `#FCFBF7`；标题 `16px / 22px`、字重 `600`；内容内边距 `16px`；底部上 `6px`、下 `8px`、左右 `24px`，按钮间距 `10px`。32px 单行按钮对应底栏约 47px（含上边框），不设置额外固定高度；多行内容自然增高。
- 蒙层为 `34%` 深色；窗口内按钮保留 `2px #3898EC` 外焦点圈和 `2px` 偏移，不被外框裁切。处于活动且未最小化的模态窗口约束 Tab 焦点；关闭后恢复触发位置。Esc、蒙层关闭及未保存保护按页面原规则，不擅自放开。

## 10.15 按钮、图标与通用焦点

> 2026-10-17按钮动态反馈：共享样式通过 `erp-button-motion` 显式启用，用于客户列表及10.2.4登记列表的实体筛选/工具栏按钮，兼容组件库与原生按钮。精细指针悬停180ms上浮1px并轻微提亮，按住80ms缩至0.98，松开回到悬停、移出恢复默认；不循环呼吸、不改变32px布局高度。禁用、加载、文字、链接、行操作按钮不参与；触屏/粗指针不启用位移，减少动态和打印无过渡。时间及缓动集中为共享变量，不修改一级D+B、二级A+D菜单动效。键盘焦点保持既有清晰外圈。

> 2026-10-17质感修正：共享主按钮使用冷蓝纵向渐变、顶部内高光和柔阴影，次按钮使用冷白玻璃渐变；所有颜色/渐变/阴影由主题用途变量提供，暖色也有对应槽位。圆角8px。文字按钮、链接按钮、朴素按钮和禁用态不套实体渐变表面。用户明确保持原按钮与输入高度，不因质感修改尺寸、业务或菜单动效。此项替代旧纯色主按钮外观。

> 2026-10-16 C4确认：本节及10.16、10.17的共享控件采用冷色状态，替代旧暖色；尺寸、焦点、事件、校验与禁用规则保持。错误及危险动作保留红色，不套Tag色槽。

- 常规按钮与单行控件高 32px，分页区控件按 10.10 为 28px，通用圆角 5px；品牌按钮、普通浅底、冷色次按钮、危险实心和文字按钮按任务强调程度选用。不能仅凭按钮名称强绑配色，同一区域避免多个高强调主按钮。
- 按下态只在按住时生效；松手仍停留恢复悬停，移开恢复默认。持续选中是独立状态，不借用按下色。

| 类型 | 默认背景 / 边框 | 悬停背景 / 边框 | 按下背景 / 边框 | 文字 |
| --- | --- | --- | --- | --- |
| 品牌主按钮 | #476F98 / 同背景 | #3C628A / 同背景 | #315473 / 同背景 | #FFFFFF |
| 普通浅底 | rgba(255,255,255,.60) / #C5D5E4 | #E8F0F7 / #9FB6CC | #D9E5F0 / #9FB6CC | #111111 |
| 冷色次按钮 | rgba(255,255,255,.60) / #C5D5E4 | #E8F0F7 / #9FB6CC | #D9E5F0 / #9FB6CC | #111111 |
| 危险实心 | #B53333 / 同背景 | #9F2D2D / 同背景 | #862626 / 同背景 | #FFFFFF |
| 文字按钮 | 透明 / 无可见边框 | 透明 / 无可见边框 | 透明 / 无可见边框 | #476F98 → #3C628A → #315473 |

- 普通浅底与次按钮采用同一套冷色状态，原按钮用途及强调层级不变；默认白色60%仅作用于背景，不降低文字透明度，不为每个按钮新增背景模糊；需要不透明回退时用 #F5F8FB。
- 有边框按钮均为 1px 边。危险实心用于需强提醒的破坏性动作，不任意为普通动作加红。文字按钮悬停、按下有下划线，禁用后无下划线、保持透明底。
- 有边框按钮禁用统一底 #E2EAF2、字 #617182、边 #C5D5E4；文字按钮禁用仅灰字。透明度保持 1，不响应悬停/按下、点击/键盘操作，Tab 跳过；原因就近可见，不能仅依赖禁用控件悬停。
- 键盘焦点为 2px #3898EC 外圈、偏移 2px；保留外侧空间，不能被裁切。普通输入框聚焦用 1px 蓝边；错误输入框保留红边并加此蓝外圈。
- 常规图标按钮 32 × 32px、SVG 16 × 16px，分页前后页按钮尺寸按 10.10；整体与图形都水平垂直居中，三点参数见 10.9。按钮有可读名称，悬停/聚焦显示名称气泡，禁用原因仍在旁边说明。
- 加载按钮保持所属类型的默认配色、原宽高，显示转圈和“处理中…”，停止悬停/按下变色并保留当前焦点。拦住重复点击、Enter、Space 及表单提交入口；结束依据真实请求结果。加载不等同普通禁用，审核小样的 2 秒和 140px 宽度不是全局规则。

## 10.16 文本输入、只读禁用与悬浮提示

| 状态 | 背景 | 文字 | 普通边框 | 交互 |
| --- | --- | --- | --- | --- |
| 可编辑 | rgba(255,255,255,.60) | #111111 | 1px #C5D5E4 | 可修改；焦点边 #3898EC |
| 只读 | #E8F0F7 | #111111 | 1px #C5D5E4 | 可聚焦、选取复制；不可修改，焦点蓝边且底不变 |
| 禁用 | #E2EAF2 | #617182 | 1px #C5D5E4 | 不可操作，不响应悬停/按下/点击焦点，Tab 跳过 |

- 常规单行输入高 32px，分页区内按 10.10 为 28px，圆角 5px；悬停边 #9FB6CC，不加粗、不叠第二圈边。只读标签明确“只读”，禁用鼠标表示不可操作、原因就近说明，不整框减透明度。文本域沿用上述状态；选择器按 10.17 专门实现，只读不能机械套原生 select 的 readonly。
- 可编辑输入的白色60%仅作用于背景，不降低整个控件透明度、不新增逐个控件的背景模糊；需不透明回退时使用 #F5F8FB。
- 错误输入保持可编辑输入的正常表面，用 1px #B53333 红边和错误图标；聚焦仍红边，并加 2px #3898EC 外圈、偏移 2px。
- 字段错误和普通说明使用脱离文档流的悬浮气泡，不增加说明行、不挤下方内容。共同参数：表面 #F5F8FB、圆角 5px、文字 12px / 18px，上下内边距 8px、左右 12px，最大宽 300px 且受视口约束。普通说明为 #111111 字和 1px #C5D5E4 边；错误为 #B53333 字和 1px 红边。
- 鼠标移入、聚焦或点击图标可显示；同一时刻只显示一个，允许移入气泡阅读。支持 Esc 和外部点击关闭，Esc 后不得因仍悬停/聚焦立即重开；需新的主动触发。按视口翻转、滚动重定位，避免被容器截断。重要业务规则须持续可见，不仅放在气泡中。
- 必填星号 #B53333 放标签前，标签仍正常文字色，并解释“带 * 的字段为必填”。初始空白不自动全部变红，实际校验失败再显示错误。哪些字段必填、何时校验按模块既有确认。
- 占位文字 #617182，只放简短示例；输入后的实际内容为 #111111，字段标签持续保留。单位、格式限制和重要操作要求不能仅放占位提示。

## 10.17 选择与高级表单控件

### 下拉与选项

- 常规输入区 32px，分页区的每页数量选择器按 10.10 为 28px；圆角 5px，底 rgba(255,255,255,.60)、1px #C5D5E4 边、字 #111111、箭头 #617182；聚焦蓝边，悬停边 #9FB6CC 且不加粗。只读用 #E8F0F7 / #111111，只展示值、可聚焦复制、不展开/清空；禁用用 #E2EAF2 / #617182、不展开且 Tab 跳过。
- 面板底 #F5F8FB、1px #C5D5E4 边、圆角 5px；选项高 32px，列表区最高 240px，超出内部滚动。至少与触发控件同宽，长文本可增宽但不超视口；浮层不推动正文，优先向下、空间不足向上或限高，避免被祖先容器裁切。
- 普通选项字 #111111；悬停/键盘活动底 #E8F0F7，选中底 #D9E8F6、#476F98 字和勾，选中再悬停保留选中底。禁用字 #617182、底不变、无悬停/选择，补“不可选”或具体原因。
- ↑↓移动活动项、跳过禁用，不立即改值；Enter 确认并关闭，Esc/Tab 关闭。单选面板与多选面板的提交方式不同，按下节执行。

### 单选与复选

- 单选视觉 14 × 14px、圆形；未选底 #F5F8FB / 边 #C5D5E4；选中 #476F98 边加 6px 钢蓝圆点。标签字 #111111，操作区至少高 32px，可点击文字；悬停仅改钢蓝边，焦点沿用蓝外圈。组内只选一个，同组方向键换选。
- 复选视觉 14 × 14px、圆角 2px；未选底 #F5F8FB / 边 #C5D5E4；勾选和半选底/边 #476F98，勾/横线 #FFFFFF。悬停、焦点及标签操作区沿用单选，Space 切换；半选表示子项未全选，不新增业务值。
- 两者禁用为 #E2EAF2 底 / #C5D5E4 边 / #617182 字及圆点、勾、横线，保留原状态、不可改、无悬停变化、Tab 跳过；原因就近显示。复选框方框在操作区/34px 行中居中，勾和半选横线在 14px 画布内居中，普通/半选/禁用逐态验收。

### 多选、日期、数字与文本域

- 多选输入区保持 32px / 5px，选 1 项显示名称，多项显示“已选 N 项”，不叠标签撑高；展开查看完整名称逐项勾选，选项 32px、复选框 14px / 2px 且居中。沿用选项颜色；↑↓移活动项，Space 勾选并保持面板，Enter 完成关闭，Esc/Tab 关闭。只读展示完整值可复制、不展开/删除；禁用不操作，不由此新增 Tag 配色。
- 日期输入区沿用 32px / 5px、冷蓝灰边和蓝焦点。日历格 32 × 32px，悬停 #E8F0F7，选中钢蓝底 / #FFFFFF 字，今天为钢蓝描边；禁用灰底灰字不可点。日历面板为表面底、1px 冷蓝灰边、5px 圆角，按视口上下避让；只读可复制但不展开，禁用不聚焦。日期格式、范围和时区按模块。
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

2026-10-19 短消息专项确认：`ElMessage` 采用[已确认动态预览](docs/designs/message_style_preview_20261019/preview-v3.html)。单行最小高 56px、最小宽 340px（不超视口减 32px）、8px 圆角、单层 1px 边框；上下 13px、左右 20px（窄屏 16px）内边距，图文间距 12px，文字 15px / 22px，图标 28px。底色沿用主题状态色加深后的第二版；图标为双色实心底座、白色符号和淡色外环。成功轻弹并显现勾选、警告最大 ±4° 轻摆、错误最大 ±2px 轻震、信息轻弹；每次出现只动一次，时长 420–560ms，减少动态效果时静止。完整色值计算与验收见[专项记录](docs/designs/message_style_preview_20261019/README.md)。

本次仅替换短消息的外观与图标动画，位置、显示时长、关闭、悬停暂停、分组和播报行为继续沿用现有组件及调用参数。下列旧版短消息尺寸与颜色已由本次确认替代，其他旧版行为要求保留为历史设计目标，不代表本次已实施；行内持续提示条不在本次范围。

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
