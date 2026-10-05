# Optional equivalent allowlisted assembly; tools/runtime.py uses bounded import.
# Inputs MUST be the exact tested artifacts retained in runtime-smoke.json.
FROM scratch
COPY demo /demo
COPY libc.so.6 /lib/x86_64-linux-gnu/libc.so.6
COPY ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2
USER 1001:1001
WORKDIR /work
ENTRYPOINT ["/demo"]
# Effective restrictions come from safety/container-policy.json, not this file.
