#!/bin/sh
# Give extraction a socket of its own.
#
#   ./isolate_sockets.sh          # show what it would do
#   ./isolate_sockets.sh --apply  # do it
#
# THE PROBLEM THIS SOLVES
# -----------------------
# The box is two sockets: NUMA node 0 = cores 0-19, node 1 = cores 20-39. The
# crawler already had node 0's CORES and extraction node 1's, and extraction was
# still 6.7x slower with the crawler running than without it (1.20 vs 8.05
# tok/s, measured 2026-08-26). Dividing cores had changed nothing.
#
# The reason is in `docker inspect`: every crawler container had
#
#     cpus=0-19   mems=ANY
#
# `mems=ANY` means its memory can be allocated on EITHER node. So seven crawlers
# executing on node 0 were allocating and streaming memory on node 1 -- the very
# memory controllers the extraction model depends on -- and paying a cross-socket
# hop themselves for the privilege. Pinning cores without pinning memory is half
# a fence.
#
# WHAT IT DOES
# ------------
#   node 0 (cores 0-19): the crawler fleet and its helpers -- mems=0
#   node 1 (cores 20-39): extraction (20-33) and the data stores (35-39), mems=1
#
# This binds MEMORY to the socket each thing already runs on. It does not move
# anything between sockets -- an earlier version moved the data stores onto the
# crawler's cores "to clear node 1" and took the box to load 653. Rebalancing
# what runs where is a separate, staged exercise; this script only stops the
# crawler allocating on the far socket.
#
# WHAT IT CANNOT DO
# -----------------
# `--cpuset-mems` governs FUTURE allocations. A long-lived process that already
# holds pages on the wrong node keeps them until it restarts. The crawler's
# browser processes are recycled constantly so they convert quickly; Postgres and
# MinIO do not, so part of the gain only arrives when they are next restarted.
# Expect an improvement now and a larger one after a maintenance window -- do not
# read a partial gain as the change not working.
#
# Co-tenants (deploy-p0-*) are deliberately NOT touched. They are not ours.
set -eu

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# Things that ALREADY run on node 0's cores. This list binds their memory to the
# socket they are already on; it must never be used to move something onto those
# cores.
#
# Do NOT add mallory-data-*, mallory-sipri-* or mallory-minio-console here. An
# earlier version did, to "clear node 1" for extraction. Seven crawler instances
# plus the corpus Postgres, MinIO and sipri on twenty cores took this box to
# **load 653** -- sshd could not be scheduled and the machine was unreachable for
# half an hour. The stores keep cores 35-39 and mems=1. Extraction shares socket
# 1's memory bandwidth with them, and that is the accepted cost.
NODE0="mallory-crawler- mallory-camofox-watchdog mallory-hostsolver-relay"

move() {                                  # move <container> <cpus> <mems>
    if [ "$APPLY" = "1" ]; then
        docker update --cpuset-cpus "$2" --cpuset-mems "$3" "$1" >/dev/null
    fi
    printf '  %-34s -> cpus=%-7s mems=%s\n' "$1" "$2" "$3"
}

echo "node 0 (cores 0-19) -- crawler, its stores, the lab models:"
for c in $(docker ps --format '{{.Names}}'); do
    for pat in $NODE0; do
        case "$c" in
            "$pat"*) move "$c" 0-19 0; break ;;
        esac
    done
done

echo "node 1 (cores 20-39) -- extraction, alone:"
move kssl-extract-ollama "${KSSL_OLLAMA_CPUSET:-20-26}" 1
move kssl-autopilot      "${KSSL_EXTRACT_CPUSET:-27-33}" 1
move kssl-bench          "${KSSL_EXTRACT_CPUSET:-27-33}" 1

if [ "$APPLY" = "1" ]; then
    echo
    echo "applied. Cores 34-39 are left empty on purpose: they are node 1's"
    echo "spare memory bandwidth, and nothing else should take them."
else
    echo
    echo "(dry run -- pass --apply to make these changes)"
fi
