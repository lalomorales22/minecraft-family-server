FROM alpine:3.20
RUN apk add --no-cache dnsmasq
EXPOSE 53/udp 53/tcp
# Forward everything to public DNS; the hostnames to redirect are added
# as --address arguments in docker-compose.yml.
# --except-interface=lo turns off dnsmasq's "local subnets only" default, which
# would otherwise drop console queries arriving through Docker's port forwarding.
ENTRYPOINT ["dnsmasq", "--keep-in-foreground", "--user=root", "--log-facility=-", \
            "--except-interface=lo", \
            "--no-resolv", "--no-hosts", "--server=8.8.8.8", "--server=1.1.1.1"]
