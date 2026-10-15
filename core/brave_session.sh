#!/usr/bin/env zsh
# Use a dedicated Brave profile. Sign in manually once, reconnect via local CDP.
set -eu
BRAVE_BIN="${BRAVE_BIN:-/Applications/Brave Browser.app/Contents/MacOS/Brave Browser}"
PROFILE="${MIXAMO_BRAVE_PROFILE:-$HOME/.mixamo-brave-profile}"
PORT="${MIXAMO_CDP_PORT:-9222}"
MODE="${1:-help}"

if [[ ! -x "$BRAVE_BIN" ]]; then
  print -u2 "Brave not found: $BRAVE_BIN"
  exit 1
fi

port_ready() { nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; }

case "$MODE" in
  login)
    if port_ready; then
      print -u2 "Port $PORT already has a listener; close the existing debug session first."
      exit 1
    fi
    mkdir -p "$PROFILE"
    "$BRAVE_BIN" --user-data-dir="$PROFILE" --no-first-run 'https://www.mixamo.com/' >/dev/null 2>&1 &!
    print 'Sign in manually with Adobe/Google in the new dedicated Brave window.'
    print 'Close that Brave instance completely, then: ./brave_session.sh automate'
    ;;
  automate)
    if port_ready; then
      print "Port $PORT already has a listener. Verify it is your intended dedicated Brave instance."
      exit 0
    fi
    mkdir -p "$PROFILE"
    "$BRAVE_BIN" --user-data-dir="$PROFILE" --no-first-run \
      --remote-debugging-address=127.0.0.1 --remote-debugging-port="$PORT" \
      'https://www.mixamo.com/' >/dev/null 2>&1 &!
    for i in {1..50}; do
      if port_ready; then
        print "Brave is listening on 127.0.0.1:$PORT."
        print "The /json/version URL can return 404 in some Brave CDP modes."
        print 'Run: python mixamo_pipeline.py --character /path/to/rigged.zip'
        exit 0
      fi
      sleep 0.4
    done
    print -u2 "No debugger on port $PORT. Ensure the previous Brave window was fully closed."
    exit 1
    ;;
  status)
    if port_ready; then
      print "A process is listening on 127.0.0.1:$PORT. Check identity using lsof."
    else
      print "No listener on 127.0.0.1:$PORT"
    fi
    ;;
  *)
    print 'Usage: ./brave_session.sh login | automate | status'
    exit 1
    ;;
esac
