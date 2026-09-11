# Hook adapters
Legacy Markdown history may be archived without changing Hook registration or injection. This does not disable candidate capture or v2 approvals. Since 3.1.2, authorized edits and moves of memory.md and corrections.md follow ordinary document permissions, without extra Hook approval. The verified ledger and mutating review commands remain guarded.

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

At `SessionStart`, the common Hook leaves free-form `memory.md` out unless explicitly enabled, then
selects only current v2 approvals by priority, lifecycle and global/repository/
project scope. All dynamic sections share one estimated-token ceiling and
eligible answers are emitted in `<verified-corrections>`. A compact receipt
reports budget omissions, expired or due records, ignored v1 rows and malformed
events. Raw candidates and errors are never read as instructions. Malformed
approval data fails closed for that session and is also reported by `doctor`.
Without a knowledge catalog, in the default `resume_mode=skip`, a hashed session receipt stores only the digest
of context actually emitted. An unchanged resume is silent; changed context is
emitted once with an explicit invalidation marker, and an empty replacement emits a
clear marker so revoked or promoted rules do not survive in the resumed conversation.
Without a catalog, a missing session ID stays silent on resume because there is no safe identity against which to compare it. With a catalog, missing identity falls back to repeated safe output.

At `PreToolUse`, writes to the authority file (the verified JSONL ledger)
and shell-invoked approval commands emit an `ask`
permission decision (2.3.0) instead of a hard block: Claude Code shows its
permission dialog and the user approves or rejects that specific call. The
approval happens in the client UI, so in-session text — including injected
content — cannot forge it.

At `Stop`, reaching the pending-candidate threshold emits a top-level
`systemMessage` JSON object. It only shows the review reminder to the user; it
does not return `decision: "block"`, continue the conversation, or promote any
candidate. The reminder is throttled to once per configured interval rather
than repeated at every stop or injected at session start. Claude Code requires non-empty successful `Stop` stdout to be one
valid JSON object, so plain-text or XML reminders are invalid.

At `PostToolUse`, error capture relies only on structured failure state such as
a non-zero exit code or client error flag. Words like `error` or `failed` inside
successful output are ordinary text and do not create error records. If a
client version exposes only an opaque response string, the adapter deliberately
skips error capture on that client instead of guessing from prose; `doctor`
reports that degraded contract when command-error capture is enabled.

## Codex
The installer uses the same lifecycle names but a separate adapter. It matches both `Bash` and `apply_patch` for `PreToolUse`, `Bash` for `PostToolUse`, ignores matchers for UserPromptSubmit and Stop, and always observes `startup|resume|clear|compact` for `SessionStart`; the common Hook suppresses an unchanged resume only when no knowledge catalog is present. Every managed command Hook has a 10-second timeout instead of inheriting Codex's 600-second default.

`PreToolUse` guards common relative, absolute and `$HOME` Shell writes to the configured verified JSONL store, mutating review commands invoked through an Agent shell, and `apply_patch` edits whose target path is one of those authority files. Shell tokenization joins adjacent quoted fragments before matching, so spelling `re''view ap''prove` cannot bypass the guard. Codex currently parses but does not support `permissionDecision: "ask"`; it reports the Hook as failed and continues the tool call. The adapter therefore returns `deny`. For an approval, the Agent gives the user one fingerprint-only `review approve-interactive` command at a time to run in a regular terminal outside the Agent tool loop; the CLI validates and displays that fingerprint before reading the distilled rule, scope, promotion target and lifecycle from interactive input. Candidate-derived text never becomes Shell syntax, and interactive approvals are not chained. Rejection, promotion and revocation commands contain only validated fingerprints, and legacy imports use `review import-legacy-interactive` with a validated legacy ID. Exact read-only `-h` and `--help` invocations remain available through the guard. Because arbitrary shell syntax
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

## Knowledge routing (3.1)

With a private catalog, SessionStart resets the knowledge stage, including resume, and compact restores eligible last-requested IDs or full-read pointers. UserPromptSubmit may emit reviewed original text independently of persistence. Both events share the configured final-output estimate, default1200 tokens; knowledge runs in an isolated one-second worker. See [knowledge contract](knowledge.md) for invalidation, source safety, deduplication and explicit reads. Existing PreToolUse guards are unchanged.

## Read-only Python inspection

Standalone Python `-c` and quoted heredoc commands are exempt from the authority-write guard only when their complete AST matches a small read-only subset: `pathlib.Path`, `read_text`, JSON parsing, text splitting, loops and printing. The guard parses source without executing it. Merely mentioning a protected filename or module in a string is not a write. Unknown code, dynamic execution, filesystem mutation, shell composition and output redirection keep the existing guard. Claude returns `ask`; Codex returns `deny` for guarded operations. This remains accidental-write protection, not a sandbox.

Read-only Python supports `startswith()` and negative indexes. Interpreter/reference matching is scoped to simple shell command segments (including newline, semicolon and logical separators); pipelines keep source and interpreter references together; expansion and heredocs retain conservative handling. The `[authority-guard]` message distinguishes possible detection from proven writes and directs file moves to the corresponding operation, not an unrelated review command.

## Exact hook trust after changes

Codex requires review and trust of the current hook definition after matcher or command changes. Use the normal `/hooks` interface to inspect the changed self-improving hook and enable that exact definition. Do not use bypass flags. Configuration wiring alone does not prove trust or execution; check a real next model request after startup, resume, clear or compact. Official contract: https://learn.chatgpt.com/docs/hooks .
