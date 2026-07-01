load_repo_env() {
  local root_dir="$1"
  local env_file="${ROBOCODE_ENV_FILE:-$root_dir/.env}"

  if [[ -f "$env_file" ]]; then
    local had_nounset=0
    case "$-" in
      *u*) had_nounset=1 ;;
    esac
    set +u
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    if [[ "$had_nounset" -eq 1 ]]; then
      set -u
    fi
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
