<!-- SPDX-License-Identifier: Apache-2.0 -->
# Alibaba OCR adapter

Load when deep review needs OCR assistance. Check determines scope, risk, findings and verification; Delegate supplies selection metadata and file-specific rules without making model calls. Review uses the current host session and its existing subscription or billing arrangement.

Pinned interface: [v1.12.13](https://github.com/alibaba/open-code-review/releases/tag/v1.12.13), commit `fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`; [official Delegate Skill](https://github.com/alibaba/open-code-review/blob/v1.12.13/skills/open-code-review-delegate/SKILL.md). Licensing: [NOTICE.md](../NOTICE.md).

## Selection and rules

Reuse a compatible native executable, such as the resolved `~/.local/bin/ocr`. Check version/flags when first establishing compatibility or after an installation change; do not repeat probes for unchanged setup.

For a diff review, obtain a preview and reconcile it with the task scope. Fetch rules for the relevant paths in coherent batches:

```text
ocr delegate preview --repo <repo> --format json --background <concise-context>
ocr delegate rule --repo <repo> --format json --background <concise-context> -- <path-1> <path-2>
```

Use literal argv and capture stdout to a private task file. Add fixed `--from/--to` or `--commit` arguments before `--` to both commands for historical targets. Delegate has no `--output`, `--audience`, `--preview` or model-budget flags. For a whole-file audit, use the task's full-file inventory and `delegate rule`; a change preview does not cover unchanged files.

Preview v1 returns `reviewable_files` and `excluded_files`. Rule output returns `groups` with `files`, `rule`, `source` and `pattern`. Read every applicable distinct rule once, then inspect actual code and business behavior. Success from either command proves neither review completion nor coverage.

Use [review-scope.md](review-scope.md) when reconciling a larger scope or configuring `--rule <temporary-rule.json>`. OCR defaults exclude some tests/docs. The task inventory remains authoritative: inspect omitted content directly, or use a temporary filter when it makes rule retrieval useful. Do not chase identical lists for their own sake. Preserve applicable project rules; scope filters and language rules do not override the user's task or project contracts.

## Failure and completion

A missing executable, incompatible schema or rule retrieval error leaves OCR assistance unavailable; report the observed limit and continue useful host review. An empty preview does not mean the requested scope is clean. Do not auto-install, upgrade or configure a provider during ordinary review.

Report `Delegate + host review` only after the host actually inspects the task scope; otherwise state remaining coverage. Use `host-only review` when OCR was unnecessary or unavailable. API absence blocks neither path. Do not promise the full engine's review rounds, filtering or benchmark results for Delegate.

Full engine commands, provider configuration, budgets and installation are isolated in [OCR完整引擎.md](OCR完整引擎.md). Load that reference only for the corresponding explicit request or authorized setup. Do not extract host login credentials or introduce an OAuth bridge; an experimental subscription-authentication proposal is not an approved engine migration.
