# Where the data centre is right now  (2026-08-26)

## The incident, in one paragraph

`isolate_sockets.sh --apply` (an earlier version) moved the corpus Postgres,
MinIO and the sipri stack onto cores 0-19 -- the crawler's twenty cores -- and
forced their memory to NUMA node 0 while all their resident pages were on node
1. Seven crawler instances targeting 90% CPU plus the data stores on one socket
took the box to **load 653**. sshd could not be scheduled and the machine was
unreachable for about half an hour. Nothing was lost; no data was touched.

`isolate_sockets.sh` has since been cut down so it can only bind memory to the
socket a container is ALREADY on. It can no longer move anything between
sockets. See the comment block at the head of that file.

## The backlog that is still draining

Load stays high after the crawl stops because Linux load average counts
**D-state** (uninterruptible IO/reclaim), not just runnable threads. The
`--cpuset-mems 0` pin on Postgres/MinIO means every access to a page that lives
on node 1 is a fault the kernel has to satisfy across the interconnect or
migrate. That reclaim work is the backlog. It does not clear by waiting -- it
clears when the pin is removed.

## What clears it

    docker update --cpuset-cpus 35-39 --cpuset-mems 1 \
      mallory-data-postgres-1 mallory-data-minio-1 mallory-minio-console \
      mallory-sipri-postgres-1 mallory-sipri-minio-1 mallory-sipri-sipri-1 \
      mallory-sipri-crawl-keeper-1

Then the lab models back to their lane, and the L2 dashboard:

    docker update --cpuset-cpus 34    --cpuset-mems 1 llm-ab llm-camofox extraction-lab
    docker update --cpuset-cpus 0-19  --cpuset-mems 0 mallory-l2dash

## Rules learned, both of them the hard way

* **One ssh session to this box at a time.** sshd's `MaxStartups` drops
  connections once ~10 unauthenticated ones are in flight, so a retry loop
  during a slow period locks you out by itself. Half the "outage" was mine.
* **Never apply a cpuset change to every container in one step.** Stage it:
  one container, check `/proc/loadavg`, then the next.

## Fleet state

Maintenance mode is **ON** -- every crawler instance stopped, refill held off:

    POST :8091/api/crawler/fleet/maintenance?on=true   # stop  (current state)
    POST :8091/api/crawler/fleet/maintenance?on=false  # resume

Resuming restored 21 saved jobs last time with nothing lost.


## UPDATE — the box cannot start new processes (2026-08-26, later)

The load backlog **has drained**. What remains is a different fault, proven by
elimination rather than assumed:

* `ssh -v` reaches `Authenticated ... using "publickey"` and `Entering interactive
  session`, then produces nothing for five minutes. A wrong key is refused
  instantly, so sshd's listener and auth are fine.
* `sftp` hangs at the same point.
* `ssh -N -L` opens its local listener and every connection through it times out —
  **including one to `:8091`, which answered through the VPS door seconds earlier.**

Sessions, sftp and forwards share exactly one thing: the per-user sshd child
forked after authentication. That child cannot run. There is therefore no
ssh-based repair — not a command, not sftp, not a tunnel to the Docker socket.

**The box is otherwise healthy.** Through the VPS doors, repeatedly:

    https://187.127.134.12:8443/api/crawler/fleet/health   0.3 s, 7/7 up, 0 crawling
    https://187.127.134.12:8444/api/summary                0.25-0.4 s, Postgres-backed

A machine at load 653 cannot answer a database query in 250 ms. Disk, memory,
Postgres, Docker and networking are all working for resident processes.

**Crawling is stopped and the frontier is intact**: 7 instances up, 0 crawling,
2,092 pending URLs held. Nothing has been lost.

**Recovery needs out-of-band access** — the provider's console/KVM, or a power
cycle. A reboot is safe: every container is `restart: unless-stopped`, the frontier
is durable, and the corpus was never written to. The orchestrator cannot help
(`grep -rnE 'subprocess|os.system|docker.sock' orchestrator/src/` returns nothing).

Until then the test sequence below **cannot run** — it needs `docker` on the host.

## The sequence still to run

1. Probe DC tok/s with maintenance ON  -- the quiet-box baseline
2. `./isolate_sockets.sh --apply` + `./bind_numa.sh` (both now safe)
3. Maintenance OFF, probe again -- crawler and extraction together
4. Collect `metrics.stage_summary` and regenerate PRODUCTION.html on the VPS
