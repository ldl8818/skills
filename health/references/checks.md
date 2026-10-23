# Conditional evidence helpers
Start with `collect-data.sh --root PATH`. Its output contains structural counts and file status; it never runs project code, scans sessions by default or calls MCP.
The bounded project Skill summary reports dangling roots and broken directory or `SKILL.md` links without exposing Skill names or contents. Counts cover only inspected entries when truncated. The opt-in global context checker lists broken link paths and keeps valid aliases collapsed; neither result proves that a client loaded a Skill.
- Instruction reachability/configuration: `check-agent-context.sh PATH summary`; global scope is excluded unless `--include-global` is explicitly supplied.
- Local documentation references: `check-doc-refs.sh PATH`.
- An already supplied verifier log: `check-verifier-output.sh PATH LOG`; inspect the log source before reporting a pass.
- Explicit Skill directories: `python3 -I scripts/scan_skill_security.py --project-root PATH SKILL_MD_PATH`.
Read each helper's help before use. Its warnings are candidate evidence and require review.
Historical analysis requires an explicit history path and opt-in to `conversation_audit.py`; never load it from the default collector. Redact output before sharing.
Global collection, live MCP calls and deep reasoning are distinct scopes. A live probe must name its server/tool and avoid mutating tools unless separately authorized.

## Runtime evidence interpretation
For a Hook or MCP fault, inspect the authorized configuration sources and retain each source's scope and enablement. Do not infer effective configuration from one file when project, user or plugin settings can override it. Unknown plugin state, command expansion or working directory remains unverified.
Validate Hook handlers against the installed runtime's current contract. A missing tool matcher is not an error for lifecycle events; command, prompt, agent, HTTP and MCP handlers do not share one required-field schema. Do not reject an unfamiliar handler merely because it has no command.
Keep connected, failed, disabled, pending approval and untested MCP states distinct. Probe only an already connected server through an available harmless tool; do not start an unverified GUI executable to test connectivity. Static collection does not establish live health.
When assessing instruction reachability or size limits, check the installed runtime's loading mode, actual file identity and effective limit. Report uninspected ancestors, nested files and overrides; root-file bytes alone do not prove the complete instruction chain fits or loads. Do not infer loading behavior from filenames alone.

For a persistent Agent loop specifically, read [long-running-agents.md](long-running-agents.md).

Only after delegation is authorized and useful, the scoped briefs are [context inspector](../agents/inspector-context.md) and [control inspector](../agents/inspector-control.md). They do not expand collection scope.
