---
name: write
description: "起草、改写、校对或本地化用户明确要求处理的文案，保留原意、事实和作者表达。用于写文案、改稿、润色、去 AI 味或 release notes 文案；不用于研究抓取、发布执行、代码注释或实现任务中的附带文字修改。"
license: MIT
metadata:
  github_path: "skills/write"
  github_date: "09-06"
  github_hash: "2d1420da16d22794ba100183bbd4198fd9d0ba03"
  github_url: "https://github.com/tw93/waza"
  version: "4.0.0"
  update_policy: "frozen"
---

# Write

## Use when
The user explicitly requests drafting, rewriting, proofreading, localization or review of user-facing prose.

## Not for
Research or retrieval, publishing actions, code comments, or incidental labels and README text inside an implementation task.

## Outcome and evidence
Deliver the requested final text or scoped file edit, faithful to the author's intent and supported facts.
Use the supplied draft, audience, medium, requested language and verifiable product state.

## Rules
1. Preserve meaning, facts and the author's actual voice. Leave sentences alone when they already serve the request.
2. Do not invent quotations, experiences, opinions, emotions or product status to make text feel natural.
3. Match editing strength to the user's request, audience and medium. Resolve ordinary wording choices directly.
4. Treat supplied factual uncertainty as uncertainty. Verify material current claims when needed, or identify the missing source instead of manufacturing support.
5. Follow the user's and project's language conventions. Word lists and stylistic examples are guidance, not universal bans or numeric quotas.
6. Deliver the final text without an unsolicited edit commentary. File-edit tasks may include the change location and material verification limits.

## Conditional references
- Chinese prose: [references/write-zh.md](references/write-zh.md).
- English prose: [references/write-en.md](references/write-en.md).
- Bilingual copy: [references/write-zh-bilingual.md](references/write-zh-bilingual.md).
- Product localization: [references/write-product-localization.md](references/write-product-localization.md).
- Long-form work: [references/mode-long-form.md](references/mode-long-form.md).
- Release-note wording: [references/mode-release-notes.md](references/mode-release-notes.md).

## Optional typography check
Use `scripts/check-punctuation.sh --help` only when the user requests typography checking, project rules require it, or CJK/Latin punctuation consistency is part of the task.
Its warnings do not override quoted originals, identifiers or an author's approved style.

## Completion
The user has the requested text or edited file, with no fabricated facts or unrequested change in intent.
