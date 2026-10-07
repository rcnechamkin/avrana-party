#!/usr/bin/env bash
# Avrana Party - lightweight Pi-specific telemetry sampler.
#
# Records what Beszel cannot read on its own: the vcgencmd throttle/undervolt
# flags, CPU temperature, ARM clock, V3D (GPU) clock and core voltage, as one
# JSON object per line. Beszel (hub on avrana) stays the MAIN historical
# dashboard for CPU / RAM / load / temp / disk / network; this is a small
# companion, not a second monitoring stack.
#
# NOTE ON TRANSIENTS: the recurring under-voltage on this Pi is brief. Periodic
# sampling (even at 1 s) will miss most sub-second dips. The kernel journal
# ("Undervoltage detected!" / "Voltage normalised") remains the authoritative
# count of transient dips:
#     sudo journalctl -k -b | grep -icE 'undervoltage|voltage normalis'
# This sampler tracks sustained state, clocks and the sticky "has occurred"
# bits over time so a PSU/cable change can be compared before vs after.
set -euo pipefail

INTERVAL=1
COUNT=1
LABEL=""
OUT=""            # empty => stdout

usage() {
  echo "usage: $0 [--interval S] [--count N] [--label TEXT] [--append FILE]" >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --interval) INTERVAL="$2"; shift 2;;
    --count)    COUNT="$2"; shift 2;;
    --label)    LABEL="$2"; shift 2;;
    --append|--out) OUT="$2"; shift 2;;
    -h|--help)  usage;;
    *) echo "unknown arg: $1" >&2; usage;;
  esac
done

VCG="$(command -v vcgencmd || echo /usr/bin/vcgencmd)"

b() { if (( $1 )); then echo true; else echo false; fi; }

# AVR-296: when the VideoCore firmware mailbox wedges (seen 2026-10-06) vcgencmd hangs in
# uninterruptible sleep and cannot be killed. Bound every call and never start another while one is
# stuck, so this sampler cannot pile up D-state processes (which also inflate the load average).
vcg() { timeout -k 1 5 "$VCG" "$@"; }
stuck_vcgencmd() { ps -eo stat,comm | awk '$1 ~ /^D/ && $2 == "vcgencmd" { n++ } END { print n + 0 }'; }

sample() {
  local thr temp arm v3d volt t ts stuck
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  stuck="$(stuck_vcgencmd)"
  if [ "$stuck" -gt 0 ]; then
    printf '{"ts":"%s","label":"%s","error":"vcgencmd_stuck","stuck_vcgencmd":%s}\n' "$ts" "$LABEL" "$stuck"
    return 0
  fi
  thr="$(vcg get_throttled | cut -d= -f2 || true)"                   # e.g. 0x50000
  if [ -z "$thr" ]; then
    printf '{"ts":"%s","label":"%s","error":"vcgencmd_timeout_or_failed"}\n' "$ts" "$LABEL"
    return 0
  fi
  temp="$(vcg measure_temp | sed -E "s/temp=([0-9.]+).*/\1/" || true)"    # degC
  arm="$(vcg measure_clock arm | cut -d= -f2 || true)"                    # Hz
  v3d="$(vcg measure_clock v3d | cut -d= -f2 || true)"                    # Hz
  volt="$(vcg measure_volts core | sed -E "s/volt=([0-9.]+)V/\1/" || true)"
  t=$(( thr ))
  printf '{"ts":"%s","label":"%s","throttled":"%s",' "$ts" "$LABEL" "$thr"
  printf '"undervolt_now":%s,"freqcap_now":%s,"throttled_now":%s,"softtemp_now":%s,' \
    "$(b $(( t & 0x1 )))" "$(b $(( t & 0x2 )))" "$(b $(( t & 0x4 )))" "$(b $(( t & 0x8 )))"
  printf '"undervolt_occurred":%s,"freqcap_occurred":%s,"throttled_occurred":%s,"softtemp_occurred":%s,' \
    "$(b $(( t & 0x10000 )))" "$(b $(( t & 0x20000 )))" "$(b $(( t & 0x40000 )))" "$(b $(( t & 0x80000 )))"
  printf '"temp_c":%s,"arm_hz":%s,"v3d_hz":%s,"core_v":%s}\n' \
    "${temp:-null}" "${arm:-null}" "${v3d:-null}" "${volt:-null}"
}

emit() { if [ -n "$OUT" ]; then sample >>"$OUT"; else sample; fi; }

i=0
while [ "$i" -lt "$COUNT" ]; do
  emit
  i=$(( i + 1 ))
  if [ "$i" -lt "$COUNT" ]; then sleep "$INTERVAL"; fi
done
exit 0
