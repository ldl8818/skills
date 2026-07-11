# Privacy
The public Skill repository and private memory repository are separate assets.

## Data that may be captured
- Explicit user correction prompts, when correction capture is enabled.
- Shell command failures, only when error capture is enabled.

Captured text is truncated, redacted for common credential patterns and marked untrusted. Redaction cannot identify every form of personal or proprietary information, so persistence should be disabled for sensitive or externally controlled material.

The software never creates a remote or pushes private memory automatically.

Initialization refuses filesystem root, HOME, the public Skill directory, and
unrelated non-empty directories. Data deletion additionally requires the
software's root marker and confirmation matching the full resolved path.
