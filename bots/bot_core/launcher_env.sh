load_repo_env_if_available() {
  local root_dir="$1"

  if [[ -f "$root_dir/scripts/lib/env.sh" ]]; then
    # shellcheck disable=SC1090
    source "$root_dir/scripts/lib/env.sh"
    load_repo_env "$root_dir"
    return
  fi

  _load_packaged_env "$root_dir"
}

_load_packaged_env() {
  local root_dir="$1"
  local env_file="${ROBOCODE_ENV_FILE:-$root_dir/.env}"
  local gun_env_file="${ROBOCODE_GUN_ENV_FILE:-$root_dir/.env.guns}"

  if [[ -f "$env_file" || -f "$gun_env_file" ]]; then
    local restore_names=()
    local restore_values=()
    local name
    local index
    local had_nounset=0
    while IFS= read -r name; do
      restore_names+=("$name")
      restore_values+=("${!name}")
    done < <(compgen -e)
    case "$-" in
      *u*) had_nounset=1 ;;
    esac
    set +u
    set -a
    if [[ -f "$env_file" ]]; then
      # shellcheck disable=SC1090
      source "$env_file"
    fi
    if [[ -f "$gun_env_file" ]]; then
      # shellcheck disable=SC1090
      source "$gun_env_file"
    fi
    set +a
    for index in "${!restore_names[@]}"; do
      export "${restore_names[$index]}=${restore_values[$index]}"
    done
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
