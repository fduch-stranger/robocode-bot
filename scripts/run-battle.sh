#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MVN_REPO="$ROOT_DIR/.m2/repository"

cd "$ROOT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  scripts/setup.sh
fi

export PATH="$ROOT_DIR/.venv/bin:$PATH"

mvn \
  -s "$ROOT_DIR/tools/maven-central-settings.xml" \
  -Dmaven.repo.local="$MVN_REPO" \
  -q \
  -f "$ROOT_DIR/tools/battle-runner/pom.xml" \
  compile exec:java \
  -Dexec.args="$ROOT_DIR/bots/test-bot-1 $ROOT_DIR/bots/test-bot-2"
