#!/usr/bin/env bash
set -euo pipefail

state_path="${1:-.state/jobs.json}"
if [[ ! -f "$state_path" ]]; then
  echo "No state file was produced; nothing to persist."
  exit 0
fi

parent="$(git rev-parse --verify refs/remotes/origin/monitor-state 2>/dev/null || true)"
if [[ -n "$parent" ]] && git show "${parent}:state.json" 2>/dev/null | cmp --silent - "$state_path"; then
  echo "Monitor state is unchanged."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

blob="$(git hash-object -w "$state_path")"
tree="$(printf '100644 blob %s\tstate.json\n' "$blob" | git mktree)"
if [[ -n "$parent" ]]; then
  commit="$(printf 'Update job monitor state\n' | git commit-tree "$tree" -p "$parent")"
else
  commit="$(printf 'Seed job monitor state\n' | git commit-tree "$tree")"
fi
git push origin "${commit}:refs/heads/monitor-state"
echo "Persisted monitor state to the monitor-state branch."
