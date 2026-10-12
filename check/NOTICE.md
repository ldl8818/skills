# Source and modification notices

## Current foundation

The main `SKILL.md` is a locally modified derivative of Alibaba's official [Open Code Review Skill](https://github.com/alibaba/open-code-review/blob/v1.12.13/skills/open-code-review/SKILL.md), adopted from release v1.12.13, commit `fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`.

Copyright 2026 alibaba/open-code-review Contributors. The upstream Apache License 2.0 is retained in [LICENSE](LICENSE). The separately installed OCR executable is maintained by Alibaba; its implementation is not copied into this Skill.

Local modifications preserve the `check` name and Chinese routing description, condense the official English workflow, add task-dependent coverage and resource/result validation, honor existing repair authorization, and retain affected-risk verification and delivery contracts. Local scope tooling is an adapter, not upstream engine code.

## Previous Waza foundation

Before this foundation change, `check` was adapted from [Tw93/Waza](https://github.com/tw93/Waza/tree/318d6c2c219894798b09c2b39d7f83d0be1a313c/skills/check).
The original registered source was `2d1420da16d22794ba100183bbd4198fd9d0ba03`; later changes were selectively adopted from `318d6c2c219894798b09c2b39d7f83d0be1a313c`. The preceding local check 4.1.0 implementation is preserved in repository history at `ee13e3c736151bae968fc59d3f1a911dd51bb753`.

Copyright (c) 2026 Tw93. The original MIT terms remain in [LICENSE-WAZA](LICENSE-WAZA). Retained or adapted Waza-era material includes `scripts/run-tests.sh`, `references/review-patterns.md`, `references/release-surfaces.md`, `references/public-reply.md` and local review/repair/verification principles incorporated into the main workflow. Their notices are retained; these files are not presented as unmodified Alibaba originals.

The former audit/triage/ship mode files and duplicate evidence generators are retired. Their useful scope, authorization and verification behavior is incorporated into the single official-workflow-based entry.
