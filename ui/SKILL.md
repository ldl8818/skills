---
name: ui
description: "Produces distinctive production UI and screenshot-grounded visual polish while eliminating generic AI design defaults. Use when building or restyling pages, components, dashboards, or typography. Not for backend logic, runtime bugs, or print/document typesetting."
when_to_use: "做组件, 做一个产品页面, 这个按钮不好看, 字体不协调, 卡片间距不一致, 这张截图的视觉层级不清楚, 不好看, 不和谐, 不清晰, 很丑, 很怪, 很傻, 突兀, 不协调, 字体, 排版, UI, 截图, build page, create component, make it look good, screenshot with visual complaint, font looks wrong"
dispatch_intent: "UI, component, page, visual interface, frontend, artifact-grounded screenshot aesthetic polish"
license: MIT
metadata:
  version: "5.0.0"
  source: local
  zh_description: "创建或精修产品页面、组件与视觉细节，内置反 AI 审美禁令与真实渲染验收。"
---

# UI: Distinctive Production Interfaces

If it looks like a default model output, fix it before handing off. Treat subjective visual complaints ("很怪", "很傻", "突兀", "不协调", "不好看") as aesthetic rejections to resolve visually -- unless evidence points to a broken render, crash, race, or state regression, which belongs to debugging. Route shippable documents (reports, slides, paged PDFs) to a document/presentation workflow rather than hand-rolling UI layouts.

## 1. Pick the Right Mode

Load a mode reference only when it matches; building a new surface starts at Section 2:

| Request | Action |
|---|---|
| Bounded tweak to an existing screen (spacing, alignment, contrast) | Load [references/mode-quick-fix.md](references/mode-quick-fix.md) |
| Screenshot supplied to iterate against | Load [references/mode-screenshot-iteration.md](references/mode-screenshot-iteration.md) |
| Generated image asset (diagram, cover, social card, illustration) | Load [references/mode-generated-asset.md](references/mode-generated-asset.md) and delegate generation to the installed image capability |
| New page, component, or visual system | Follow Section 2 below |

## 2. Ground in the Product First

- **Existing product comes first**: Before inventing styles for a new panel, dialog, sheet, or component inside an existing app, inspect sibling components and theme/token files (`tokens.css`, `theme.ts`, global styles) and lift exact hex codes, spacing scale, typography, and radii. Never approximate from memory.
- **Existing native app exception**: On macOS / iOS / Android apps with a coherent visual identity, default to incremental craft (spacing, alignment, states, typography hierarchy, copy tightening). Never propose a wholesale platform restyle unless explicitly requested. For native motion/press curves, load [references/design-native-motion.md](references/design-native-motion.md).
- **Compact direction lock (new surfaces only)**: Infer as much as possible from project code, screenshots, and conversation before asking at most 2 concise questions on material ambiguities. State in 3 lines before coding:
  1. **Visual thesis**: mood, material, and energy in one specific phrase (not "clean and modern"; if referencing Linear/Vercel/etc., name 3 concrete properties: radius, surface depth treatment, accent family).
  2. **Content / structure plan**: utility surfaces (app shells, dashboards) use orient -> status -> action with no marketing hero unless requested.
  3. **Interaction thesis**: `none` with reason, or 1-3 purposeful micro-interactions.
- **Load targeted design specs on demand**: Load [references/design-reference.md](references/design-reference.md) for new visual systems, app shells, UI copy cuts, or multi-option palettes; load [references/design-data-viz.md](references/design-data-viz.md) for dashboards and charts.

## 3. Anti-AI-Slop Hard Rules

Apply in every mode unless the committed direction deliberately breaks one (and explains why):

- **Absolute bans**: no thick colored side-border card accents, no gradient text, no default glassmorphism cards, no reflex purple-to-blue/cyan-on-dark palettes, no generic 3-equal-card grids or centered hero with side-by-side generic CTAs, no modal escapes for ordinary overflow, no `transition: all`, and no layout-property animations (`width`/`height`/`top`/`left`).
- **Motion discipline**: Frequency governs animation -- nothing keyboard-initiated or triggered hundreds of times a day should animate (motion reads as lag). Every user action still needs immediate visual acknowledgment (selected, open, loading, or subtle press state); hover alone is not activation feedback.
- **Typography & density craft**:
  - Never rely on `…` ellipsis truncation for fixed metric/label slots -- format compactly or structure the layout to fit.
  - Tighten wording or container width to avoid awkward single-word orphan lines instead of shrinking font size.
  - Keep at most 3 distinct text styles inside a small card; establish hierarchy by order, weight, and spacing.
- **Punctuation**: Never output Unicode em-dash (`U+2014`) in UI copy.

When the user asks for options (or taste choices like icon, weight, accent), provide 2-3 genuinely distinct labeled variations rather than guessing blindly.

## 4. Aesthetic Review & Rendered Verification

Before reporting completion:

1. **AI Slop Test**: Check the rendered first viewport -- would a stranger immediately say "an AI made this"? Fix any reflex typography, default gradient, card boilerplate, or broken hierarchy.
2. **Real runtime check**: Use the shared `lookup` entrypoint to choose the browser surface for local UI verification (current desktop client's built-in browser panel when available, otherwise `ego-lite`), inspect the rendered component in relevant viewport and interaction states, and complete `lookup`'s preview/space closeout (temporary checks close by default; user-facing previews reuse one space). State any unavailable visual evidence honestly.
