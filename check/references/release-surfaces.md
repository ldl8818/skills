# Release surfaces
Load only the affected surface.
## CLI
Verify help/version, flags, exit status, stdout/stderr and structured output, interactive versus noninteractive behavior, configuration precedence and installed executable/resource resolution.
For mutating commands inspect selection scope, failure atomicity, retry/idempotency and recovery. Use safe fixtures for destructive paths.
## Package and installation
Inspect the documented build and install path, archive or generated mirror, resource references and executable bits. Exclude caches and private state.
When installation changes, run an isolated install using the documented path and invoke the smallest meaningful installed command. A source test or valid manifest is not installed-runtime proof.
## Reworked release
Choose the comparison base from the published version relevant to the release, not merely the latest local diff.
Separate blockers from deferrable work. Check the affected failure paths, permissions, update feeds and user-facing support claims. Refresh evidence only when the underlying artifact or state changes.
