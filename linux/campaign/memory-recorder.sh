#!/usr/bin/env bash
# Record host memory every INTERVAL seconds (default 10) as tab-separated lines:
#   utc  psi_some_avg10  psi_full_avg10  mem_available_kib  swap_free_kib
#   cgroup memory.current (bytes) for: the campaign unit, user@1001.service, k3s/kubepods
#   top 5 processes by RSS (pid:rss_kib:comm)
# Run it as its own system unit next to the campaign (linux/README.md 7.7) so it
# keeps writing when the desktop session is killed. Appends; never truncates.
#   memory-recorder.sh <output file> [campaign unit name] [interval]
set -u
OUT="$1"; UNIT="${2:-}"; INTERVAL="${3:-10}"
CG=/sys/fs/cgroup
cur() { cat "$CG/$1/memory.current" 2>/dev/null || echo NA; }
[ -s "$OUT" ] || printf 'utc\tpsi_some10\tpsi_full10\tavail_kib\tswapfree_kib\tcampaign_b\tuser1001_b\tkubepods_b\ttop_rss\n' >> "$OUT"
while :; do
  some=$(awk '/^some/{split($2,a,"=");print a[2]}' /proc/pressure/memory)
  full=$(awk '/^full/{split($2,a,"=");print a[2]}' /proc/pressure/memory)
  avail=$(awk '/^MemAvailable/{print $2}' /proc/meminfo)
  swapf=$(awk '/^SwapFree/{print $2}' /proc/meminfo)
  camp=NA; [ -n "$UNIT" ] && camp=$(cur "system.slice/$UNIT.service")
  top=$(ps -eo pid=,rss=,comm= --sort=-rss | head -5 | awk '{printf "%s:%s:%s ",$1,$2,$3}')
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$some" "$full" "$avail" "$swapf" \
    "$camp" "$(cur user.slice/user-1001.slice/user@1001.service)" "$(cur kubepods.slice)" "$top" >> "$OUT"
  sleep "$INTERVAL"
done
