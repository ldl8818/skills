# Source and modification notices

## Primary foundation: Waza-derived local Check

Version 6.0.0 uses the locally maintained Waza-derived Check workflow as its primary foundation: task-based scope, evidence-based judgment, risk-proportionate verification and authorized repair/delivery. The preceding local baseline is [check 4.0.4](https://github.com/ldl8818/skills/tree/5478feb145ffdd6682f44a4607bdbb8affffdcce/check), before OCR was integrated.

The original registered Waza source is `2d1420da16d22794ba100183bbd4198fd9d0ba03`, path `skills/check`. Applicable updates were selectively adopted from [Tw93/Waza at 318d6c2](https://github.com/tw93/Waza/tree/318d6c2c219894798b09c2b39d7f83d0be1a313c/skills/check). The main metadata again points to that original registered source; it does not claim that local 6.0.0 is an upstream Waza release or an unchanged upstream snapshot.

Copyright (c) 2026 Tw93. MIT terms are retained in [LICENSE](LICENSE). The Waza-derived entry, `references/深入审查.md`, `references/review-patterns.md`, `references/release-surfaces.md`, `references/public-reply.md` and `scripts/run-tests.sh` retain this foundation with local adaptations.

Local changes add explicit lightweight/deep routing, requirement-and-scenario coverage, selective context loading, and OCR adapters. The old audit/triage/ship mode files and heuristic signal scripts remain retired; relevant judgment and verification contracts are retained without making broad audits or release actions part of every review.

## Secondary integration: Alibaba OpenCodeReview

OCR is an optional review tool, not Check's routing authority. The adapter contract comes from Alibaba OpenCodeReview [v1.12.13](https://github.com/alibaba/open-code-review/releases/tag/v1.12.13), commit `fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`, including its [official Skill](https://github.com/alibaba/open-code-review/blob/v1.12.13/skills/open-code-review/SKILL.md) and [Delegate Skill](https://github.com/alibaba/open-code-review/blob/v1.12.13/skills/open-code-review-delegate/SKILL.md).

Copyright 2026 alibaba/open-code-review Contributors. Apache License 2.0 terms are retained in [LICENSE-APACHE](LICENSE-APACHE). `references/open-code-review.md` and `references/OCR完整引擎.md` are locally modified integration references. The local `references/review-scope.md`, `scripts/review_scope.py` and `tests/test_review_scope.py` adapters remain Apache-2.0; they are not unmodified upstream engine code.

The separately installed OCR executable and its runtime rule text are maintained by Alibaba and are not vendored here. Delegate supplies selection and rules; the host performs model review. Full-engine execution remains an explicit option with its own provider and acceptance requirements.

## Transition history and distribution

Local 4.1.0 integrated OCR into the Waza workflow. Local 5.0.0 switched the primary workflow to Alibaba's official Skill; 5.1.0 selected Delegate to reuse the host session. Local 6.0.0 restores Waza-derived local orchestration while retaining the OCR adapters and independent scope accounting.

The Skill includes MIT and Apache-2.0 components; the frontmatter expression `MIT AND Apache-2.0` describes the combined distribution, not a choice to relicense either upstream's material. Keep both licenses and this notice when redistributing. Earlier license filenames were reorganized without removing their terms.
