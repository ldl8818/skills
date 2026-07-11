# Privacy
The public Skill repository and private memory repository are separate assets.

## Data that may be captured
- Explicit user correction prompts, when correction capture is enabled.
- Shell command failures, only when error capture is enabled.

Captured text is truncated, redacted for common credential patterns and marked untrusted. Redaction cannot identify every form of personal or proprietary information, so persistence should be disabled for sensitive or externally controlled material.

Only a correction answer explicitly approved through the 2.2 `review approve`
command may be injected into later Agent sessions. Approval is a trust decision:
review the wording and choose `global` or a specific `project:/absolute/path`.
Historical Markdown rows are audit-only until explicitly reviewed under this
contract. Injection can be disabled without deleting history by setting
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
