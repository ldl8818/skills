# Project audit
Use only for an explicit repository-quality audit.
Establish the requested scope from current architecture, entrypoints, tests and deployment surfaces. Follow reachable data/control paths; prioritize correctness, security and maintainability issues that affect actual behavior.
Use scripts/audit_signals.py only to locate candidates. Counts and hotspots are not findings.
Report defects and risks by evidence and impact, including safe simplifications where their value is demonstrated. No mechanical score, persona rating or fixed reviewer count.
A broad audit remains read-only unless repair is authorized. Run only the verification that can resolve material uncertainty within scope.
