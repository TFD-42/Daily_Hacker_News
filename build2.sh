#!/usr/bin/env bash
# build2.sh — publish the latest journal HTML behind a hardened HTTP server
#              exposed via a Cloudflare Quick Tunnel.
#
# Composition:
#   1. Regenerates a journal if none is present.
#   2. Launches scripts/serve.py (whitelist: only *.html + feed.json + opml,
#      no directory listing, no source code, GET/HEAD only, security headers,
#      trust-proxy so we see the real visitor IP + country from Cloudflare).
#   3. Launches `cloudflared tunnel --url http://127.0.0.1:$PORT`
#      (quick tunnel = no login, no domain, no CF account — one-shot URL).
#   4. Pulls the public URL from cloudflared's stderr + metrics API.
#   5. Streams enriched access logs (IP, country, OS, browser, device,
#      path, referrer) live to stdout.
#
# Usage
# -----
#   ./build2.sh                     # foreground, tail logs, CTRL-C to stop
#   ./build2.sh --daemon            # detach, writes PIDs + URL to files
#   ./build2.sh --stop              # stop the daemon set
#   ./build2.sh --status            # is it running?
#   ./build2.sh --regen             # force secjournal.py before serving
#   PORT=9090 ./build2.sh           # override local port
#
# Only Cloudflare Quick Tunnel is used by default (no login, no config).
# For your own named tunnel, set NAMED_TUNNEL=<tunnel-name>.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PY:-python3}"

PORT="${PORT:-8787}"
NAMED_TUNNEL="${NAMED_TUNNEL:-}"

JOURNAL_DIR="$ROOT/out/journals"
SERVE_PID="$ROOT/.build2_serve.pid"
CF_PID="$ROOT/.build2_cf.pid"
SERVE_LOG="$ROOT/.build2_serve.log"
CF_LOG="$ROOT/.build2_cf.log"
ACCESS_LOG="$ROOT/.access.log"
URL_FILE="$ROOT/.build2_url.txt"

# ── ansi helpers ─────────────────────────────────────────────────────────────
c()    { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info() { echo "$(c "1;36" "ℹ")  $*"; }
ok()   { echo "$(c "1;32" "✓")  $*"; }
warn() { echo "$(c "1;33" "⚠")  $*"; }
err()  { echo "$(c "1;31" "✗")  $*" >&2; }

# ── dependencies ─────────────────────────────────────────────────────────────
check_deps() {
  local missing=()
  for cmd in $PY cloudflared; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    err "manque : ${missing[*]}"
    for m in "${missing[@]}"; do
      case "$m" in
        cloudflared)
          echo "   install : brew install cloudflared" >&2
          echo "            | https://github.com/cloudflare/cloudflared/releases" >&2
          echo "            | (termux) pkg install cloudflared" >&2
          ;;
      esac
    done
    exit 1
  fi
}

# ── running check ────────────────────────────────────────────────────────────
# alive <pidfile> [cmd-pattern] — true only if the PID is live AND (when a
# pattern is given) the process command matches it. The pattern guards against
# a recycled PID being mistaken for ours and later killed.
alive() {
  local pf="$1" pat="${2:-}"
  [ -f "$pf" ] || return 1
  local pid; pid=$(cat "$pf" 2>/dev/null)
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  if [ -n "$pat" ]; then
    ps -p "$pid" -o command= 2>/dev/null | grep -q "$pat" || return 1
  fi
  return 0
}

status() {
  local any=0
  if alive "$SERVE_PID" "serve.py"; then
    ok "serve.py running (PID $(cat "$SERVE_PID")) — port $PORT"
    any=1
  fi
  if alive "$CF_PID" "cloudflared"; then
    ok "cloudflared running (PID $(cat "$CF_PID"))"
    any=1
  fi
  if [ -f "$URL_FILE" ]; then
    ok "URL: $(cat "$URL_FILE")"
  fi
  if [ "$any" -eq 0 ]; then
    warn "not running"
    return 1
  fi
}

stop() {
  local stopped=0
  # pidfile → expected command pattern (ownership guard)
  for entry in "$SERVE_PID:serve.py" "$CF_PID:cloudflared"; do
    local pf="${entry%:*}" pat="${entry##*:}"
    if alive "$pf" "$pat"; then
      local pid; pid=$(cat "$pf")
      kill "$pid" 2>/dev/null || true
      # wait up to 5s for graceful exit
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      stopped=1
    fi
    rm -f "$pf"
  done
  rm -f "$URL_FILE"
  [ "$stopped" -eq 1 ] && ok "stopped" || warn "was not running"
}

# ── freeport ─────────────────────────────────────────────────────────────────
free_port() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null \
      | xargs -I{} kill -9 {} 2>/dev/null || true
  fi
}

# ── journal presence ─────────────────────────────────────────────────────────
ensure_journal() {
  mkdir -p "$JOURNAL_DIR"
  local latest
  latest=$(ls -1t "$JOURNAL_DIR"/secjournal_*.html 2>/dev/null | head -1 || true)
  if [ -z "$latest" ] || [ "${REGEN:-0}" = "1" ]; then
    info "regeneration du journal via secjournal.py …"
    "$PY" "$ROOT/scripts/secjournal.py" --no-open --no-translate 2>&1 | tail -5
    latest=$(ls -1t "$JOURNAL_DIR"/secjournal_*.html 2>/dev/null | head -1 || true)
  fi
  if [ -z "$latest" ]; then
    err "no journal generated — check scripts/secjournal.py"
    exit 2
  fi
  ok "journal servi : $(basename "$latest")"
}

# ── launch serve.py ──────────────────────────────────────────────────────────
launch_serve() {
  info "starting hardened server on 127.0.0.1:$PORT (trust-proxy: ON)"
  # 127.0.0.1 only — the Cloudflare tunnel is the sole public entry point.
  # trust-proxy => on lit CF-Connecting-IP + CF-IPCountry.
  nohup "$PY" "$ROOT/scripts/serve.py" \
      --host 127.0.0.1 --port "$PORT" \
      --trust-proxy \
      --log "$ACCESS_LOG" \
      > "$SERVE_LOG" 2>&1 &
  echo $! > "$SERVE_PID"
  sleep 1
  if ! alive "$SERVE_PID"; then
    err "serve.py did not start:"
    cat "$SERVE_LOG" >&2
    exit 3
  fi
  ok "serve.py OK (PID $(cat "$SERVE_PID"))"
}

# ── launch cloudflared ───────────────────────────────────────────────────────
launch_cloudflared() {
  info "starting cloudflared Quick Tunnel …"
  local args=(tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate \
              --metrics 127.0.0.1:4040)
  if [ -n "$NAMED_TUNNEL" ]; then
    info "  (using named tunnel: $NAMED_TUNNEL)"
    args=(tunnel run "$NAMED_TUNNEL")
  fi
  nohup cloudflared "${args[@]}" > "$CF_LOG" 2>&1 &
  echo $! > "$CF_PID"

  # Wait for the tunnel URL to appear. `set -eo pipefail` is a hazard here
  # because grep exits 1 when no match yet — disable during the poll loop.
  local url=""
  set +eo pipefail   # grep exits 1 while there is no match yet
  for i in $(seq 1 45); do
    sleep 1
    # 1. banner in log
    url=$(grep -oE 'https://[a-z0-9.-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1)
    if [ -n "$url" ]; then break; fi
    # 2. metrics API (named tunnel path or quick tunnel)
    local host
    host=$(curl -s --max-time 2 http://127.0.0.1:4040/quicktunnel 2>/dev/null \
           | grep -oE '"hostname":"[^"]+"' | head -1 | sed 's/.*:"//;s/"$//')
    if [ -n "$host" ]; then
      url="https://$host"
      break
    fi
  done
  set -euo pipefail   # restore the FULL strict mode (including -u)
  if [ -z "$url" ]; then
    err "tunnel URL not found after 30s — see $CF_LOG"
    stop
    exit 4
  fi
  # url may or may not have the scheme
  case "$url" in
    https://*|http://*) ;;
    *) url="https://$url" ;;
  esac
  echo "$url" > "$URL_FILE"
  ok "tunnel up"
  echo "$(c "1;32" "→") URL publique : $(c "1;36" "$url")"
}

# ── enriched log streamer ────────────────────────────────────────────────────
stream_logs() {
  info "log stream (Ctrl-C = quit tail; process stays alive unless --daemon)"
  # tail the access log and pretty-print JSON records.
  # SECURITY: log lines contain attacker-controlled fields (path/referrer/UA
  # from public tunnel visitors). Feed them to Python over STDIN — never splice
  # them into the -c source, or a crafted request could execute arbitrary code.
  tail -F -n 0 "$ACCESS_LOG" 2>/dev/null | "$PY" -u -c '
import sys, json
for line in sys.stdin:
    line = line.rstrip("\n")
    try:
        r = json.loads(line)
    except Exception:
        print(line); continue
    t   = str(r.get("t", "?"))[11:19]
    ip  = r.get("ip", "?"); country = r.get("country", "-")
    os_ = r.get("os", "?"); br = r.get("browser", "?")
    dev = r.get("device", "?"); path = r.get("path", "?")
    st  = r.get("status", "?"); ref = str(r.get("ref", "-"))[:60]
    print(f"[{t}] {st} {country:>2} {ip:<15} {os_:<12} {br:<8} {dev:<7} {path}   ref={ref}")
'
}

# ── dispatch ─────────────────────────────────────────────────────────────────
usage() { sed -n '2,26p' "${BASH_SOURCE[0]}"; }

MODE="fg"
while [ $# -gt 0 ]; do
  case "$1" in
    ""|-h|--help)   usage; exit 0 ;;
    --status)       status; exit $? ;;
    --stop)         stop; exit 0 ;;
    --daemon)       MODE="daemon" ;;
    --regen)        REGEN=1 ;;
    --port)         PORT="$2"; shift ;;
    *)              err "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

check_deps
if alive "$SERVE_PID" || alive "$CF_PID"; then
  warn "processes already running — use ./build2.sh --status or --stop"
  exit 5
fi
free_port
ensure_journal
launch_serve
launch_cloudflared

if [ "$MODE" = "daemon" ]; then
  ok "detached. logs → $ACCESS_LOG · URL → $URL_FILE"
  ok "stop : ./build2.sh --stop"
else
  trap 'echo; info "stopping…"; stop; exit 0' INT TERM
  stream_logs
fi
