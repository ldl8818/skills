# Conditional review patterns
Load only patterns reached by the current diff.
- Security boundaries: trace untrusted input to shell, filesystem, network and privilege sinks. Check exact target selection, path containment, parameter handling and credential exposure.
- User-file replacement: verify staging and atomic replacement preserve the original on write failure or interruption. Check recovery and partial external effects.
- Async work: distinguish visible terminal output from captured output. Prefer structured status over prose parsing and observable completion over guessed sleeps.
- Deletion and simplification: inspect static callers, dynamic registration, generators, manifests and installed entrypoints before declaring code unused. Preserve deliberate asymmetry unless its reason is obsolete.
- Duplicated derivation: check whether summary/executor or preview/control compute the same rule independently and can drift.
- Test fidelity: verify the tested path is reached in production and the test observes the failed behavior. Add a seam only if it improves meaningful coverage.
- Architecture: inspect responsibility boundaries, dependency direction, shared mutable state and concurrency. Prefer a direct fix over an abstraction for hypothetical future cases.
- Migration: establish which data and versions actually shipped before requiring compatibility machinery.
- Recurring state or visual failures: test the violated invariant when a realistic seam exists; do not mistake one screenshot or a tuned constant for broad regression protection.
