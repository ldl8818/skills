# Long-Running Agent Stop Conditions

Loaded from `health` Step 1c when the project uses `/loop`, autonomous agents, or any long-running agent flow. Skip entirely for projects without one.

The project must define explicit stop conditions. An agent that never stops is a budget and safety incident waiting to happen.

Audit for these four hard stop signals; flag the absence of each as a Structural finding:

1. **No progress across two consecutive checkpoints.** Same files touched, same errors logged, no new commits/tests/output. Reassess the evidence model and surface the current state; stop only when the declared budget, authorization or an actual blocker requires it.
2. **Repeated identical failure.** Same stack trace, same error message, same failed assertion three times in a row requires revisiting the hypothesis rather than repeating the same action; new evidence may justify further work.
3. **Cost or token budget exceeded.** Honor any explicit user or project per-run budget (tokens, API spend, wall-clock minutes). Loop exits when the budget is hit, not when work is done.
4. **External blockers.** Merge conflict on the target branch, dependency lock the agent cannot resolve, missing credential, network unreachable. Stop the affected action only when it cannot be resolved within the existing authority; continue independent work and use bounded retries when new evidence supports them.

The stop conditions should live in tracked project docs (`AGENTS.md`, the loop's launch script, or a dedicated config), not only in the agent's prompt. Prompts are forgettable; tracked config is enforceable. Recommend hooks (PostToolUse on the relevant tools) over prompt instructions when the project supports them: a supported hook can enforce a covered operation mechanically, while its actual event coverage must still be verified. Confirm the host's hook coverage before recommending one: some agents only fire PostToolUse for a subset of tools (for example, a runtime may match shell/Bash only), so a fixup that must run after file edits belongs on a Stop or session-end hook there instead.

Existing user and project budget, recovery and authorization contracts govern the action taken at a checkpoint. A repeated failure requires evidence reassessment, not an automatic stop while meaningful authorized progress is available. Do not invent a paid budget or kill a user process as an audit action; report the gap and apply the authorized workflow.
