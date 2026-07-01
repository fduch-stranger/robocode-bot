load_repo_env() {
  local root_dir="$1"
  local env_file="${ROBOCODE_ENV_FILE:-$root_dir/.env}"

  if [[ -f "$env_file" ]]; then
    local known_names=(
      PYTHON_BIN
      ROBOCODE_PYTHON_BIN
      ROBOCODE_LEGACY_BOTS_ROOT
      ROBOCODE_TELEMETRY
      ROBOCODE_TELEMETRY_ROOT
      ROBOCODE_TELEMETRY_DIR
      ROBOCODE_TELEMETRY_AUTOSTART
      ROBOCODE_TELEMETRY_HOST
      ROBOCODE_TELEMETRY_PORT
      ROBOCODE_TELEMETRY_PORT_FALLBACK
      ROBOCODE_TELEMETRY_OPEN
    )
    local restore_names=()
    local restore_values=()
    local name
    local index
    local had_nounset=0
    for name in "${known_names[@]}"; do
      if [[ ${!name+x} ]]; then
        restore_names+=("$name")
        restore_values+=("${!name}")
      fi
    done
    case "$-" in
      *u*) had_nounset=1 ;;
    esac
    set +u
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
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
