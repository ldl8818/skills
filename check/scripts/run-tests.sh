#!/usr/bin/env bash
# Discover candidates only; never run project commands or package managers.
set -euo pipefail
if [[ "${1:-}" == "--help" ]]; then
  printf '%s\n' 'Run from the project root. Prints candidates; executes none.'
  exit 0
fi
printf '%s\n' 'Candidates only; confirm against AGENTS.md, lockfiles and CI before execution.'
[[ ! -f Cargo.toml ]] || printf '%s\n' 'cargo check' 'cargo test'
[[ ! -f tsconfig.json ]] || printf '%s\n' 'project-local TypeScript compiler (if installed)'
[[ ! -f package.json ]] || printf '%s\n' 'inspect package.json scripts and the matching package manager lockfile'
[[ ! -f Makefile ]] || printf '%s\n' 'inspect documented Makefile verification targets'
[[ ! -f pyproject.toml && ! -f pytest.ini ]] || printf '%s\n' 'inspect configured Python test runner and test dependencies'
exit 0
