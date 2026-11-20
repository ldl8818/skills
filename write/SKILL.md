---
name: write
description: "Rewrites and polishes Chinese or English prose, technical instructions, release notes, and product copy to remove AI tone while preserving the author's voice. Use when drafting, editing, localizing, or reviewing prose. Not for code comments or commit messages."
when_to_use: "改稿, 润色, 去AI味, 帮我写文案, 审稿, 文档review, 技术说明改写, 这段说明有歧义, 把这篇文章改得自然一点, 校对这份文案, 把更新内容写成发布说明, 指令消歧, clarify instructions, technical writing, 本地化文案, 多语言文案, i18n copy, localization copy, check this document, 推特, twitter, X推文, tweet, social post, draft, edit text, proofread, sound natural, polish, rewrite"
dispatch_intent: "Writing, editing prose, clarify technical instructions, polish, release notes, launch/social copy, remove AI tone"
license: MIT
metadata:
  version: "5.0.0"
  source: local
  zh_description: "起草、改写、校对和本地化中英文文案，去 AI 味并保留原声，内置标点检查脚本。"
---

# Write: Cut the AI Taste

Strip AI patterns so prose sounds human and direct. Do not perform "vocabulary upgrades"; cut filler, summary-tone, and synthetic phrasing while keeping the author's meaning and voice intact.

## 1. Core Stance

- **Over-editing is failure**: If a sentence is already clear and natural, leave it alone. Prefer subtraction over phrase-by-phrase replacement. On the author's own finished draft, default to typos, broken syntax, and obvious AI tells without flattening their style.
- **Keep the speaker**: Preserve authentic colloquialisms, stance, emotion, and deliberate series/brand wording. Remove synthetic PR buzzwords and translationese, not human conviction. Never rewrite attributed quotes or testimonials unless explicitly in scope.
- **Never invent first-person experience**: Every anecdote, metric, tool history, or quote must come from supplied material or real source artifacts. If drafting in the author's voice, read 1-2 of their existing pieces first.
- **Material gate before long-form drafting**: Count actual non-obvious material (real experience, numbers, quotes, verifiable facts) before choosing length. Common sense and restated points are not material. If sections lack substance, research first, ask at most 3 focused questions, or write a shorter piece -- never pad to hit a word count.
- **Shorter than the first draft wants to be**: Respect real surface limits (tweet fold lines, UI slots, release note length) up front.
- **Artifact-grounded claims**: Release notes, launch posts, product copy, and public replies must match actual current code, runnable artifacts, screenshots, or changelogs -- never plans or stale memory.
- **No silent restructuring**: Edit in place unless structural changes were requested (or long-form mode applies); keep frontmatter, links, image placeholders, and example blocks intact.

## 2. Language & Mode Routing

Detect language from the target text (not the prompt) and load only the matching reference files:

- **Chinese prose**: [references/write-zh.md](references/write-zh.md)
- **English prose**: [references/write-en.md](references/write-en.md)
- **Bilingual / CN-EN drift**: [references/write-zh-bilingual.md](references/write-zh-bilingual.md)
- **Chinese release notes / social posts**: [references/write-zh-release-notes.md](references/write-zh-release-notes.md) + [references/write-zh.md](references/write-zh.md)

Load a mode reference only when requested:

| Task | Reference / Rule |
|---|---|
| Release notes / changelog | [references/mode-release-notes.md](references/mode-release-notes.md) |
| Public issue / PR maintainer reply | [references/mode-public-reply.md](references/mode-public-reply.md) |
| Technical docs, CLI instructions, error copy | [references/write-technical.md](references/write-technical.md) and [references/技术说明消歧.md](references/技术说明消歧.md) |
| Long-form structural rewrite | [references/mode-long-form.md](references/mode-long-form.md) |
| Compare two drafts ("which is better?") | [references/mode-revision-review.md](references/mode-revision-review.md) |
| Multi-locale product / i18n copy | [references/write-product-localization.md](references/write-product-localization.md) |
| Document / PDF review ("审稿") | Check unauthorized privacy exposure, tone drift, CN/EN accuracy, leftover placeholders (`TODO`/`TBD`), and broken links |
| Paragraph flow ("段落连贯") | Fix unsignalled topic jumps and monotone rhythm with minimal bridging edits |
| Tweet / X post / launch thread | Apply [references/write-zh-release-notes.md](references/write-zh-release-notes.md) (lead with user value, one stance, natural rhythm, respect fold budget) |

## 3. Punctuation & Formatting Gate

- **No Unicode em-dash or en-dash**: Never produce `—` (`U+2014`) or `–` (`U+2013`) in editable prose (preserve verbatim quotes, code, URLs, and literal identifiers). In Chinese prose, when a dash is genuinely needed, use ASCII double-hyphen `--` following the user's typography convention; otherwise prefer commas, periods, colons, or parentheses.
- **Chinese/English spacing**: Use full-width Chinese punctuation with no spaces beside it; add a half-width space between Chinese and English letters; keep numbers adjacent to Chinese without extra spaces unless a project specifies otherwise.
- **Run the deterministic checker** on produced text before returning:

```bash
bash <skill-base-dir>/scripts/check-punctuation.sh --lang <zh|en|ja|auto> <file>   # or pipe via stdin
```

Fix real findings while preserving meaning; pass `--lang` explicitly for mixed-locale text.

## 4. Output

- Pasted-text rewrites: return the polished text directly; include a change list only when requested or on a finished author draft.
- Repository edits: verify the diff and report scoped changes plus check results. Code comments and commit messages stay outside this skill.
