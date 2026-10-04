# Retained runner

The built image's immutable local identity, package inventory, binary hashes,
architecture/libc and recipe limitations are in toolchain.lock.json. Qualification
uses `docker --pull=never` and requires that exact retained image. No host install
is performed. Acquisition used a pinned Debian base, versioned top-level package
inputs and verified stable lit wheel; all installed transitive versions are in
packages.lock and immutable built layers. APT sources were mutable at acquisition,
so the recipe alone is not claimed snapshot-rebuildable. Retain the built image or
transfer it with docker save/load separately from the small starter bundle. Loading
an image must be followed by identity verification and target-runner qualification.

Runtime sandbox settings are documented in docs/trust-boundary.md. Native programs
have no production network or container-launch privilege. Bootstrap never disables
ASLR or host security to make a runtime pass. Main local CFL build uses this exact
image and documented external compiler/runtime variables; remote upstream images
are separately pinned and configured, never claimed locally or remotely executed.
