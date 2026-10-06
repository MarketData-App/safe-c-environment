#!/bin/bash
# Builds one project fuzz target with the ClusterFuzzLite build contract:
# CC/CXX/CFLAGS/LIB_FUZZING_ENGINE/OUT/WORK come from the protected caller.
# Usage: project-fuzz-build.sh PROJECT_DIR NAME HARNESS SOURCE...
# HARNESS and SOURCE are paths relative to PROJECT_DIR (itself relative to /src).
set -euo pipefail
: "${CC:?}" "${CFLAGS:?}" "${LIB_FUZZING_ENGINE:?}" "${OUT:?}" "${WORK:?}"
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
root=/src
if [[ "$project_dir" != "." ]]; then root="/src/$project_dir"; fi
# Bash arrays split compiler flag words; no eval or command substitution.
read -r -a cflags <<< "$CFLAGS"
read -r -a engine <<< "$LIB_FUZZING_ENGINE"
mkdir -p "$OUT" "$WORK"
objects=()
index=0
for source in "$@"; do
  plain "$source"
  "$CC" "${cflags[@]}" -std=c17 -I"$root/include" -c "$root/$source" -o "$WORK/module-$index.o"
  objects+=("$WORK/module-$index.o")
  index=$((index + 1))
done
plain "$harness"
"$CC" "${cflags[@]}" -std=c17 -I"$root/include" -c "$root/$harness" -o "$WORK/harness.o"
"${CXX:-$CC}" "${cflags[@]}" "${objects[@]}" "$WORK/harness.o" "${engine[@]}" -o "$OUT/${name}_fuzzer"
