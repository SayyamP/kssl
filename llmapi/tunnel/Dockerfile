# One SSH forward from VPS-B to one remote model server, plus the watchdog that proves
# the forward still carries traffic. Parameterised: one image, one container per remote.
FROM alpine:3.20

# curl is not optional here -- it IS the health check. `nc -z` only proves something
# accepted a TCP connection, which a half-open ssh forward will happily do while the
# service behind it is gone.
RUN apk add --no-cache openssh-client curl

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
