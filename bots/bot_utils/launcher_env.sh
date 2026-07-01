load_repo_env_if_available() {
  local root_dir="$1"

  if [[ -f "$root_dir/scripts/lib/env.sh" ]]; then
    # shellcheck disable=SC1090
    source "$root_dir/scripts/lib/env.sh"
    load_repo_env "$root_dir"
  fi
}

robocode_python_bin() {
  local root_dir="$1"

  if [[ -n "${ROBOCODE_PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$ROBOCODE_PYTHON_BIN"
  elif [[ -x "$root_dir/.venv/bin/python" ]]; then
    printf '%s\n' "$root_dir/.venv/bin/python"
  else
    printf '%s\n' "python3"
  fi
}
