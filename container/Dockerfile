FROM debian@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a
# Acquisition only. The built image and complete installed inventory are retained;
# transitive APT inputs are recorded in packages.lock, not claimed snapshot-rebuildable.
RUN apt-get update && apt-get install -y --no-install-recommends \
 gcc=4:14.2.0-1 g++=4:14.2.0-1 \
 clang-19=1:19.1.7-3+b1 clang-tidy-19=1:19.1.7-3+b1 \
 clang-format-19=1:19.1.7-3+b1 libclang-rt-19-dev=1:19.1.7-3+b1 \
 llvm-19=1:19.1.7-3+b1 llvm-19-tools=1:19.1.7-3+b1 \
 cmake=3.31.6-2 ninja-build=1.12.1-1 python3 python3-jsonschema=4.19.2-6 \
 git binutils bubblewrap ca-certificates && rm -rf /var/lib/apt/lists/*
ENV PATH=/usr/lib/llvm-19/bin:/usr/bin:/bin
RUN mkdir /opt/safety && dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > /opt/safety/packages.lock
WORKDIR /work
USER 65534:65534
# lit's stable PyPI release, no dependencies. Retained wheel digest is locked.
USER root
COPY lit-23.1.2-py3-none-any.whl /opt/safety/
RUN python3 -m zipfile -e /opt/safety/lit-23.1.2-py3-none-any.whl /opt/lit
ENV PYTHONPATH=/opt/lit
USER 65534:65534
