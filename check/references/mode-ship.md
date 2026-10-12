# Ship and release readiness
Identify the authorized target: local commit, remote push, merge, package, registry publication or release. Existing authorization persists; one action does not implicitly authorize every distribution channel.
A commit/push-only task does not require tags, registry publication or release assets unless the change or project rules make them relevant.
Inspect current worktrees, precise changes, branch, remote and concurrent edits. Stage only task-owned paths when committing is authorized.
Use project instructions for required gates and affected distribution surfaces; see [release-surfaces.md](release-surfaces.md). Do not execute all possible tests.
Before publishing, verify artifact contents, versions and the relevant installed behavior. Prepare accurate release text and target parameters before any necessary final approval.
After external mutation, read back commit/branch, registry version, release assets or relevant remote state. CI still running is pending, not passed.
A timeout after an at-most-once publication leaves its state unknown. Reconcile through bounded read-only checks under the project's retry policy; report any unresolved state and never repeat publication merely to obtain a passing verification.
Keep source, package, CI and release acceptance separate. Report the achieved target and concrete blockers; no mandatory reaction or ceremonial signoff.
