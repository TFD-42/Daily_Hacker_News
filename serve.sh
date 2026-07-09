#!/usr/bin/env bash
# serve.sh — start / stop / reload the hardened HTTP(S) server for
# Daily Hacker News. Wraps scripts/serve.py.
#
# Usage:
#   ./serve.sh                     # foreground, HTTP :8000, bind 0.0.0.0
#   ./serve.sh --local             # bind 127.0.0.1 only (dev)
#   ./serve.sh --tls               # HTTPS, auto self-signed cert if missing
#   ./serve.sh --daemon            # detach (nohup + pid file)
#   ./serve.sh --stop              # stop daemon
#   ./serve.sh --status            # is it running?
#   ./serve.sh --gen-cert          # regenerate self-signed cert
#   ./serve.sh --install-launchd   # macOS user launchd, autostart at login
#   ./serve.sh --install-systemd   # print systemd unit for Linux (copy/paste)
#
# Env / defaults:
#   PORT=8000
#   HOST=0.0.0.0       (or 127.0.0.1 with --local)
#   AUTH=              (user:password to enable HTTP Basic)
#   ALLOW=             (comma-separated CIDRs; ex: 10.0.0.0/8,192.168.1.0/24)
#   CERT=./deploy/certs/dhn.pem
#   KEY=./deploy/certs/dhn.key

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PY:-python3}"
SCRIPT="$ROOT/scripts/serve.py"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
AUTH="${AUTH:-}"
ALLOW="${ALLOW:-}"
CERT="${CERT:-$ROOT/deploy/certs/dhn.pem}"
KEY="${KEY:-$ROOT/deploy/certs/dhn.key}"

PID_FILE="$ROOT/.serve.pid"
LOG_FILE="$ROOT/.serve.log"

TLS=0
DAEMON=0
LOCAL=0

# ── helpers ───────────────────────────────────────────────────────────────────
c()    { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info() { echo "$(c "1;36" "ℹ")  $*"; }
ok()   { echo "$(c "1;32" "✓")  $*"; }
warn() { echo "$(c "1;33" "⚠")  $*"; }
err()  { echo "$(c "1;31" "✗")  $*" >&2; }

require_openssl() {
  command -v openssl >/dev/null 2>&1 || {
    err "openssl requis pour generer le certificat"; exit 1; }
}

gen_self_signed() {
  require_openssl
  mkdir -p "$(dirname "$CERT")"
  info "generation certificat self-signed → $CERT"
  openssl req -x509 -newkey rsa:2048 -sha256 \
    -keyout "$KEY" -out "$CERT" \
    -days 365 -nodes \
    -subj "/CN=daily-hacker-news.local" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:0.0.0.0" \
    2>/dev/null
  chmod 600 "$KEY"
  ok "cert / cle generes (365 jours)"
}

build_cmd() {
  local -a a=("$PY" "$SCRIPT" --host "$HOST" --port "$PORT")
  [ -n "$AUTH" ] && a+=(--auth "$AUTH")
  if [ -n "$ALLOW" ]; then
    IFS=',' read -ra NETS <<< "$ALLOW"
    for n in "${NETS[@]}"; do a+=(--allow "$n"); done
  fi
  if [ "$TLS" -eq 1 ]; then
    [ -f "$CERT" ] && [ -f "$KEY" ] || gen_self_signed
    a+=(--cert "$CERT" --key "$KEY")
  fi
  a+=(--log "$ROOT/.access.log")
  printf '%s\n' "${a[@]}"
}

# _owned <pid> — true only if PID is live AND its command looks like our
# server. Guards against a recycled PID being mistaken for ours and killed.
_owned() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q "serve.py" || return 1
  return 0
}

status() {
  if [ -f "$PID_FILE" ]; then
    local pid; pid=$(cat "$PID_FILE" 2>/dev/null || echo)
    if _owned "$pid"; then
      ok "running (PID $pid) — log: $LOG_FILE"
      return 0
    fi
  fi
  warn "not running"
  return 1
}

start_bg() {
  if [ -f "$PID_FILE" ] && _owned "$(cat "$PID_FILE" 2>/dev/null)"; then
    err "already running (PID $(cat "$PID_FILE"))"; exit 2
  fi
  local -a cmd
  cmd=(); while IFS= read -r line; do cmd+=("$line"); done < <(build_cmd)
  info "cmd: ${cmd[*]}"
  nohup "${cmd[@]}" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 0.6
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    ok "started (PID $(cat "$PID_FILE"))"
    head -3 "$LOG_FILE"
  else
    err "failed to start — see $LOG_FILE"
    tail -20 "$LOG_FILE" >&2
    exit 3
  fi
}

stop_bg() {
  [ -f "$PID_FILE" ] || { warn "no pid file"; return 0; }
  local pid; pid=$(cat "$PID_FILE" 2>/dev/null || echo)
  if ! _owned "$pid"; then
    warn "not running"; rm -f "$PID_FILE"; return 0
  fi
  info "stopping PID $pid…"
  kill "$pid"
  # wait for graceful exit up to 5 s
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || { ok "stopped"; rm -f "$PID_FILE"; return 0; }
    sleep 0.5
  done
  warn "not exiting — SIGKILL"
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
}

install_launchd() {
  local label="com.dailyhackernews.server"
  local plist="$HOME/Library/LaunchAgents/$label.plist"
  mkdir -p "$(dirname "$plist")"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>               <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/serve.sh</string>
  </array>
  <key>WorkingDirectory</key>    <string>$ROOT</string>
  <key>RunAtLoad</key>           <true/>
  <key>KeepAlive</key>           <true/>
  <key>StandardOutPath</key>     <string>$LOG_FILE</string>
  <key>StandardErrorPath</key>   <string>$LOG_FILE</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>              <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>PORT</key>              <string>$PORT</string>
    <key>HOST</key>              <string>$HOST</string>
  </dict>
</dict>
</plist>
PLIST
  info "plist → $plist"
  launchctl unload  "$plist" 2>/dev/null || true
  launchctl load    "$plist"
  ok "launchd charge (autostart au login)"
  info "gerer:  launchctl unload $plist  # arret"
}

print_systemd_unit() {
  local user="${USER:-$(whoami)}"
  cat <<UNIT
# Copier dans /etc/systemd/system/dailyhackernews.service
# puis:
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now dailyhackernews.service
#   journalctl -u dailyhackernews.service -f

[Unit]
Description=Daily Hacker News hardened static server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$user
WorkingDirectory=$ROOT
Environment=PORT=$PORT HOST=$HOST
ExecStart=$PY $SCRIPT --host \${HOST} --port \${PORT} --log $ROOT/.access.log
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$ROOT
ProtectHome=read-only
PrivateTmp=true
CapabilityBoundingSet=
AmbientCapabilities=

[Install]
WantedBy=multi-user.target
UNIT
}

# ── dispatch ──────────────────────────────────────────────────────────────────
usage() { sed -n '2,26p' "${BASH_SOURCE[0]}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    ""|-h|--help)      usage; exit 0 ;;
    --local)           LOCAL=1; HOST="127.0.0.1" ;;
    --tls)             TLS=1 ;;
    --daemon)          DAEMON=1 ;;
    --stop)            stop_bg; exit 0 ;;
    --status)          status; exit $? ;;
    --gen-cert)        gen_self_signed; exit 0 ;;
    --install-launchd) install_launchd; exit 0 ;;
    --install-systemd) print_systemd_unit; exit 0 ;;
    --port)            PORT="$2"; shift ;;
    --host)            HOST="$2"; shift ;;
    --auth)            AUTH="$2"; shift ;;
    --allow)           ALLOW="$2"; shift ;;
    *)                 err "unknown arg: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

if [ "$DAEMON" -eq 1 ]; then
  start_bg
else
  # foreground
  cmd=(); while IFS= read -r line; do cmd+=("$line"); done < <(build_cmd)
  info "cmd: ${cmd[*]}"
  exec "${cmd[@]}"
fi
