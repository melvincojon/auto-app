#!/usr/bin/env bash
set -euo pipefail

state_path="${1:-.state/jobs.json}"
mkdir -p "$(dirname "$state_path")"

if git fetch --quiet origin refs/heads/monitor-state:refs/remotes/origin/monitor-state; then
  git show refs/remotes/origin/monitor-state:state.json > "$state_path"
  echo "Restored monitor state from the monitor-state branch."
else
  echo "No monitor-state branch exists yet; the first successful poll will seed it."
fi
