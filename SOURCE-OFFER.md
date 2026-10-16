# Source code availability and written offer

Date: 2026-10-13, updated 2026-10-14 (framework developer image, image release v3) and 2026-10-15 (owner confirmation; source URL check and the four former gaps; release v3 published). Distributor: MarketData-App, the GitHub organization that
publishes the repository
[MarketData-App/safe-c-environment](https://github.com/MarketData-App/safe-c-environment).
In this file, "this repository" always means MarketData-App/safe-c-environment.

This repository and its published release assets contain programs and libraries
under the GNU General Public License (GPL) and the GNU Lesser General Public
License (LGPL). MarketData-App does not host their source code. This file tells
you where the exact source code is, and it gives a written offer for it.

This file is not legal advice. The owner confirmed the chosen bases on
2026-10-15.

## 1. Where the source code is

For every Debian binary package that MarketData-App distributes, the exact
Debian source package (the signed `.dsc` file, the upstream `.orig` archives
and the Debian packaging archive) is on the Debian snapshot archive,
`snapshot.debian.org`. These source packages contain the scripts that control
compilation and installation.

- **The source listing:** [third_party/source-availability.json](third_party/source-availability.json).
  It maps each distributed binary package and version to its source package and
  version. For each source package it gives the `snapshot.debian.org` package
  URL, the Debian pool directory, the name of the `.dsc` file and its sha256.
  The signed `.dsc` file lists the sha256 of every other file of the source
  package. The listing was made from the repository's own records:
  `container/packages.lock`, `developer.lock.json`, `foundation.lock.json` and
  the signed Debian trixie indexes `Packages.xz` and `Sources.xz` in
  `third_party/developer/provenance/`. Four binaries that the pinned trixie
  index does not hold resolve in the signed trixie-security index (section 5).
- **The table in section 5** repeats the URL and the `.dsc` sha256 for each of
  the 131 source packages.
- **GLib 2.90.0 (foundation):** the complete source is in this repository
  (section 6).
- **GCC runtime libraries in the numpy wheel:** the numpy 2.3.3 wheel bundles
  `libgfortran` and `libquadmath`. They are not Debian packages. The
  repository does not record their exact source, so the written offer in
  section 3 covers them (section 5.2).

MarketData-App stays responsible for the availability of this source for as
long as it distributes the binaries, and for the periods in section 3. If a
listed location stops working, MarketData-App supplies the source on request
(section 4).

## 2. Which rule applies, in plain words

- **GPL version 3 (also GPL-3.0-or-later), section 6(d).** MarketData-App
  distributes this object code by download from a designated place (the
  repository and the release). Section 6(d) allows equivalent access to the
  Corresponding Source on a different server, run by a third party, when clear
  directions next to the object code say where to find it, and the distributor
  makes sure that the source stays available as long as needed. The third-party
  server is `snapshot.debian.org`. The directions are this file and
  `third_party/source-availability.json`, next to the binaries in this
  repository and next to `images.tar.gz` in the release. (Section 6(b), the
  written offer, applies only to object code in a physical product, so it is
  not the basis here.)
- **LGPL version 3.** It is GPL-3.0 plus additional permissions, and its
  section 4 refers to GPL-3.0 section 6 for combined works. The same section
  6(d) directions apply.
- **GPL version 2 (also GPL-2.0-or-later and GPL-2.0-only, for example git),
  section 3(b).** GPL-2.0 has no third-party-server option. MarketData-App
  therefore gives the written offer in section 3. The snapshot directions are an
  extra help.
- **LGPL version 2.1 or later (also LGPL-2.0-or-later), for the library
  binaries themselves (for example `libc6`, `libglib2.0-0t64`, `libmount1`, the
  elfutils libraries and `libcares2`).** These libraries allow "any later
  version". MarketData-App uses that option and distributes its copies under
  LGPL version 3. The GPL-3.0 section 6(d) directions above therefore apply to
  them.
- **LGPL version 2.1 only (no "or later").** The repository's records name
  these components:
  - `libbabeltrace1` 1.5.11-4+b2 (source `babeltrace` 1.5.11-4, developer
    layer): its Debian copyright file
    (`third_party/developer/notices/libbabeltrace1/copyright`) gives
    `include/babeltrace/list.h` as LGPL-2.1 "only version 2.1"; the rest of
    the package is MIT or GPL.
  - GLib 2.90.0 (foundation): some files are LGPL-2.1-only
    (`third_party/foundation-notices/glib-LGPL-2.1-only.txt`). Its complete
    source is in this repository, next to the binary, as LGPL-2.1 section 4
    asks (section 6).

  For `libbabeltrace1`, LGPL-2.1 section 4 asks for the source next to the
  library or equivalent access from the same place, and MarketData-App does
  not host it. The basis that MarketData-App uses is the written offer in
  section 3 together with the snapshot directions. The owner confirmed this
  basis on 2026-10-15. If counsel later does not accept it, MarketData-App
  publishes the `babeltrace` source package next to the binaries.

  The repository does not record the license of each SDK package. If an SDK
  library is LGPL-2.1-only, the same written offer and directions apply to it,
  and the same confirmation applies.
- **The GCC runtime libraries in the numpy wheel** (`libgfortran`,
  GPL-3.0-or-later WITH GCC-exception-3.1; `libquadmath`, LGPL-2.1-or-later).
  The repository does not record the GCC release or the build of these
  binaries, so it cannot give exact section 6(d) directions. The basis that
  MarketData-App uses is the written offer in section 3. The upstream GCC
  locations in section 5.2 are an extra help. The owner confirmed this basis on
  2026-10-15. If counsel later does not accept it, MarketData-App records the
  exact source and gives directions to it, or publishes it next to the
  binaries.
- **LGPL version 2.1, section 6(c),** applies to a "work that uses the Library"
  (a program that links the library). For such programs in the images, the
  written offer in section 3 also gives the materials that section 6(c) asks
  for.
- **LGPL version 2.0, GPL version 1 and other versions** have equivalent rules.
  The written offer in section 3 and the directions in section 1 apply to them
  in the same way.

Each component stays under its own license. This file does not change any
license. The project's own MIT license (see [LICENSE](LICENSE)) does not apply
to these components.

## 3. The written offer

MarketData-App offers to give **any third party** a complete machine-readable
copy of the **complete corresponding source code** of each GPL- or
LGPL-licensed component listed in `third_party/source-availability.json`
(`binaries` and `other_components`) and in section 6.

- **Duration.** At least **three years** after the last date on which
  MarketData-App distributes the binary of that component in this repository
  or as a release asset.
- **Who can accept it.** Any person or organization. You do not have to show
  that you received a binary.
- **Charge.** A download link costs nothing. A physical medium costs no more
  than the cost of physically performing the distribution: the medium and the
  postage.
- **Medium.** A medium customarily used for software interchange: normally a
  download, or on request a physical storage device.

## 4. How to ask

1. Open an issue in the public repository
   [MarketData-App/safe-c-environment](https://github.com/MarketData-App/safe-c-environment/issues).
2. Give the issue the title `Source request`.
3. Name each component and version from `third_party/source-availability.json`
   or section 6, or write `all`.
4. Name the release asset or the commit that holds the binary, if you know it.
5. Say whether you want a download link or a physical medium.

Do not put personal data in the public issue. If a physical medium is
necessary, the project tells you in the issue how to send a postal address
privately.

## 5. Source packages and directions

| Distribution | Identity | Record |
|---|---|---|
| Release `images-sdk-developer-v3`, asset `images.tar.gz` (512,160,947 bytes). It is the published release. | sha256 `e8c9c5d2bfb96073965da6c83260a5aa6f7a9703bbf05307c32c41976b51d99f` | `ci/image-bundle.json` |
| Release `images-sdk-developer-v2`, asset `images.tar.gz` (496,826,156 bytes). It is an earlier release. | sha256 `ea82b842693ae0382e4d7e6448ce43fff1c956ddf4557c57b01500a346c8f624` | earlier versions of `ci/image-bundle.json` |
| SDK image in both `images.tar.gz` archives (208 Debian packages) | image ID `sha256:fabbb83309d3767840466b4ccb82a1da9940b76d76ae7d16eedf04d6a540d179` | `toolchain.lock.json`, `container/packages.lock` |
| Framework developer image in the v3 `images.tar.gz` (SDK image plus 24 Debian packages plus the wheels numpy 2.3.3, pyperf 2.9.0 and psutil 7.1.0 under `/opt/bench-python`) | image ID `sha256:323daee40b10313e19988592dcb32bb7f0aa6a7e72301ed85a1a9f61aed82e30` | `ci/image-bundle.json` (`image_ids`), `developer.lock.json`, `third_party/developer/payload/manifest.json` |
| Developer image in the v2 `images.tar.gz` (SDK image plus the same 24 Debian packages) | image ID `sha256:9b90ce96e4e0b2dc7f11a16d8c5fcd79e59672fccd9134163cea428e4fe9c1a6` | earlier versions of `ci/image-bundle.json` (`image_ids`) |
| Debian packages in this repository | `third_party/developer/archives/*.deb`, `third_party/developer/payload/*`, `container/foundation-inputs/*.deb` | `developer.lock.json`, `foundation.lock.json` |
| Python wheels in this repository | `third_party/developer/wheels/*.whl` | `third_party/developer/provenance/wheel-selection.json` |

The listing covers 236 binary packages (208 SDK, 24 developer, 4 foundation
build inputs). It resolves all 236 of them to 131 source packages. The repository
does not record the license of each SDK package, so the directions cover every
listed package, whatever its license. Both developer images hold the same 24
developer packages at the same versions. The listing also names two GPL/LGPL
libraries that the numpy wheel bundles (`other_components`, section 5.2).

**Gaps and checks.**

- Four SDK binary versions are not in the pinned trixie index:
  `libssl3t64`, `openssl` and `openssl-provider-legacy` 3.5.7-1~deb13u3, and
  `linux-libc-dev` 6.12.111-1. On 2026-10-15 they were resolved in the signed
  trixie-security index (InRelease of 30 Sep 2026, snapshot.debian.org archive
  `debian-security` 20260930T060347Z; the signatures check with the pinned
  Debian archive keyring). Their sources are `openssl` 3.5.7-1~deb13u3 and
  `linux` 6.12.111-1, in the table below. The trixie-security index files are
  not kept in this repository.
- The exact source of the two GCC runtime libraries in the numpy wheel is not
  recorded (section 5.2). The written offer in section 3 covers them. The owner
  confirmed this basis on 2026-10-15.
- On 2026-10-15, a read-only HTTP HEAD request to each of the 131 snapshot URLs
  in the listing returned 200.
- `third_party/developer/provenance/source-provenance.json` still records the
  acquisition URLs on `deb.debian.org`. That file is a hash-bound acquisition
  record, so it stays unchanged. The `snapshot.debian.org` directions in this
  file and in `third_party/source-availability.json` replace those URLs for
  source availability. Its source file hashes agree with the listing for all
  24 developer packages.

| Source package | Version | Snapshot directions | `.dsc` sha256 |
|---|---|---|---|
| `abseil` | `20240722.0-4` | https://snapshot.debian.org/package/abseil/20240722.0-4/ | `d127496fe53d7dd0e6770c6eb3f873187fcb76e67fee68c4c8da745b41b7bbc6` |
| `acl` | `2.3.2-2` | https://snapshot.debian.org/package/acl/2.3.2-2/ | `1f42130ccb5442fe2db2aee1dcc03c51a31512dd2519a38e8fc9270c5abbc807` |
| `apt` | `3.0.3` | https://snapshot.debian.org/package/apt/3.0.3/ | `ccf1666e5b268d76bf62aafb22db089a2fdae9c17d1d1c446546b3621768add7` |
| `attr` | `1:2.5.2-3` | https://snapshot.debian.org/package/attr/1%3A2.5.2-3/ | `c2ae3e15db059029030ddf4fdac179d8f90d423f2310a6ef8c745ba28ac18b0a` |
| `audit` | `1:4.0.2-2+deb13u1` | https://snapshot.debian.org/package/audit/1%3A4.0.2-2+deb13u1/ | `f72198219d4a50967e328a143c9c0a7ba981c8f3790b2880465b8a80ac33850e` |
| `babeltrace` | `1.5.11-4` | https://snapshot.debian.org/package/babeltrace/1.5.11-4/ | `c4d2209e9f7fd6b5b5885f75c23814e424e7a8f03201e08e78a4d333ddfa6e19` |
| `base-files` | `13.8+deb13u7` | https://snapshot.debian.org/package/base-files/13.8+deb13u7/ | `6240b5a02fc32bd6d925bb7776e00c467e80d930f8cf3c4a20c299ce692dc7e4` |
| `base-passwd` | `3.6.7` | https://snapshot.debian.org/package/base-passwd/3.6.7/ | `23dafe71f85d7595d9e20efba17729c1c975a33bd469cf09bfad9e96b1f542f3` |
| `bash` | `5.2.37-2` | https://snapshot.debian.org/package/bash/5.2.37-2/ | `7e5f6d5a26093e812f8841d5cf3245054102e86986017d8edd859417b03707f9` |
| `binutils` | `2.44-3` | https://snapshot.debian.org/package/binutils/2.44-3/ | `5abd1ae1adb61fd8ecbadfdc16668738668e81c745884aefa0ce97791b2a74b8` |
| `brotli` | `1.1.0-2` | https://snapshot.debian.org/package/brotli/1.1.0-2/ | `39b06802a852629132d549a7f7449dee7f435e801706714a4bc2ea2f15b28f36` |
| `bubblewrap` | `0.12.0-1~deb13u1` | https://snapshot.debian.org/package/bubblewrap/0.12.0-1~deb13u1/ | `1abef77e6c35ce6c48c8969d31bffcc7a589bfd8e8fea9284fd8d77750f01d39` |
| `bzip2` | `1.0.8-6` | https://snapshot.debian.org/package/bzip2/1.0.8-6/ | `cd3bfd77254a6b5ef1be144bdc90a0dd374bc8206afd98ba4abf828741b79820` |
| `c-ares` | `1.34.5-1+deb13u1` | https://snapshot.debian.org/package/c-ares/1.34.5-1+deb13u1/ | `8848358552603070f98f37679a9361b4da8405b841bbf59d002556571670f7f1` |
| `ca-certificates` | `20250419` | https://snapshot.debian.org/package/ca-certificates/20250419/ | `3fc919369a3b84e34a959faa8bdffb9bd2c5a7d4a948a4b07a09a5d43e257030` |
| `cdebconf` | `0.280` | https://snapshot.debian.org/package/cdebconf/0.280/ | `36cdaa45fca445d2164fbdd81faad9918d748fa703678d8af237354d5744b1d1` |
| `cmake` | `3.31.6-2` | https://snapshot.debian.org/package/cmake/3.31.6-2/ | `70a8dfd49b8bb8735f617986330f23af8deae876c6c30c036e6694edfe2c5b54` |
| `coreutils` | `9.7-3` | https://snapshot.debian.org/package/coreutils/9.7-3/ | `c3a207e3aaad165765c7a6fab89045f5fd20035fea6830b9f9ebbb92ebfbff89` |
| `curl` | `8.14.1-2+deb13u5` | https://snapshot.debian.org/package/curl/8.14.1-2+deb13u5/ | `9a9a2c95cdc8b5d76892c70858f25eaf2dc0b0a475a1e43e0b4ad428414752df` |
| `cyrus-sasl2` | `2.1.28+dfsg1-9` | https://snapshot.debian.org/package/cyrus-sasl2/2.1.28+dfsg1-9/ | `179cda376ee9f9a54098f902174299dd183ae78c703f72b86bd4c3297db4c153` |
| `dash` | `0.5.12-12` | https://snapshot.debian.org/package/dash/0.5.12-12/ | `589efc4d87a4ae4745c273bdb33198d7c4f28a71736a8ece81d3677cf9c6e5ce` |
| `db5.3` | `5.3.28+dfsg2-9` | https://snapshot.debian.org/package/db5.3/5.3.28+dfsg2-9/ | `045f392c75dffc9d4f3bd44978b90ca8d45b935cf0ae4202bf79a760f2ce07b1` |
| `debconf` | `1.5.91` | https://snapshot.debian.org/package/debconf/1.5.91/ | `1aa3ceaef24ef533cfffe7f9ca750c6325dbaea86a7abca77cb4439ceae930d8` |
| `debian-archive-keyring` | `2025.1` | https://snapshot.debian.org/package/debian-archive-keyring/2025.1/ | `09604bd8d4562a1e942e5d1a19a6b82447cbdeb2e7c7f0df7c32a2503647ea47` |
| `debianutils` | `5.23.2` | https://snapshot.debian.org/package/debianutils/5.23.2/ | `471b65deec232bb033f3e3e06d5bf64dac0ced474c6fd61d41538f3f3de876f8` |
| `diffutils` | `1:3.10-4` | https://snapshot.debian.org/package/diffutils/1%3A3.10-4/ | `087b414ddfc92161a30186926bc4b4ac02c7cba589b0323561cacd54c8b48392` |
| `dpkg` | `1.22.22` | https://snapshot.debian.org/package/dpkg/1.22.22/ | `fc481d9b87cd4416cd55673cc1fa716b57480a6b23253ac0d87c1abbfad4c964` |
| `e2fsprogs` | `1.47.2-3` | https://snapshot.debian.org/package/e2fsprogs/1.47.2-3/ | `860abb653ecbe01a11bb7e41c9e09a45e83847bffa585f7a3d3c0f9401c9d4bb` |
| `elfutils` | `0.192-4` | https://snapshot.debian.org/package/elfutils/0.192-4/ | `37d101658c45a25afc15d2053a1378df2381dadbb368e262ede2cea79241779f` |
| `expat` | `2.8.3-1~deb13u1` | https://snapshot.debian.org/package/expat/2.8.3-1~deb13u1/ | `d17f15fe413a553c72185d2d00448b87db72354e0d8fa6099ad19ee19e7117af` |
| `findutils` | `4.10.0-3` | https://snapshot.debian.org/package/findutils/4.10.0-3/ | `fa6b67056d9e5b4d8edbfc8ab95ac15ac769b140284426973f6a1ef07a4594ec` |
| `gcc-14` | `14.2.0-19` | https://snapshot.debian.org/package/gcc-14/14.2.0-19/ | `7db1e202cce66617e9134a662c877a3a773de5b612fd52179815877e0ecfb847` |
| `gcc-defaults` | `1.220` | https://snapshot.debian.org/package/gcc-defaults/1.220/ | `abfa2d362033435385e733f97d0cace1fbc917fd4160c81cc89abac38d3cdc37` |
| `gdb` | `16.3-1` | https://snapshot.debian.org/package/gdb/16.3-1/ | `d7a8760ea307a7859b44c2d5b8523bfaa1f3bcda26fa55f3d90768b15a3f1138` |
| `gdbm` | `1.24-2` | https://snapshot.debian.org/package/gdbm/1.24-2/ | `28acecf1cf00240942833c04079a02bb4c199a48faa1f4ca90f0ea9b79dc5841` |
| `git` | `1:2.47.3-0+deb13u1` | https://snapshot.debian.org/package/git/1%3A2.47.3-0+deb13u1/ | `41ee783af84774dfab31ff6af54a07f70513dd09914e2d622626f4dfecae0a86` |
| `glib2.0` | `2.84.4-3~deb13u5` | https://snapshot.debian.org/package/glib2.0/2.84.4-3~deb13u5/ | `2587beb2f5b90511d0c88a7595c1d3b3ea7a5b7e6582713ecae3713864012858` |
| `glibc` | `2.41-12+deb13u4` | https://snapshot.debian.org/package/glibc/2.41-12+deb13u4/ | `0915324aa646bb99abfaa9aa6ecb734b30babd28454a3e51f3152912370fbd3e` |
| `gmp` | `2:6.3.0+dfsg-3` | https://snapshot.debian.org/package/gmp/2%3A6.3.0+dfsg-3/ | `f7b64af28f52b7346bb8581e01d3c19daf769639345f234f8ae1e29c42171443` |
| `gnutls28` | `3.8.9-3+deb13u4` | https://snapshot.debian.org/package/gnutls28/3.8.9-3+deb13u4/ | `f1153e91212bdf60acf66cb62713ad4ed577f2e85f578a04df31a5619624c1e1` |
| `grep` | `3.11-4` | https://snapshot.debian.org/package/grep/3.11-4/ | `dd6f8eb933bc05446e483f7792c8bf0a1aba9d498e65c6ccafe64e9bf27ac054` |
| `grpc` | `1.51.1-6` | https://snapshot.debian.org/package/grpc/1.51.1-6/ | `ba7c21a2833c9a4b483135bf2e8757e3fc88fa967413c6bf00fab40392f421c5` |
| `gzip` | `1.13-1+deb13u1` | https://snapshot.debian.org/package/gzip/1.13-1+deb13u1/ | `0c25763da4f7242fbe7e9185b69bcb3f986011b04446b66a84c52bbdf731d308` |
| `hostname` | `3.25` | https://snapshot.debian.org/package/hostname/3.25/ | `80aadf116c3423044be69a4cef8ba2766f412bd4d46a500aacb61f303c19c4ef` |
| `init-system-helpers` | `1.69~deb13u1` | https://snapshot.debian.org/package/init-system-helpers/1.69~deb13u1/ | `873082d72727267b6207e38df47e3002aeb0ed554f876db17c7bbfeb26174ee6` |
| `intel-processor-trace` | `2.1.2-1` | https://snapshot.debian.org/package/intel-processor-trace/2.1.2-1/ | `949674199c9ef5028d3bd1006e2cb2f55172f875f0129ebdf1fa494f35672aa2` |
| `isl` | `0.27-1` | https://snapshot.debian.org/package/isl/0.27-1/ | `35ceb67dbb1b4098431b184e342143c2bd94c4a41ebfb3a983e3be31440b0453` |
| `jansson` | `2.14-2` | https://snapshot.debian.org/package/jansson/2.14-2/ | `6296ddd9c0a022bd1b70074aefb171cfcdf5694a04ffd32b35fd66097621af87` |
| `json-c` | `0.18+ds-1` | https://snapshot.debian.org/package/json-c/0.18+ds-1/ | `30f35cab8f920a6481e5fb8e58e789c59dd92945b82a2bcb9cf640a6e6e88594` |
| `keyutils` | `1.6.3-6` | https://snapshot.debian.org/package/keyutils/1.6.3-6/ | `e63869474c390d5d5bdee8492f7b2f4d6034ff10d8190da18593620c0f35fbf8` |
| `krb5` | `1.21.3-5+deb13u1` | https://snapshot.debian.org/package/krb5/1.21.3-5+deb13u1/ | `d17d2840bc97fea2c2375245569ca67838a2b557ee083c6cbe42b129a317212c` |
| `libarchive` | `3.7.4-4+deb13u1` | https://snapshot.debian.org/package/libarchive/3.7.4-4+deb13u1/ | `0579aa62c9b547a520fd3af48382b1b071c75dde75643c5063fc5f5dcb80545b` |
| `libbsd` | `0.12.2-2` | https://snapshot.debian.org/package/libbsd/0.12.2-2/ | `01eb1d0c896096f9038213f5f00376ecfd1c0d1def21b7042f28ae070e4837e3` |
| `libcap-ng` | `0.8.5-4` | https://snapshot.debian.org/package/libcap-ng/0.8.5-4/ | `a5745b7d68a11068ae5beddcc7fbc94cd87dd81cb2d7495e7d48610603be3526` |
| `libcap2` | `1:2.75-10+deb13u1` | https://snapshot.debian.org/package/libcap2/1%3A2.75-10+deb13u1/ | `cb6af220de216655ec55bb1f5abf3fa8f03e82c9956f120b313056e895c02ea6` |
| `libedit` | `3.1-20250104-1` | https://snapshot.debian.org/package/libedit/3.1-20250104-1/ | `1faea2073588dc3310133fb2dca5b9b6d3e759ae8653c2afefa1c802085cf544` |
| `liberror-perl` | `0.17030-1` | https://snapshot.debian.org/package/liberror-perl/0.17030-1/ | `44590c5e4057ee2b2090b7ca661cdbead886528a2b5b5fa7ae708f8b9c1814bf` |
| `libffi` | `3.4.8-2` | https://snapshot.debian.org/package/libffi/3.4.8-2/ | `4424defe3f37c0084f062e03330b2ba3d3f927367c33be455cfacf7f85a78161` |
| `libgc` | `1:8.2.8-1` | https://snapshot.debian.org/package/libgc/1%3A8.2.8-1/ | `e9c90ee694ef4945700054ad2ea23e326d8ac2d15daf79cd97e99977e5d517b7` |
| `libidn2` | `2.3.8-2` | https://snapshot.debian.org/package/libidn2/2.3.8-2/ | `af3327227dbbf12fff281f71b7feb90371d2dbe597f3129e38b93c3faadcea61` |
| `libjsoncpp` | `1.9.6-3` | https://snapshot.debian.org/package/libjsoncpp/1.9.6-3/ | `fd8e28f65bd38ebd0cb1830d160626d9e87020171ad14f39f6bfedb1ccc6c64e` |
| `libmd` | `1.1.0-2` | https://snapshot.debian.org/package/libmd/1.1.0-2/ | `46cc951cd6d71bbfeff4522de66f968fb92601ec4cc622b07f6ac0a2a36ac5f0` |
| `libpfm4` | `4.13.0+git99-gc5587f9-1` | https://snapshot.debian.org/package/libpfm4/4.13.0+git99-gc5587f9-1/ | `b705e7e337f6141963f6a66674977558529fcda8656b38a7e6474dc6dc42c72b` |
| `libpsl` | `0.21.2-1.1` | https://snapshot.debian.org/package/libpsl/0.21.2-1.1/ | `b9b5496ca2bffb827cb0b2d997469908a2b7a7475c20a11c02f9dcd1ed2a0cc9` |
| `libseccomp` | `2.6.0-2` | https://snapshot.debian.org/package/libseccomp/2.6.0-2/ | `d05f94536558d34fa339326c6f958a3357b51efac8234470b5d97b69472db765` |
| `libselinux` | `3.8.1-1` | https://snapshot.debian.org/package/libselinux/3.8.1-1/ | `e430b782a396e266f86c32fa779efadebfd40e6a0d10ddbd786fc47905f723b9` |
| `libsemanage` | `3.8.1-1` | https://snapshot.debian.org/package/libsemanage/3.8.1-1/ | `b22bfc4ab2cd47fac46cc9e45d418bb30eb540c3e5c1052d6c669f53e180e4e5` |
| `libsepol` | `3.8.1-1` | https://snapshot.debian.org/package/libsepol/3.8.1-1/ | `0351ffc8c3f66918c9e4ecae9244ae2af27857d8795e424e384ddda794718c34` |
| `libssh2` | `1.11.1-1+deb13u2` | https://snapshot.debian.org/package/libssh2/1.11.1-1+deb13u2/ | `f584c22bccd948a432cc56f64adb896af2cb26d9b38bcaac13cdc7907e766599` |
| `libtasn1-6` | `4.20.0-2+deb13u1` | https://snapshot.debian.org/package/libtasn1-6/4.20.0-2+deb13u1/ | `3f8b0e7ddd5325278b1164f260e45e785e5907309d76b703c8716d068f9cd7e9` |
| `libtext-charwidth-perl` | `0.04-11` | https://snapshot.debian.org/package/libtext-charwidth-perl/0.04-11/ | `8a4f6e7a44880f8b4dd8f3dc0c97a39c6fef979f99899de4962c9ccfe84a2577` |
| `libtext-wrapi18n-perl` | `0.06-10` | https://snapshot.debian.org/package/libtext-wrapi18n-perl/0.06-10/ | `726c08c23af488c28b70600a5c1632468f1535cb50dcd5255cc153a4f8558ed9` |
| `libunistring` | `1.3-2` | https://snapshot.debian.org/package/libunistring/1.3-2/ | `0c09938cace7fbbf36c73af8bc2243fd2f70d3fe336539e8d4c10d0e61742571` |
| `libuv1` | `1.50.0-2` | https://snapshot.debian.org/package/libuv1/1.50.0-2/ | `5691ae93bdd0c9b147e76290bc8816c805f565b6a52ad23691a31b6092056abc` |
| `libxcrypt` | `1:4.4.38-1` | https://snapshot.debian.org/package/libxcrypt/1%3A4.4.38-1/ | `feba1874a84616791c1c17f9a290c9e97562b2904b3b0200edc82a2db54f3f07` |
| `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | https://snapshot.debian.org/package/libxml2/2.12.7+dfsg+really2.9.14-2.1+deb13u3/ | `04b1da890535b11e3db231f39114ee09e643badceff79441d749d0ca78efaaa5` |
| `libyaml` | `0.2.5-2` | https://snapshot.debian.org/package/libyaml/0.2.5-2/ | `c1c3dab54fe7b355753f46a8c783b74a0a6e1099fb3878f4963a175691351477` |
| `libzstd` | `1.5.7+dfsg-1` | https://snapshot.debian.org/package/libzstd/1.5.7+dfsg-1/ | `8f6ab97fa772d921334e50fa5756a0951e23c718dc913e43a228f28c1a23adf9` |
| `linux` | `6.12.111-1` | https://snapshot.debian.org/package/linux/6.12.111-1/ | `6935287a25ed12865714b53cb936959db5875ee025abdaadea8df6335fe74d55` |
| `llvm-toolchain-19` | `1:19.1.7-3` | https://snapshot.debian.org/package/llvm-toolchain-19/1%3A19.1.7-3/ | `1559a483908ca0c8d4124448a551da5f87ab644771352a5335b1b01d07fe732f` |
| `lz4` | `1.10.0-4` | https://snapshot.debian.org/package/lz4/1.10.0-4/ | `394c635aa75a21cd5896680e48821c05336645072ae866b2717d53f36b9ba851` |
| `mawk` | `1.3.4.20250131-1` | https://snapshot.debian.org/package/mawk/1.3.4.20250131-1/ | `147dd01670e2ebf61f3c78470e0025b87d14e69c7ba9cfafd54da32a355dea84` |
| `media-types` | `13.0.0` | https://snapshot.debian.org/package/media-types/13.0.0/ | `a664c287e8d358da16bae998374c546cf0eaf3e0416f7059a56818eefe018546` |
| `mpclib3` | `1.3.1-1` | https://snapshot.debian.org/package/mpclib3/1.3.1-1/ | `b2252a499fd0f8e92ce2cf7d8e68477ffc9dd06127803a91f0a1115822efec75` |
| `mpfr4` | `4.2.2-1` | https://snapshot.debian.org/package/mpfr4/4.2.2-1/ | `08ee7b45f8a9980570508770a9d48f70d4c1962fd7c98af4a78cbc3747002ecd` |
| `ncurses` | `6.5+20250216-2` | https://snapshot.debian.org/package/ncurses/6.5+20250216-2/ | `00539cc2bc6bb84be1b8a8a5decf606682e14b6f39b76b9aa090e65d2c2d4580` |
| `netbase` | `6.5` | https://snapshot.debian.org/package/netbase/6.5/ | `e8691899f57c06fcc383b0f2214b662137df539227d9d7811dc8223f32ebe4c7` |
| `nettle` | `3.10.1-1` | https://snapshot.debian.org/package/nettle/3.10.1-1/ | `7b440850ce04b341363f3f5e23dfb9f96ebf7d52e0ef7ba2d07120c90ca61b3c` |
| `nghttp2` | `1.64.0-1.1+deb13u1` | https://snapshot.debian.org/package/nghttp2/1.64.0-1.1+deb13u1/ | `11f4603a9f417bc3d195be36cb462bb9df0657f52b72dd9276453a31bc0227c7` |
| `nghttp3` | `1.8.0-1` | https://snapshot.debian.org/package/nghttp3/1.8.0-1/ | `ffc623e78be62361a82f0a2e7b9a19ff0bcdfc371b8bcc1842039499a12adba2` |
| `ngtcp2` | `1.11.0-1+deb13u1` | https://snapshot.debian.org/package/ngtcp2/1.11.0-1+deb13u1/ | `f14f724e9031e0565be0d75b8bb3b693887f5111e1901ed32401eb860e3ac004` |
| `ninja-build` | `1.12.1-1` | https://snapshot.debian.org/package/ninja-build/1.12.1-1/ | `d6b3848557b2af6826102591a4a86a513caabfde79e1e6d34b6bdf51337ac45e` |
| `openldap` | `2.6.10+dfsg-1` | https://snapshot.debian.org/package/openldap/2.6.10+dfsg-1/ | `05cdd431ef995904f094f4464ca78d5d3b2abdbe4eefacd72446ff8443a2ffac` |
| `openssl` | `3.5.7-1~deb13u3` | https://snapshot.debian.org/package/openssl/3.5.7-1~deb13u3/ | `9cdb0d9daf0773ca5c0f3f5ea1fc59b1106a99e005a5c048948b826e8d3b47e1` |
| `p11-kit` | `0.25.5-3` | https://snapshot.debian.org/package/p11-kit/0.25.5-3/ | `65e21a68dd942741bba82f5bf20901f616b64de91a976d92a54a0cb314896544` |
| `pam` | `1.7.0-5` | https://snapshot.debian.org/package/pam/1.7.0-5/ | `5c127aa18c7cb52ec9ee91fa2099453b3a851bcc0088e79045384a2a508b341c` |
| `pcre2` | `10.46-1~deb13u2` | https://snapshot.debian.org/package/pcre2/10.46-1~deb13u2/ | `4eac7bfc4d11259da7d299f90b6c74b359d7cbb3be2f017e039b02524f30d2e6` |
| `perl` | `5.40.1-6+deb13u1` | https://snapshot.debian.org/package/perl/5.40.1-6+deb13u1/ | `92d1cfb32167d77fada7284f1c291de72f93eb896f5cfd58247d020182b403a8` |
| `pkgconf` | `1.8.1-4` | https://snapshot.debian.org/package/pkgconf/1.8.1-4/ | `782a764448d1ecf39f80c7a1747c28fcbde1800b615eee6a46639a17e58b62f9` |
| `procps` | `2:4.0.4-9` | https://snapshot.debian.org/package/procps/2%3A4.0.4-9/ | `0ea43605b8d5d7ac4306af0dcd2d01e237cbaba6603b0cf248dd7cfd4364ac7a` |
| `protobuf` | `3.21.12-11+deb13u1` | https://snapshot.debian.org/package/protobuf/3.21.12-11+deb13u1/ | `8f60b706ef31fa14c88d93314a5a3ae07b98fa0bc3bb4b58739598de6357779a` |
| `pygments` | `2.18.0+dfsg-2` | https://snapshot.debian.org/package/pygments/2.18.0+dfsg-2/ | `8cfe5e4680e92060683bc235e1fe2f391d49be9b9b3ae1c13e2f8c75e0a4b419` |
| `python-attrs` | `25.3.0-1` | https://snapshot.debian.org/package/python-attrs/25.3.0-1/ | `09bd794be15a64c1451c688b0fac86dd3b647496d1e43aa61924d61737348973` |
| `python-jsonschema` | `4.19.2-6` | https://snapshot.debian.org/package/python-jsonschema/4.19.2-6/ | `bf9976fd1bea1ace70248392afc004e5868fde743cde9526c3d50cbde83d6ca0` |
| `python-jsonschema-specifications` | `2023.12.1-2` | https://snapshot.debian.org/package/python-jsonschema-specifications/2023.12.1-2/ | `ba24e3e6781e75e2b7e3ad322d453a2127254a567bc1ea1bf0c5fe9a13aa452f` |
| `python3-defaults` | `3.13.5-1` | https://snapshot.debian.org/package/python3-defaults/3.13.5-1/ | `206e2f527ca126e46f007b3dd668ae9d35a03c7653bee137a03161df33063d2c` |
| `python3.13` | `3.13.5-2+deb13u5` | https://snapshot.debian.org/package/python3.13/3.13.5-2+deb13u5/ | `4be84e20fb902354fa86955e2fbea6e8bdbd158f54833423488308a9b3532662` |
| `pyyaml` | `6.0.2-1` | https://snapshot.debian.org/package/pyyaml/6.0.2-1/ | `6306e75c1b6c41c3d530afb50e25473e1c2b3cd4434510fab0c9132f6924cfa7` |
| `re2` | `20240702-3` | https://snapshot.debian.org/package/re2/20240702-3/ | `2021430e93176817d300d424e363c073ddc4655e45b86d42193c3714b40238e9` |
| `readline` | `8.2-6` | https://snapshot.debian.org/package/readline/8.2-6/ | `6f94c7144d6b6b1ff88aaebd81480e87f8773b7638031782aac12ef93ffd2e71` |
| `referencing` | `0.36.2-1` | https://snapshot.debian.org/package/referencing/0.36.2-1/ | `b457392a4306902bcf355f4d47aff05f3535708c96b982cdd9299ce3369593ed` |
| `rhash` | `1.4.5-1` | https://snapshot.debian.org/package/rhash/1.4.5-1/ | `908ab021cc101fcb5cf385a051a65bfc426d4f8a374928710c567d578b322238` |
| `rpcsvc-proto` | `1.4.3-1` | https://snapshot.debian.org/package/rpcsvc-proto/1.4.3-1/ | `7d8e122bd18b02fe0de6d467a0ecdafff74035b3e1ed0da1c0c792d9c015682f` |
| `rpds-py` | `0.21.0-2` | https://snapshot.debian.org/package/rpds-py/0.21.0-2/ | `1a2c878845c6e93709d99509593954d04d15e278bc1453ae83cce02dcadb827e` |
| `rtmpdump` | `2.4+20151223.gitfa8646d.1-2` | https://snapshot.debian.org/package/rtmpdump/2.4+20151223.gitfa8646d.1-2/ | `a296819cd2ab5880b67ad963ef0867cb10e462f4403e52565aa863eb05bb1370` |
| `rust-sequoia-sqv` | `1.3.0-3` | https://snapshot.debian.org/package/rust-sequoia-sqv/1.3.0-3/ | `98ad852ed30d42d3b0d6ce40d2f56a96fb443cc6fa2caeaa12516fe5bbe544af` |
| `sed` | `4.9-2+deb13u1` | https://snapshot.debian.org/package/sed/4.9-2+deb13u1/ | `9fcc5dffe5e712b4631757c057228ae57919aec1cca1c91a80e76719167f443b` |
| `sensible-utils` | `0.0.25` | https://snapshot.debian.org/package/sensible-utils/0.0.25/ | `7d0deb8fca88c2e095a838b4ba2443c5c07f1501907b331a7ef051178c90a5a8` |
| `shadow` | `1:4.17.4-2` | https://snapshot.debian.org/package/shadow/1%3A4.17.4-2/ | `920de0d3be5303f2c0511d5531c1815abc258b15af8f9c511c8aa6d8e1a91a86` |
| `source-highlight` | `3.1.9-4.3` | https://snapshot.debian.org/package/source-highlight/3.1.9-4.3/ | `8e5ec41c17a5d6c840f7aed961879acc4aad4f3893783370013d0420a3e5bebe` |
| `sqlite3` | `3.46.1-7+deb13u2` | https://snapshot.debian.org/package/sqlite3/3.46.1-7+deb13u2/ | `46e1eec171e11108fc436e45309b635b601029726b6ffd3bf435bb474e511638` |
| `systemd` | `257.13-1~deb13u1` | https://snapshot.debian.org/package/systemd/257.13-1~deb13u1/ | `1b3405d671a82d1e20c9d99f52d4336aafe8543b28d04e91b7f1f586d3a667c7` |
| `sysvinit` | `3.14-4` | https://snapshot.debian.org/package/sysvinit/3.14-4/ | `1cfe65682218077e6f76011f0c5caacc9f2ab214d55893307d4a54c93312ac92` |
| `tar` | `1.35+dfsg-3.1` | https://snapshot.debian.org/package/tar/1.35+dfsg-3.1/ | `5bb58d4966d94c99a9f1b182676089ecc05058d62fdb927f5c07539d9cda4077` |
| `tzdata` | `2026c-0+deb13u1` | https://snapshot.debian.org/package/tzdata/2026c-0+deb13u1/ | `b18d6eddfb23971bacbf569a2641cda837002a813d8e8940d8792ea7ba8e2d4e` |
| `ucf` | `3.0052` | https://snapshot.debian.org/package/ucf/3.0052/ | `9117f54533d23ad74371e91c3038e13b1aa0fabd51a382f47a5af81e9b5ee591` |
| `util-linux` | `2.41.5-0+deb13u1` | https://snapshot.debian.org/package/util-linux/2.41.5-0+deb13u1/ | `43e9b2cbebd10fdc598c4ad10217c8202c28de53af6eafc892c8e9b5cbf3a3a5` |
| `xxhash` | `0.8.3-2` | https://snapshot.debian.org/package/xxhash/0.8.3-2/ | `9d1f7aaace7871fbdb8775d756c6eaca84e6ad5d8e9c6ac465b7e0adc06ff90c` |
| `xz-utils` | `5.8.1-1+deb13u1` | https://snapshot.debian.org/package/xz-utils/5.8.1-1+deb13u1/ | `ddadd9d9f7c4bb80b08f9f17409e2701a29a4cf8fe25e15d19605e5281c1fc1b` |
| `z3` | `4.13.3-1` | https://snapshot.debian.org/package/z3/4.13.3-1/ | `503d4e990e0d6e2012d4ef97e31ff6a7dcd8b0ead582e58be07c84dc6b6d0df3` |
| `zlib` | `1:1.3.dfsg+really1.3.1-1` | https://snapshot.debian.org/package/zlib/1%3A1.3.dfsg+really1.3.1-1/ | `ede2791e29c1d3b422f9208bdd7edf040c20445ea1e7453a72037576e64fa197` |

### 5.1 GPL and LGPL tags of the developer packages

`developer.lock.json` (`notices`) records these `license_tags` from each
package's Debian `copyright` file in `third_party/developer/notices/`. Some tags
apply only to build files.

| Binary package | Binary version | Source package and version | GPL/LGPL tags recorded |
|---|---|---|---|
| `gdb` | `16.3-1` | `gdb` 16.3-1 | GPL-2+; GPL-3+; GPL-3+ and LGPL-2.1+; GPL-3+ with GCC-Runtime-3.1 exception; LGPL-2+; LGPL-2.1+ |
| `clangd-19` | `1:19.1.7-3+b1` | `llvm-toolchain-19` 1:19.1.7-3 | none recorded |
| `libbabeltrace1` | `1.5.11-4+b2` | `babeltrace` 1.5.11-4 | GPL-2; GPL-3+; LGPL-2.1 |
| `libdebuginfod1t64` | `0.192-4` | `elfutils` 0.192-4 | GPL-3+; GPL-3+ with Bison exception; LGPL-2.1+; LGPL-3+ or GPL-2+ |
| `libipt2` | `2.1.2-1` | `intel-processor-trace` 2.1.2-1 | none recorded |
| `libpython3.13` | `3.13.5-2+deb13u5` | `python3.13` 3.13.5-2+deb13u5 | none recorded |
| `libsource-highlight4t64` | `3.1.9-4.3+b1` | `source-highlight` 3.1.9-4.3 | GPL-3+ |
| `libabsl20240722` | `20240722.0-4` | `abseil` 20240722.0-4 | none recorded |
| `libgrpc++1.51t64` | `1.51.1-6` | `grpc` 1.51.1-6 | GPL-2+ |
| `libgrpc29t64` | `1.51.1-6` | `grpc` 1.51.1-6 | GPL-2+ |
| `libprotobuf32t64` | `3.21.12-11+deb13u1` | `protobuf` 3.21.12-11+deb13u1 | GPL-3; GPLWithACException |
| `libdw1t64` | `0.192-4` | `elfutils` 0.192-4 | GPL-3+; GPL-3+ with Bison exception; LGPL-2.1+; LGPL-3+ or GPL-2+ |
| `libelf1t64` | `0.192-4` | `elfutils` 0.192-4 | GPL-3+; GPL-3+ with Bison exception; LGPL-2.1+; LGPL-3+ or GPL-2+ |
| `libglib2.0-0t64` | `2.84.4-3~deb13u5` | `glib2.0` 2.84.4-3~deb13u5 | AFL-2.0 or LGPL-2.1+; GPL-2+; LGPL-2+; LGPL-2.1+; LGPL-2.1+ and Kuchling-PD and Plumb-PD; LGPL-3+ |
| `libjson-c5` | `0.18+ds-1` | `json-c` 0.18+ds-1 | none recorded |
| `libdebuginfod-common` | `0.192-4` | `elfutils` 0.192-4 | GPL-3+; GPL-3+ with Bison exception; LGPL-2.1+; LGPL-3+ or GPL-2+ |
| `libsource-highlight-common` | `3.1.9-4.3` | `source-highlight` 3.1.9-4.3 | GPL-3+ |
| `libcares2` | `1.34.5-1+deb13u1` | `c-ares` 1.34.5-1+deb13u1 | GPL-2+ with Autoconf-data exception; GPL-2+ with Libtool exception; GPL-3+ with Autoconf-2.0~Archive exception; GPL-3+ with Autoconf-data exception; LGPL-2.1+ |
| `libprotoc32t64` | `3.21.12-11+deb13u1` | `protobuf` 3.21.12-11+deb13u1 | GPL-3; GPLWithACException |
| `libre2-11` | `20240702-3+b1` | `re2` 20240702-3 | none recorded |
| `ucf` | `3.0052` | `ucf` 3.0052 | GPL-2 |
| `libtext-wrapi18n-perl` | `0.06-10` | `libtext-wrapi18n-perl` 0.06-10 | Artistic or GPL-1+; GPL-1+ |
| `sensible-utils` | `0.0.25` | `sensible-utils` 0.0.25 | GPL-2+ |
| `libtext-charwidth-perl` | `0.04-11+b4` | `libtext-charwidth-perl` 0.04-11 | Artistic or GPL-1+; GPL-1+ |

### 5.2 GPL and LGPL libraries in the bench Python wheels

The framework developer image holds the wheels numpy 2.3.3, pyperf 2.9.0 and
psutil 7.1.0 under `/opt/bench-python`. The same wheels are in this repository
(`third_party/developer/wheels/`). pyperf (MIT) and psutil (BSD-3-Clause) hold
no GPL or LGPL code. numpy is BSD-3-Clause, and it bundles the two libraries in
this table. The license and the upstream location come from the numpy notice
`third_party/developer/notices/numpy/LICENSE.txt`. The sha256 values come from
`third_party/developer/payload/manifest.json`, and they equal the members of
the pinned wheel.

| Library | File in the wheel | sha256 | License | Exact source | Upstream location (help only) |
|---|---|---|---|---|---|
| GCC runtime library `libgfortran` | `numpy.libs/libgfortran-040039e1-0352e75f.so.5.0.0` | `c6090048eccc763522c12ef016f81da6b627cb3a044f55cf0479a839c41c0980` | GPL-3.0-or-later WITH GCC-exception-3.1 | not recorded (highest symbol version tag: `GFORTRAN_8`) | https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libgfortran |
| GCC Quad-Precision Math Library `libquadmath` | `numpy.libs/libquadmath-96973f99-934c22de.so.0.0.0` | `6ed5137f412781ad7863439fb543613f620b43c32b63292a0029246162f5bbc6` | LGPL-2.1-or-later | not recorded | https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libquadmath |

## 6. GLib foundation in the SDK image

The SDK image holds a GLib build under `/opt/foundation` (shared and static
libraries). The project built it from inputs that are all in this repository,
so the complete corresponding source is next to the binary at the same commit.

| Component | Version | License | Source in this repository |
|---|---|---|---|
| GLib core | 2.90.0 | LGPL-2.1-or-later (some files under other licenses, see `third_party/foundation-notices/glib-*.txt`) | `container/foundation-inputs/glib-2.90.0.tar.xz` (sha256 `17d15cac2af80a33271127408e0abc2748eb297c595c2a26409e81e14e7d1b8f`), the test adaptation `container/glib-test-compat.py` with its record `container/glib-test-compat.json` and `third_party/patches/glib-selected-tests-callback-abi.patch`, and the build recipe `container/build-foundation.py` |

PCRE2 10.46, which the foundation also builds, is under BSD-3-Clause WITH
PCRE2-exception. It is not GPL or LGPL. Its source is in this repository
(`container/foundation-inputs/pcre2-10.46.tar.bz2`).

## 7. Scope

- This file covers the images of release `images-sdk-developer-v3` (the SDK
  image `sha256:fabbb83309d3767840466b4ccb82a1da9940b76d76ae7d16eedf04d6a540d179`
  and the framework developer image
  `sha256:323daee40b10313e19988592dcb32bb7f0aa6a7e72301ed85a1a9f61aed82e30`),
  the images of release `images-sdk-developer-v2`, and the binaries in this
  repository (MarketData-App/safe-c-environment) at the commit that contains
  this file. Release `images-sdk-developer-v3` is the published release.
  Release `images-sdk-developer-v2` is an earlier release. A later release must
  update the listing.
- A project that `./tools/safety instantiate` creates receives a copy of this
  file and of the Debian binaries in `third_party/` and
  `container/foundation-inputs/`. It also receives the three Python wheels in
  `third_party/developer/wheels/` (numpy, pyperf and psutil). The numpy wheel
  holds the GPL/LGPL runtime libraries `libgfortran` and `libquadmath`
  (section 5.2). If that project publishes its repository or
  its own release assets, it distributes these binaries itself. It then needs
  its own source arrangement. This file is MarketData-App's statement for
  MarketData-App's distribution only. GPL-2.0 section 3(c) and GPL-3.0 section
  6(c) let a recipient pass on a written offer only for noncommercial or
  occasional distribution.
