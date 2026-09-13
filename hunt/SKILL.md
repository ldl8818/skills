---
name: hunt
description: "通过复现、证据和定向验证诊断并修复可观察的软件故障。用户报告报错、崩溃、测试失败、回归、性能异常或运行行为失效时使用；不用于泛化代码审查、纯审美偏好或新功能设计。"
license: MIT
metadata:
  github_path: "skills/hunt"
  github_date: "09-06"
  github_hash: "2d1420da16d22794ba100183bbd4198fd9d0ba03"
  github_url: "https://github.com/tw93/waza"
  version: "4.0.0"
  update_policy: "frozen"
---

# Hunt

## Use when
Investigate an observable error, crash, failing test, regression, slowdown or broken runtime behavior.

## Not for
General code review, aesthetic preferences, or new feature design. A screenshot is evidence only when it demonstrates a concrete failure.

## Outcome and evidence
Establish the cause using a reproducible path or the closest reliable signal, then verify the authorized fix.
Use source traces, logs, runtime state, relevant tests and the affected client or renderer.

## Rules
1. Establish expected versus observed behavior and the affected version or environment. A diagnosis-only request does not authorize a production fix; an ongoing repair authorization persists across status questions.
2. Before applying a production behavior fix, establish evidence for its root cause. Temporary logs, assertions, probes, minimal tests and isolated experiments are allowed during diagnosis.
3. Design experiments to distinguish hypotheses. When evidence contradicts the current model or repeated attempts fail, rebuild that model and continue investigating rather than guessing another patch.
4. Change the failed behavior within the authorized scope. Inspect same-cause siblings when evidence warrants it; do not refactor unrelated neighboring logic.
5. Choose regression protection by recurrence probability and impact. Verify the failing path and relevant boundaries without mechanically adding a permanent test for every reversible edit.
6. Preserve existing work. Demonstrate before/after behavior through a safe fixture or isolated copy when needed, without mandatory stash, revert or reset.
7. Continue until the cause and authorized fix are verified. Stop only for an actual unavailable permission, device, user-only fact or irreplaceable input; state the missing evidence and what has been ruled out.

## Conditional references
- Cache, queue, subprocess, lifecycle or platform failure patterns: [references/failure-patterns.md](references/failure-patterns.md).
- IME, Unicode or cursor bugs: [references/ime-unicode.md](references/ime-unicode.md).
- Discriminating probes or native freezes: [references/logging-techniques.md](references/logging-techniques.md).
- Generated output or renderer faults: [references/rendering-debug.md](references/rendering-debug.md).

## Completion
Explain the evidenced cause, scoped change and verification result. Source-only checks do not prove a native freeze or rendered regression fixed.
