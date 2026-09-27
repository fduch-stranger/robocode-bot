# Machine-wide battle lock. Concurrent battles compete for CPU and skew bot turn timing,
# which silently invalidates benchmark results, so battles wait for each other.
#
# ROBOCODE_BATTLE_LOCK=0 disables the lock; ROBOCODE_BATTLE_LOCK_PATH overrides its location
# (default is shared by every checkout and worktree of the current user).

battle_lock_path() {
  printf '%s\n' "${ROBOCODE_BATTLE_LOCK_PATH:-/tmp/robocode-battle-$(id -u).lock}"
}

battle_lock_owner_pid() {
  local lock_dir="$1"
  cat "$lock_dir/pid" 2>/dev/null || true
}

acquire_battle_lock() {
  battle_lock_acquired=0
  if [[ "${ROBOCODE_BATTLE_LOCK:-1}" == "0" ]]; then
    return 0
  fi
  local lock_dir owner waited=0
  lock_dir="$(battle_lock_path)"
  while ! mkdir "$lock_dir" 2>/dev/null; do
    owner="$(battle_lock_owner_pid "$lock_dir")"
    if [[ -n "$owner" ]] && ! kill -0 "$owner" 2>/dev/null; then
      # The owner died without releasing; clear the stale lock and retry.
      rm -rf "$lock_dir"
      continue
    fi
    if [[ "$waited" -eq 0 ]]; then
      echo "Waiting for another battle to finish (lock $lock_dir held by pid ${owner:-unknown})..." >&2
    fi
    waited=1
    sleep 2
  done
  printf '%s\n' "$$" > "$lock_dir/pid"
  battle_lock_acquired=1
  if [[ "$waited" -eq 1 ]]; then
    echo "Battle lock acquired." >&2
  fi
}

release_battle_lock() {
  if [[ "${battle_lock_acquired:-0}" -ne 1 ]]; then
    return 0
  fi
  local lock_dir
  lock_dir="$(battle_lock_path)"
  if [[ "$(battle_lock_owner_pid "$lock_dir")" == "$$" ]]; then
    rm -rf "$lock_dir"
  fi
  battle_lock_acquired=0
}
