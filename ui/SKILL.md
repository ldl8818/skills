---
name: ui
description: "创建或精修真实产品的网页、原生页面与组件，结合项目约定和实际渲染验证。用户明确要求做页面、修改界面、调整层级或按截图修正视觉细节时使用；不用于后端、文档排版、独立图片生成或运行时故障。"
license: MIT
metadata:
  github_path: "skills/ui"
  github_date: "09-06"
  github_hash: "2d1420da16d22794ba100183bbd4198fd9d0ba03"
  github_url: "https://github.com/tw93/waza"
  version: "4.0.0"
  update_policy: "frozen"
---

# UI

## Use when
Create a coded page or component, or correct visual hierarchy, spacing, typography, alignment or consistency using a reference or rendered interface.

## Not for
Broken clicks, crashes and state regressions; document typesetting; standalone image generation; backend work. Bare “design”, “style”, “排版” or “screenshot” does not establish a UI task.

## Outcome and evidence
Deliver the requested interface or visual correction.
Evidence includes current components, design tokens, the user's reference, and the actual rendered result at the relevant viewport and state.

## Rules
1. Inspect project conventions, existing tokens and comparable components before choosing a visual direction. Reuse the product's visual language unless the user asks to change it.
2. Translate the user's reference into observable differences in hierarchy, density, typography, color or layout. Avoid prescribing a universal aesthetic or adding a second design system.
3. Continue authorized implementation without a separate design approval gate. Resolve low-impact details from context; ask only about missing decisions that change the intended result.
4. Verify the real render. Compilation or source inspection does not establish visual correctness. If rendering is unavailable, identify precisely what remains unverified.
5. Check responsive behavior, focus, keyboard access, contrast, reduced motion and relevant empty/error/loading states in proportion to the change.
6. Keep interaction behavior and user content intact during visual edits. Use project-native components and motion conventions rather than obligatory effects.

## Conditional references
- Larger visual choices: [references/design-reference.md](references/design-reference.md).
- A supplied screenshot or visual complaint: [references/mode-screenshot-iteration.md](references/mode-screenshot-iteration.md).
- A small local visual fix: [references/mode-quick-fix.md](references/mode-quick-fix.md).
- Native animation: [references/design-native-motion.md](references/design-native-motion.md).
- Charts and dense data surfaces: [references/design-data-viz.md](references/design-data-viz.md).

## Completion
The implementation matches the requested change and relevant rendered evidence has been inspected.
Report the changed surface, meaningful verification and any real limitation; no named design philosophy or signature interaction is required.
