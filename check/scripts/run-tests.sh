#!/usr/bin/env bash
# Auto-detect and run project verification (lint + typecheck + tests).
# Run from the project root. Exits non-zero on failure.
set -euo pipefail

if [[ "${1:-}" != "--execute" ]]; then
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
fi
shift

if [ -f Cargo.toml ]; then
  cargo check && cargo test
elif [ -f tsconfig.json ]; then
  npx tsc --noEmit && npm test
elif [ -f package.json ] && grep -q '"test"' package.json; then
  npm test
elif [ -f Makefile ] && grep -q '^test:' Makefile; then
  make test
elif [ -f pytest.ini ] || [ -f pyproject.toml ] || find . -maxdepth 2 -name "test_*.py" | grep -q .; then
  pytest
else
  echo "(no test command detected - ask the user for the verification command)"
  exit 1
fi
