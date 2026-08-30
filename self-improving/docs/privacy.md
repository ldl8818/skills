# Privacy
The public Skill repository and private memory repository are separate assets.

## Data that may be captured
- Explicit user correction prompts, when correction capture is enabled.
- Structured Shell command failures, only when error capture is enabled. Words such as `error` in successful output do not count; a client that exposes only opaque output text is skipped instead of guessed.

Messages that begin with client-injected system tags (task notifications, reminders, slash-command echoes), prompts longer than 1500 characters, and keywords that appear only inside fenced code blocks are never treated as corrections, which also keeps machine-generated paths out of the candidate inbox. Captured text is truncated, redacted for common credential patterns and marked untrusted. Each candidate also stores the keyword that triggered capture with a short window of surrounding text, so a reviewer can see why it was filed; that window is redacted and capped the same way. Redaction cannot identify every form of personal or proprietary information, so persistence should be disabled for sensitive or externally controlled material.

Only a current v2 correction explicitly approved through `review approve` may
be injected at a later `SessionStart`. An unchanged resume is suppressed by a
per-session content digest; the digest contains no rule text. Approval is a trust decision: review the
wording, choose global/repository/project scope, name its formal promotion
target, and accept review and expiry dates. Historical v1 and Markdown rows are
audit-only under the default configuration. Approval, promotion and revocation history lives in one append-only
JSONL authority file, avoiding a split state between Markdown and runtime.
Injection can be disabled without deleting history by setting
`injection.include_verified_corrections` to `false`.

The Hook guard prevents common accidental Agent writes and standard shell
approval commands. It is not a privilege boundary against arbitrary code
running under the same operating-system account. For stronger tamper evidence,
keep the private memory directory in a private version-controlled repository and
review changes outside the Agent session.

The software never creates a remote or pushes private memory automatically.

Initialization refuses filesystem root, HOME, the public Skill directory, and
unrelated non-empty directories. Data deletion additionally requires the
software's root marker and confirmation matching the full resolved path.
