# Retained upstream notices

Exact revisions and hashes are in upstream.lock.json. Original license and file notices are retained alongside the minimal files. LLVM: Apache-2.0 WITH LLVM-exception, including historical file-scope terms in compiler-rt/LICENSE.TXT. Juliet 1.3: NIST public domain / CC0-1.0; 1.3.1 is not claimed. cmake-init templates: Unlicense; generator/interpreter: GPL-3.0-or-later. Only its reviewed template interpreter was executed inside isolated assessment scratch; no generator implementation is incorporated into first-party code or ordinary checks. Trail of Bits material: CC-BY-SA-4.0 retained for reference only, attributed to Trail of Bits; first-party protocol is independently written from the assignment. ClusterFuzzLite and actions: see their retained LICENSE files. First-party publication licensing awaits the owner.

## Foundation dependency amendment

Pinned GLib 2.90.0 core (LGPL-2.1-or-later) and PCRE2 10.46 are retained in
container/foundation-inputs, with their upstream notices in
third_party/foundation-notices. The lock is foundation.lock.json. Meson 1.9.2 and
Debian pkgconf/configuration-header packages are build inputs only. Additional
upstream components are not approved application APIs. A retained, hash-inventoried callback ABI patch adapts selected test
registrations/callbacks and the narrowly inventoried library callbacks exercised by those tests. Exact
original/adapted identities are in container/glib-test-compat.json. Dynamic runtime linking does not complete the owner's
distribution obligations: retain source/recipe/patch material, preserve notices,
and independently review the eventual distribution and replacement/relinking
mechanism. The user's first-party code is not relicensed.
