# The data centre's door to the VPS.
#
# Everything the pipeline writes goes to the VPS database, and the LLM it calls
# is on the VPS -- but neither port is on the internet, and neither should be.
# This container holds one ssh session with two forwards and nothing else.
#
# It is a container rather than a host process for one reason: the data centre
# has no passwordless sudo, so there is no systemd unit available, and a bare
# `nohup ssh` does not survive a reboot. `restart: unless-stopped` does.
FROM alpine:3.20
RUN apk add --no-cache openssh-client
# ssh refuses a key the whole world can read, and a bind-mounted key arrives
# with the host's permissions. Fix it at start rather than trusting the host.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
