#!/bin/bash
# Builds one project fuzz target with the ClusterFuzzLite build contract:
# CC/CXX/CFLAGS/LIB_FUZZING_ENGINE/OUT/WORK come from the protected caller.
# Usage: project-fuzz-build.sh PROJECT_DIR NAME HARNESS SOURCE... [--glib PREFIX --framework FRAMEWORK_SOURCE...]
# HARNESS and SOURCE are paths relative to PROJECT_DIR (itself relative to /src).
# Amendment F item 3: with --glib (exactly /opt/foundation/fuzz) the build adds the locked
# fuzz-profile GLib and compiles each FRAMEWORK_SOURCE (relative to /src) with the same
# flags; without it, only libm is added. The selection is an argument, not an environment
# variable: the protected launcher admits only the policy's environment names.
# Library mode (Amendment F item 3):
#   project-fuzz-build.sh --library PROJECT_DIR NAME EXPORTS SOURCE... [--glib PREFIX --framework FRAMEWORK_SOURCE...]
# compiles every source with the same flags plus -fPIC and links $OUT/libNAME.so with a version
# script that exports only EXPORTS (comma-separated C names; every other symbol local) and
# -z text (no text relocation). No -z defs: the sanitizer and coverage runtime symbols stay
# undefined in a shared object.
set -euo pipefail
: "${CC:?}" "${CFLAGS:?}" "${LIB_FUZZING_ENGINE:?}" "${OUT:?}" "${WORK:?}"
mode=target
if [[ $# -ge 1 && "$1" == "--library" ]]; then
  mode=library
  shift
fi
if [[ $# -lt 3 ]]; then
  echo "usage: project-fuzz-build.sh PROJECT_DIR NAME HARNESS SOURCE..." >&2
  exit 2
fi
project_dir=$1
name=$2
harness=$3
shift 3
plain() {
  case "/$1/" in
    *//*|*/../*|*/./*) echo "project-fuzz-build: path is not a plain relative path: $1" >&2; exit 2 ;;
  esac
}
if [[ "$project_dir" != "." ]]; then plain "$project_dir"; fi
if [[ ! "$name" =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
  echo "project-fuzz-build: invalid target name" >&2
  exit 2
fi
pic=()
exports=()
if [[ "$mode" == "library" ]]; then
  if [[ ! "$name" =~ ^[a-z][a-z0-9_]{0,30}$ || ! "$harness" =~ ^[a-z][a-z0-9_]{0,62}(,[a-z][a-z0-9_]{0,62}){0,15}$ ]]; then
    echo "project-fuzz-build: invalid library name or export list" >&2
    exit 2
  fi
  IFS=, read -r -a exports <<< "$harness"
  pic=(-fPIC)
fi
root=/src
if [[ "$project_dir" != "." ]]; then root="/src/$project_dir"; fi
# Bash arrays split compiler flag words; no eval or command substitution.
read -r -a cflags <<< "$CFLAGS"
read -r -a engine <<< "$LIB_FUZZING_ENGINE"
sources=()
framework=()
glib_prefix=""
state=sources
for argument in "$@"; do
  case "$state:$argument" in
    sources:--glib)
      state=glib ;;
    glib:*)
      if [[ "$argument" != "/opt/foundation/fuzz" ]]; then
        echo "project-fuzz-build: --glib must be /opt/foundation/fuzz" >&2
        exit 2
      fi
      glib_prefix=$argument
      state=after-glib ;;
    after-glib:--framework)
      state=framework ;;
    sources:--*|after-glib:*|framework:--*)
      echo "project-fuzz-build: unexpected argument order" >&2
      exit 2 ;;
    framework:*)
      framework+=("$argument") ;;
    *)
      sources+=("$argument") ;;
  esac
done
if [[ "$state" == "glib" || "$state" == "after-glib" || ( "$state" == "framework" && ${#framework[@]} -eq 0 ) ]]; then
  echo "project-fuzz-build: --glib needs --framework and at least one framework source" >&2
  exit 2
fi
if [[ "$mode" == "library" && ${#sources[@]} -eq 0 ]]; then
  echo "project-fuzz-build: a library needs at least one source" >&2
  exit 2
fi
glib=()
libraries=(-lm)
if [[ -n "$glib_prefix" ]]; then
  glib=(-isystem "$glib_prefix/include/glib-2.0" -isystem "$glib_prefix/lib/glib-2.0/include"
        -DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_70 -DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_70
        -I/src/foundation/include -I/src/foundation/parallel)
  libraries=(-L"$glib_prefix/lib" -lglib-2.0 -Wl,-rpath,"$glib_prefix/lib" -lm)
fi
mkdir -p "$OUT" "$WORK"
objects=()
index=0
for source in "${sources[@]}"; do
  plain "$source"
  "$CC" "${cflags[@]}" "${pic[@]}" -std=c17 -I"$root/include" "${glib[@]}" -c "$root/$source" -o "$WORK/module-$index.o"
  objects+=("$WORK/module-$index.o")
  index=$((index + 1))
done
index=0
for source in "${framework[@]}"; do
  plain "$source"
  "$CC" "${cflags[@]}" "${pic[@]}" -std=c17 "${glib[@]}" -c "/src/$source" -o "$WORK/framework-$index.o"
  objects+=("$WORK/framework-$index.o")
  index=$((index + 1))
done
if [[ "$mode" == "library" ]]; then
  map="$WORK/$name.map"
  {
    printf '{ global:'
    printf ' %s;' "${exports[@]}"
    printf ' local: *; };\n'
  } > "$map"
  "$CC" "${cflags[@]}" -shared -fPIC "${objects[@]}" -Wl,--version-script="$map" -Wl,-z,text "${libraries[@]}" -o "$OUT/lib$name.so"
  exit 0
fi
plain "$harness"
"$CC" "${cflags[@]}" -std=c17 -I"$root/include" "${glib[@]}" -c "$root/$harness" -o "$WORK/harness.o"
"${CXX:-$CC}" "${cflags[@]}" "${objects[@]}" "$WORK/harness.o" "${engine[@]}" "${libraries[@]}" -o "$OUT/${name}_fuzzer"
