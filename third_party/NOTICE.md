# Third-party notices

## Project license

The project's own files are under the MIT license; see `LICENSE` at the
repository root (Copyright (c) 2026 MarketData-App). The MIT license does not
apply to the third-party files listed below. Each of them keeps its own license.
A project that `./tools/safety instantiate` creates keeps its own code under the
license that its owner chooses; the exported framework files stay under MIT.

For the GPL and LGPL binaries in this repository and in the published images,
`SOURCE-OFFER.md` at the repository root gives the directions to their source
code and a written offer; `third_party/source-availability.json` is the source
listing. In these files, "this repository" means
MarketData-App/safe-c-environment. They state MarketData-App's arrangement for
its own distribution. A project that publishes the copied Debian binaries
(`third_party/developer/`, `container/foundation-inputs/`) distributes them
itself and needs its own source arrangement.

## Retained upstream files

Exact revisions, paths and hashes are in `upstream.lock.json`. The original
license and file notices are retained next to the minimal files under
`third_party/originals/`.

- LLVM (llvm/llvm-project): Apache-2.0 WITH LLVM-exception, including the
  historical file-scope terms in `compiler-rt/LICENSE.TXT`.
- lit 23.1.2 (retained wheel `container/lit-23.1.2-py3-none-any.whl`):
  Apache-2.0 WITH LLVM-exception.
- Juliet Test Suite for C/C++ 1.3 (arichardson/juliet-test-suite-c): NIST
  public domain / CC0-1.0. Version 1.3.1 is not claimed.
- cmake-init (friendlyanon/cmake-init): templates under the Unlicense;
  generator and interpreter under GPL-3.0-or-later. Only its reviewed template
  interpreter was executed, inside isolated assessment scratch. No generator
  implementation is incorporated into first-party code or ordinary checks.
- ClusterFuzzLite (google/clusterfuzzlite): Apache-2.0.
- oss-fuzz-gen (google/oss-fuzz-gen) and Mull (mull-project/mull): Apache-2.0,
  README and LICENSE retained for reference only.
- cbmc-starter-kit (model-checking/cbmc-starter-kit): MIT-0, reference only.
- Trail of Bits skills (trailofbits/skills): CC-BY-SA-4.0, retained for
  reference only and attributed to Trail of Bits. The first-party protocol is
  independently written from the assignment.
- Trail of Bits buttercup (trailofbits/buttercup): AGPL-3.0-only, verbatim
  README and LICENSE for reference only; no code is used.
- actions/checkout and actions/upload-artifact: MIT.

## Adapted files

These files are modified copies of upstream files. Each Apache-2.0 file carries
a header that names its origin, its license and the change (Apache-2.0 section
4(b)). The public-domain and Unlicense files need no such header. The complete
change is the matching patch in `third_party/patches/`, and
`upstream.lock.json` (`adaptations`) binds original, patch and result.

- `safety/qualification/C01`-`C08`, `C11`, `C21/bad.c`: LLVM compiler-rt tests,
  Apache-2.0 WITH LLVM-exception.
- `safety/qualification/C10`, `C16`, `C22/bad.c`: Juliet 1.3, public domain /
  CC0-1.0.
- `third_party/adapters/clusterfuzzlite-actions/*/action.yml`: ClusterFuzzLite,
  Apache-2.0; the runner image is pinned to a digest.
- `cmake/prelude.cmake`: cmake-init template, Unlicense.

## Foundation dependency

The pinned GLib 2.90.0 core (LGPL-2.1-or-later; some files under the other
licenses in `third_party/foundation-notices/glib-*.txt`) and PCRE2 10.46
(BSD-3-Clause WITH PCRE2-exception; full text in
`third_party/foundation-notices/pcre2-COPYING`, copied from `LICENCE.md` in the
pinned source archive) are retained in `container/foundation-inputs/`. The lock
is `foundation.lock.json`. Meson 1.9.2 (Apache-2.0) and the Debian packages
`pkgconf-bin`, `libpkgconf3`, `libffi-dev` and `zlib1g-dev` are build inputs
only; their notices are in `third_party/foundation-notices/`. Additional
upstream components are not approved application APIs.

### GLib modification notice

MarketData-App changed GLib 2.90.0 on 2026-10-05. The change adds typed
callback ABI bridges for the selected upstream test paths and for the narrowly
inventoried library callbacks that those tests exercise. It adds no sanitizer
suppression and changes no exported API or ownership semantics. Changed files:
`glib/tests/bytes.c`, `string.c`, `array-test.c`, `hash.c`, `error.c`,
`autoptr.c`, `utf8-validate.c`, `overflow.c`, `refcount.c`, and
`glib/gbytes.c`, `glist.c`, `gslist.c`, `gtestutils.c`, `garray.c`,
`gvarianttypeinfo.c`, `gqueue.c`. The build applies the change with
`container/glib-test-compat.py`. The record of the change is
`third_party/patches/glib-selected-tests-callback-abi.patch`, and
`container/glib-test-compat.json` binds the original and adapted file hashes.
This notice is kept here and not inside the patch file, because the patch hash
is part of the qualified foundation build record in the SDK image.

### Linking

First-party code links GLib dynamically. The foundation also builds a static
`libglib-2.0.a`. A project that links GLib statically into a program and
distributes that program must let its users relink the program with a modified
GLib (LGPL-2.1 section 6). Dynamic runtime linking does not complete every
distribution duty: retain the source, recipe and patch material, preserve the
notices, and review the eventual distribution and the replacement or relinking
mechanism.

## Developer image layer

The Debian packages of the developer layer are retained as `.deb` files in
`third_party/developer/archives/` and as extracted layers in
`third_party/developer/payload/`. Their Debian copyright files are in
`third_party/developer/notices/`. `developer.lock.json` records each package,
its notice and its license tags, and
`third_party/developer/provenance/source-provenance.json` records the exact
Debian source packages. Several of these packages are under the GPL or LGPL;
`SOURCE-OFFER.md` covers them.

## Bench Python wheels (performance lab)

Pinned PyPI wheels are retained in third_party/developer/wheels (pieces of at most
32 MiB) with provenance in third_party/developer/provenance/wheel-selection.json and
are extracted, without tests or bytecode, into /opt/bench-python of the developer image
only. The framework image holds only the wheels that framework code imports (owner
decision 2026-10-13). Their license files are retained in
third_party/developer/notices/<name>/. The owner confirmed the license basis on 2026-10-15
(developer.lock.json license_review). The review status of each notice stays PENDING.

| Distribution | Version | License (from its notice file) | Notice |
|---|---|---|---|
| numpy | 2.3.3 | BSD-3-Clause; bundled lapack-lite BSD-3-Clause, dragon4 MIT, libdivide Zlib, Meson Apache-2.0, spin BSD-3-Clause, tempita MIT, OpenBLAS BSD-3-Clause, LAPACK BSD-3-Clause-Open-MPI, GCC runtime GPL-3.0-or-later WITH GCC-exception-3.1, libquadmath LGPL-2.1-or-later | numpy/LICENSE.txt |
| pyperf | 2.9.0 | MIT | pyperf/COPYING |
| psutil | 7.1.0 | BSD-3-Clause | psutil/LICENSE |

The numpy wheel bundles `numpy.libs/libgfortran*.so` (GPL-3.0-or-later WITH
GCC-exception-3.1) and `numpy.libs/libquadmath*.so` (LGPL-2.1-or-later).
`SOURCE-OFFER.md` (section 5.2) covers them.

## Container images

The SDK image (`toolchain.lock.json`, package list `container/packages.lock`)
and the framework developer image that `developer.lock.json` names are in the
v3 release archive (`images-sdk-developer-v3`) that `ci/image-bundle.json`
describes. Each Debian package in them keeps its own license; its notice is in
`/usr/share/doc/<package>/copyright` inside the image. The v3 release is the
published release. The earlier release `images-sdk-developer-v2` holds the SDK
image and the earlier developer image. `SOURCE-OFFER.md` covers the GPL
and LGPL components of both developer images.

## License review state

An agent engineering license review (LR1, 2026-10-13) was made. It is not legal
advice. No legal team has approved the distribution. The owner confirmed the
license basis of the v3 image bundle on 2026-10-15: MIT for the project's own
files, and `SOURCE-OFFER.md` as a separate document for the included
third-party components, each under its own license.
