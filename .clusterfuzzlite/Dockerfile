# Remote adapter image is distinct from the locally qualified Debian toolchain.
# Configured and pinned, but remote execution is not claimed.
FROM gcr.io/oss-fuzz-base/base-builder@sha256:4d95d77396ce573bbfca794166cd2f1e28df5b3445a45132e52ef0e4ff7f566b
COPY fuzz /src/fuzz
WORKDIR /src
COPY .clusterfuzzlite/build.sh /src/build.sh
