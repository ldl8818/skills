# Conditional evidence helpers
Start with `collect-data.sh --root PATH`. Its output contains structural counts and file status; it never runs project code, scans sessions by default or calls MCP.
- Instruction reachability/configuration: `check-agent-context.sh PATH summary`; global scope is excluded unless `--include-global` is explicitly supplied.
- Local documentation references: `check-doc-refs.sh PATH`.
- An already supplied verifier log: `check-verifier-output.sh PATH LOG`; inspect the log source before reporting a pass.
- Explicit Skill directories: `python3 -I scripts/scan_skill_security.py --project-root PATH SKILL_MD_PATH`.
Read each helper's help before use. Its warnings are candidate evidence and require review.
Historical analysis requires an explicit history path and opt-in to `conversation_audit.py`; never load it from the default collector. Redact output before sharing.
Global collection, live MCP calls and deep reasoning are distinct scopes. A live probe must name its server/tool and avoid mutating tools unless separately authorized.

For a persistent Agent loop specifically, read [long-running-agents.md](long-running-agents.md).

Only after delegation is authorized and useful, the scoped briefs are [context inspector](../agents/inspector-context.md) and [control inspector](../agents/inspector-control.md). They do not expand collection scope.
