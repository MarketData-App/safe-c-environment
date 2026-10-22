# Source code availability and written offer (option-pricing-benchmark example)

Date: 2026-10-18. Distributor: MarketData-App, the GitHub organization that publishes the repository
[MarketData-App/safe-c-environment](https://github.com/MarketData-App/safe-c-environment). This file covers the
example project `examples/option-pricing-benchmark/` of that repository. The file
[SOURCE-OFFER.md](../../SOURCE-OFFER.md) at the repository root covers the framework.

This file is not legal advice.

## 1. What this file covers

The example keeps the SciPy 1.16.2 wheel in git as two parts below `benchmarks/project/third_party/wheels/`:
`scipy-1.16.2-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.part-00` and `.part-01`. Joined, they are
35,681,881 bytes with sha256 `c2275ff105e508942f99d4e3bc56b6ef5e4b3c0af970386ca56b777608ce95b7` (lock row `scipy` of
`benchmarks/project/third_party/lock.json`). SciPy is under BSD-3-Clause. The wheel bundles these four libraries under
the GPL or the LGPL:

| Library | File in the wheel | sha256 | License | Exact source | Upstream location (help only) |
|---|---|---|---|---|---|
| GCC runtime library `libgfortran` | `scipy.libs/libgfortran-040039e1-0352e75f.so.5.0.0` | `c6090048eccc763522c12ef016f81da6b627cb3a044f55cf0479a839c41c0980` | GPL-3.0-or-later WITH GCC-exception-3.1 | not recorded (highest symbol version tag: `GFORTRAN_8`); the same bytes as the numpy member in section 5.2 of the root SOURCE-OFFER.md | https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libgfortran |
| GCC runtime library `libgfortran` | `scipy.libs/libgfortran-040039e1.so.5.0.0` | `14afb3129b1a8b50bc40a3b0820c7f1152ea9bc10121aab152943f7057472886` | GPL-3.0-or-later WITH GCC-exception-3.1 | not recorded (highest symbol version tag: `GFORTRAN_8`) | https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libgfortran |
| GCC Quad-Precision Math Library `libquadmath` | `scipy.libs/libquadmath-96973f99-934c22de.so.0.0.0` | `6ed5137f412781ad7863439fb543613f620b43c32b63292a0029246162f5bbc6` | LGPL-2.1-or-later | not recorded; the same bytes as the numpy member in section 5.2 of the root SOURCE-OFFER.md | https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libquadmath |
| GCC Quad-Precision Math Library `libquadmath` | `scipy.libs/libquadmath-96973f99.so.0.0.0` | `934c22ded0e7d169c4d4678876c96051adf3d94545da962f60b41659b075da3b` | LGPL-2.1-or-later | not recorded | https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libquadmath |

The other third-party files of the example hold no GPL or LGPL binary: the QuantLib 1.43 wheel, the mpmath 1.3.0
wheel, the QuantLib 1.43 source release and the retained Boost 1.90.0 files. The QuantLib source release contains
build scripts under the GPL with Autoconf or Libtool exceptions. They are source, so the archive is its own source.

## 2. Which rule applies

The repository does not record the GCC release or the build of these four binaries, so it cannot give exact
GPL-3.0 section 6(d) directions. The basis that MarketData-App uses is the written offer in section 3. The upstream
GCC locations in section 1 are an extra help. The root SOURCE-OFFER.md (section 2) uses the same basis for the same
libraries in the numpy wheel; the owner confirmed it on 2026-10-15. If counsel later does not accept it,
MarketData-App records the exact source and gives directions to it, or publishes it next to the binaries.

License texts: `benchmarks/project/third_party/notices/scipy/LICENSE.txt` holds the GPL-3.0 text and the GCC Runtime
Library Exception 3.1. The LGPL-2.1 text is in `benchmarks/project/third_party/notices/scipy/LGPL-2.1.txt`.

Each component stays under its own license. This file does not change any license.

## 3. The written offer

MarketData-App offers to give **any third party** a complete machine-readable copy of the **complete corresponding
source code** of each library in section 1.

- **Duration.** At least **three years** after the last date on which MarketData-App distributes the binary in this
  repository.
- **Who can accept it.** Any person or organization. You do not have to show that you received a binary.
- **Charge.** A download link costs nothing. A physical medium costs no more than the cost of physically performing
  the distribution: the medium and the postage.
- **Medium.** A medium customarily used for software interchange: normally a download, or on request a physical
  storage device.

## 4. How to ask

1. Open an issue in the public repository
   [MarketData-App/safe-c-environment](https://github.com/MarketData-App/safe-c-environment/issues).
2. Give the issue the title `Source request`.
3. Name each library by its file and sha256 from section 1, or write `all (option-pricing-benchmark)`.
4. Say whether you want a download link or a physical medium.

Do not put personal data in the public issue. If a physical medium is necessary, the project tells you in the issue
how to send a postal address privately.

## 5. Scope

This file covers the binaries in `examples/option-pricing-benchmark/` at the commit that contains this file. The
project bench image that the framework builds from these wheels is not published. A publication of that image, or of
the wheels as a release asset, must update this file.
