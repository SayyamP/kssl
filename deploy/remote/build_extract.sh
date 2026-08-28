#!/bin/sh
# Build the CPU extraction image. ~10 min, mostly torch and the GLiNER weights.
cd /home/sysadmin/kssl/app/deploy/extraction || exit 1
docker build -t kssl-extraction:latest . > /home/sysadmin/kssl/bench/build.log 2>&1
echo "BUILD rc=$?" >> /home/sysadmin/kssl/bench/build.log
