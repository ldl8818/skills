# Hook adapters
Claude Code and Codex payloads are normalized before core memory logic runs.

The adapters are tested against sanitized payload fixtures captured from real
Claude Code and Codex sessions. Only field names and synthetic example values
are committed under `examples/hook-payloads/`; transcripts and user content are
never copied into the public repository.

At `UserPromptSubmit`, correction capture applies a pre-filter before keyword
matching: a message that begins with a client-injected system tag (such as a
task notification, an injected reminder, or a slash-command echo like
`<command-message>` / `<command-name>` / `<command-args>`) is not the user
speaking and is never treated as a correction; a prompt longer than 1500
characters is a document or a generated prompt rather than a correction and is
dropped before keyword matching; and keywords that appear only inside fenced
code blocks (pasted logs, diffs) do not trigger capture. Human text before an
appended reminder block still counts. Exact same-day repeats were already
deduplicated by fingerprint.

The length rule is the one rule that does not depend on knowing what a machine
message looks like, so client features that reuse the user-prompt channel are
filtered without enumerating their tags. English keywords (`remember`,
`stop doing`) do not match inside longer English words, so `remembering` in
generated prose is not a correction; they still match next to Chinese text.

Because keyword matching runs on the full prompt while the inbox stores a
truncated copy, every captured row also records the matched keyword and a short
window around it in the `Match` column, surfaced by `review list` and as
`matched` in `review list --json`. That is what lets a reviewer tell a real
correction from a stray keyword when the trigger falls outside the stored text.
The match text is redacted and capped like any other stored content and is not
part of the fingerprint.

## Claude Code
The installer wires `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and `Stop` while preserving existing groups. Every managed command Hook has a 10-second timeout.

At `SessionStart`, the common Hook validates the line and character budgets and
injects the small `memory.md` core. It then reads only approvals written by the
`review approve` command, filters them by the current project/global scope, applies
the configured count and character budgets, and emits them in a separate
`<verified-corrections>` block. Raw candidate and error files are never read as
instructions. If any approval-ledger event is malformed, verified-correction
injection fails closed for that session and `doctor` reports a hard failure.
When pending candidates reach the reminder threshold (3), `SessionStart` also
injects a review reminder that points the agent at the pre-review flow
(`review list --json`, draft rules and recommendations, then user-confirmed
batch approval). The reminder is guidance only; raw candidates are never
injected.

At `PreToolUse`, writes to the authority files (`memory.md`, `corrections.md`,
the verified JSONL ledger) and shell-invoked approval commands emit an `ask`
permission decision (2.3.0) instead of a hard block: Claude Code shows its
permission dialog and the user approves or rejects that specific call. The
approval happens in the client UI, so in-session text — including injected
content — cannot forge it.

At `Stop`, reaching the pending-candidate threshold emits a top-level
`systemMessage` JSON object. It only shows the review reminder to the user; it
does not return `decision: "block"`, continue the conversation, or promote any
candidate. Claude Code requires non-empty successful `Stop` stdout to be one
valid JSON object, so plain-text or XML reminders are invalid.

## Codex
The installer uses the same lifecycle names but a separate adapter. It matches both `Bash` and `apply_patch` for `PreToolUse`, `Bash` for `PostToolUse`, ignores matchers for UserPromptSubmit and Stop, and uses startup/resume matching for SessionStart. Every managed command Hook has a 10-second timeout instead of inheriting Codex's 600-second default.

`PreToolUse` guards common relative, absolute and `$HOME` Shell writes to the configured `memory.md`, `corrections.md` and verified JSONL store, approval/rejection commands invoked through an Agent shell, and `apply_patch` edits whose target path is one of those authority files. Codex currently parses but does not support `permissionDecision: "ask"`; it reports the Hook as failed and continues the tool call. The adapter therefore returns `deny`. For an approval, the Agent gives the user one fingerprint-only `review approve-interactive` command at a time to run in a regular terminal outside the Agent tool loop; the CLI validates and displays that fingerprint before reading the distilled rule and scope from interactive input. Candidate-derived text never becomes Shell syntax, and interactive approvals are not chained. Rejection and revocation commands contain only validated fingerprints, and legacy imports use `review import-legacy-interactive` with a validated legacy ID. Because arbitrary shell syntax
cannot be parsed safely with string matching, and specialized tools may bypass the default Hook path, this is an accidental-write guard,
not a complete sandbox or access-control mechanism. Code running as the same OS
user can deliberately call internal Python APIs or obfuscate a write. Keep
private memory under version control when audit and rollback matter.

Installation must preserve unrelated Hooks such as status or notification integrations. After Codex upgrades, run `doctor` and a real-session smoke test because Hook payload fields may evolve.

Codex 0.146.0 enforces the same successful `Stop` JSON requirement as Claude
Code. The shared adapter therefore emits the same non-blocking `systemMessage`
object on both platforms; XML is not a valid `Stop` response on either client.

`doctor` checks each managed Hook's command path, command type, matcher and
timeout before reporting the wiring as healthy. Its separate current-package
schema coverage is not proof that every event was produced by the latest client
launch or that a client supports a particular permission decision. End-to-end
smoke results must be reported separately from fixture replay.
