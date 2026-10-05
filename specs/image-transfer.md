# Locked image transfer

This is outer-controller data acquisition, not a candidate build, application,
runner approval or image upgrade. MarketDataApp owns the transfer adapter. It
transfers only the exact SDK and development image IDs in the two current locks.
No container starts, no Docker flags or endpoint come from the caller, and no
dependency recipe runs. Ordinary safety checks remain offline.

`ci/images export --destination DIRECTORY` requires a new absolute private
directory outside the source tree. The path must equal its resolved canonical
path; parent traversal and links are rejected before creating directories or
consulting Docker. The local approved daemon must contain both
locked images. The output is `images.tar.gz` and a transfer receipt identifying
the archive hash, byte size, exact image IDs, lock hashes and pending publication
licensing. Export preserves config identities; it does not promise that rebuilding
the acquisition Dockerfiles would reproduce those identities.

`ci/images verify --archive FILE --sha256 HASH` validates a regular non-symlink
gzip Docker-save archive, its caller-supplied lowercase SHA-256 and exactly the
two separately locked image identities. A transfer hash never authorizes a baseline.
Locked IDs may identify a classic image config or an OCI index/manifest. Every
referenced blob must match its digest and declared size, and an OCI archive must
contain exactly the two locked roots. Each root selects exactly one Linux amd64
runtime image. Configs must match the referenced digests; no runtime image may
introduce an entrypoint, volume or health check. BuildKit attestations require the
unknown platform, the exact native-manifest reference, empty config and in-toto
data layers. They are data, never additional runnable images. Required members
must exist, and unreferenced payload is rejected.
Archive member paths are relative and canonical; links, special files, duplicate
members, missing images and unregistered image configs are rejected. Archive and
expanded data each have a 3 GiB ceiling, 4096 members, and a 1 MiB metadata ceiling.
Zero-byte archives, one image, one-past limits and digest/config disagreement
are failures. Exact finite byte/member limits are permitted. Shared layer references between the two images are permitted.

`ci/images load` performs the same verification before the fixed local Docker
image-load operation. It then inspects both actual loaded IDs. This does not
authorize that daemon or launch candidate code. A new machine still needs its
independently approved runner policy and actual complete qualification.

All operations reject inherited Docker endpoint/config overrides. The Docker
client uses the single policy's endpoint and context. Metadata commands have a
120-second finite deadline and bounded opaque output; failures report only type
and receipt path. Compression uses a fixed gzip timestamp and bounded source
bytes. A failed export preserves opaque management evidence and removes partial
payload files; it never overwrites an existing destination. Loading a verified
archive is idempotent and does not prune other Docker resources.

Tests run through the protected launcher. Transfer verification tests use small
data archives and prove rejection before the load callback. Actual export/load
round trips additionally check the two retained image IDs without modifying locks.
Publishing the payload remains pending owner licensing review and explicit owner
authorization. The current machine-pinned daemon policy remains unchanged.
