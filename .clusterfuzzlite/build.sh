#!/bin/bash
set -euo pipefail
: "${CC:?}" "${CXX:?}" "${CFLAGS:?}" "${CXXFLAGS:?}" "${LIB_FUZZING_ENGINE:?}" "${OUT:?}" "${WORK:?}"
# Environment flags belong to the caller's pinned toolchain. Bash arrays split
# compiler flag words; no eval, command substitution, or template execution.
read -r -a cflags <<< "$CFLAGS"
read -r -a cxxflags <<< "$CXXFLAGS"
read -r -a engine <<< "$LIB_FUZZING_ENGINE"
variant=good
if [[ "${SAFETY_QUALIFICATION_VARIANT:-}" == "bad" ]]; then
  variant=bad
elif [[ -n "${SAFETY_QUALIFICATION_VARIANT:-}" && "${SAFETY_QUALIFICATION_VARIANT}" != "good" ]]; then
  exit 2
fi
parser=$(python3 -c 'import json,sys;print(json.load(open("/src/fuzz/targets.json"))["parser_"+sys.argv[1]])' "$variant")
harness=$(python3 -c 'import json;print(json.load(open("/src/fuzz/targets.json"))["harness"])')
mkdir -p "$OUT" "$WORK"
"$CC" "${cflags[@]}" -std=c17 -I/src/fuzz -c "/src/$parser" -o "$WORK/parser.o"
"$CC" "${cflags[@]}" -std=c17 -I/src/fuzz -c "/src/$harness" -o "$WORK/harness.o"
"$CXX" "${cxxflags[@]}" "$WORK/parser.o" "$WORK/harness.o" "${engine[@]}" -o "$OUT/parser_fuzzer"
