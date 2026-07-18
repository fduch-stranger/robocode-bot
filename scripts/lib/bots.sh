discover_bot_dirs() {
  local root_dir="$1"
  local bot

  for bot in "$root_dir"/bots/* "$root_dir"/bots/ports/*; do
    if [[ -d "$bot" ]] && compgen -G "$bot/*.json" > /dev/null; then
      printf '%s\n' "$bot"
    fi
  done
}

legacy_bots_root() {
  local root_dir="$1"
  local legacy_root

  if [[ -n "${ROBOCODE_LEGACY_BOTS_ROOT:-}" ]]; then
    legacy_root="$ROBOCODE_LEGACY_BOTS_ROOT"
  else
    legacy_root="$root_dir/legacy-bots"
  fi

  if [[ -d "$legacy_root" ]]; then
    (cd "$legacy_root" && pwd)
  else
    printf '%s\n' "$legacy_root"
  fi
}

discover_legacy_bot_dirs() {
  local root_dir="$1"
  local legacy_root
  local bot

  legacy_root="$(legacy_bots_root "$root_dir")"
  if [[ ! -d "$legacy_root" ]]; then
    return 0
  fi

  for bot in "$legacy_root"/*; do
    if is_valid_legacy_bot_dir "$bot"; then
      printf '%s\n' "$bot"
    fi
  done
}

is_valid_legacy_bot_dir() {
  local bot="$1"

  [[ -d "$bot" ]] && compgen -G "$bot/*.json" > /dev/null && compgen -G "$bot/*.sh" > /dev/null
}

legacy_bot_dir() {
  local root_dir="$1"
  local name="$2"
  local legacy_root
  local canonical
  local candidate

  legacy_root="$(legacy_bots_root "$root_dir")"
  name="${name#legacy:}"
  canonical="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"

  case "$canonical" in
    drussgt|jk.mega.drussgt|jk.mega.drussgt_3.1.12)
      candidate="$legacy_root/jk.mega.DrussGT_3.1.12"
      ;;
    diamond|voidious.diamond|voidious.diamond_1.8.28)
      candidate="$legacy_root/voidious.Diamond_1.8.28"
      ;;
    saguaro|oog.mega.saguaro|oog.mega.saguaro.saguaro|oog.mega.saguaro.saguaro_1.0)
      candidate="$legacy_root/oog.mega.saguaro.Saguaro_1.0"
      ;;
    *)
      candidate="$legacy_root/$name"
      ;;
  esac

  if is_valid_legacy_bot_dir "$candidate"; then
    printf '%s\n' "$candidate"
    return 0
  fi

  return 1
}

list_legacy_bots() {
  local root_dir="$1"
  local bot
  local name

  while IFS= read -r bot; do
    name="$(basename "$bot")"
    case "$name" in
      jk.mega.DrussGT_3.1.12)
        printf '%s\t%s\n' "drussgt" "$bot"
        ;;
      voidious.Diamond_1.8.28)
        printf '%s\t%s\n' "diamond" "$bot"
        ;;
      oog.mega.saguaro.Saguaro_1.0)
        printf '%s\t%s\n' "saguaro" "$bot"
        ;;
      *)
        printf '%s\t%s\n' "$name" "$bot"
        ;;
    esac
  done < <(discover_legacy_bot_dirs "$root_dir")
}

is_legacy_bot_dir() {
  local root_dir="$1"
  local bot="$2"
  local legacy_root

  legacy_root="$(legacy_bots_root "$root_dir")"
  [[ -n "$legacy_root" && "$bot" == "$legacy_root"/* ]]
}

normalize_bot_dir() {
  local root_dir="$1"
  local bot="$2"
  local local_bot

  if [[ "$bot" = /* ]]; then
    printf '%s\n' "$bot"
  elif [[ "$bot" == legacy:* ]]; then
    legacy_bot_dir "$root_dir" "$bot"
  else
    local_bot="$root_dir/$bot"
    if [[ -d "$local_bot" ]]; then
      printf '%s\n' "$local_bot"
    elif legacy_bot_dir "$root_dir" "$bot"; then
      return 0
    else
      printf '%s\n' "$local_bot"
    fi
  fi
}

append_legacy_bot_args() {
  local root_dir="$1"
  local name="$2"

  if [[ "$name" == "all" ]]; then
    discover_legacy_bot_dirs "$root_dir"
  else
    legacy_bot_dir "$root_dir" "$name"
  fi
}
