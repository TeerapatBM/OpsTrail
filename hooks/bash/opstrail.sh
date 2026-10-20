# OpsTrail shell hook for bash and zsh (Linux, macOS, WSL, Git Bash).
# Add to ~/.bashrc or ~/.zshrc:   source /path/to/OpsTrail/hooks/bash/opstrail.sh
# Writes one line per command to ~/.opstrail/inbox (format "tsv1", see SPEC.md §4).
# Remote servers: you can source this file there too, then copy ~/.opstrail/inbox/*.tsv back
# into your local inbox to include remote commands in your documents.

[ -n "${__OPSTRAIL_LOADED:-}" ] && return 0
__OPSTRAIL_LOADED=1

__OPSTRAIL_HOME="${OPSTRAIL_HOME:-$HOME/.opstrail}"
__OPSTRAIL_INBOX="$__OPSTRAIL_HOME/inbox"
__OPSTRAIL_SESSION="$(date +%s)$$"
__OPSTRAIL_HOST="$(hostname 2>/dev/null || uname -n)"

__opstrail_b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

__opstrail_write() {  # $1=exit $2=cmd $3=shell
  [ -e "$__OPSTRAIL_HOME/paused" ] && return 0
  [ -z "$2" ] && return 0
  mkdir -p "$__OPSTRAIL_INBOX" 2>/dev/null || return 0
  printf 'tsv1\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(date +%s)" "$1" "$(__opstrail_b64 "$PWD")" "$(__opstrail_b64 "$2")" \
    "$__OPSTRAIL_HOST" "${USER:-$(id -un)}" "$3" "$__OPSTRAIL_SESSION" \
    >> "$__OPSTRAIL_INBOX/$3-$__OPSTRAIL_HOST-$$.tsv" 2>/dev/null
}

if [ -n "${ZSH_VERSION:-}" ]; then
  __opstrail_cmd=""
  __opstrail_preexec() { __opstrail_cmd="$1"; }
  __opstrail_precmd() {
    local ec=$?
    [ -n "$__opstrail_cmd" ] && __opstrail_write "$ec" "$__opstrail_cmd" zsh
    __opstrail_cmd=""
    return $ec
  }
  autoload -Uz add-zsh-hook 2>/dev/null
  add-zsh-hook preexec __opstrail_preexec
  add-zsh-hook precmd __opstrail_precmd
elif [ -n "${BASH_VERSION:-}" ]; then
  __opstrail_last_hist=""
  __opstrail_prompt() {
    local ec=$?
    local line num cmd
    line="$(HISTTIMEFORMAT='' builtin history 1)"
    num="$(printf '%s' "$line" | awk '{print $1}')"
    if [ -n "$__opstrail_last_hist" ] && [ "$num" != "$__opstrail_last_hist" ]; then
      cmd="$(printf '%s' "$line" | sed -E 's/^ *[0-9]+\*? *//')"
      __opstrail_write "$ec" "$cmd" bash
    fi
    __opstrail_last_hist="$num"
    return $ec
  }
  case ";${PROMPT_COMMAND:-};" in
    *";__opstrail_prompt;"*) ;;
    *) PROMPT_COMMAND="__opstrail_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
  esac
fi
