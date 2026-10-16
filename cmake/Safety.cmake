# Target-scoped C17 policy shared by qualification and future application targets.
function(safety_target target)
  set_target_properties(${target} PROPERTIES C_STANDARD 17 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
  # Project targets (cmake/Project.cmake) see only their own include/ directory: the
  # framework qualification and fuzz directories would let an angle include reach
  # files the project policy does not scan.
  if(NOT _SAFETY_PROJECT_TARGETS)
    target_include_directories(${target} PRIVATE ${PROJECT_SOURCE_DIR}/safety/qualification ${PROJECT_SOURCE_DIR}/fuzz)
  endif()
  if(NOT SAFETY_PROFILE STREQUAL "ordinary")
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror
      -Wconversion -Wsign-conversion -Wshadow -Wformat=2 -Wformat-security
      -Wundef -Wstrict-prototypes -Wmissing-prototypes -Wvla -Wcast-qual
      -Wwrite-strings -Werror=implicit-function-declaration -Werror=incompatible-pointer-types)
  endif()
  if(_SAFETY_PROJECT_TARGETS)
    # Amendment F item 3: project code gets IEEE binary64 without contraction in every build.
    target_compile_options(${target} PRIVATE -ffp-contract=off)
  endif()
  if(SAFETY_PROFILE MATCHES "^(asan|ubsan|integer|msan|tsan|fuzz)$")
    target_compile_options(${target} PRIVATE -O1 -g -fno-omit-frame-pointer -fno-optimize-sibling-calls)
    if(SAFETY_PROFILE STREQUAL "asan")
      set(flags -fsanitize=address,undefined -fsanitize-address-use-after-scope -fsanitize-address-use-after-return=always -fno-sanitize-recover=all)
    elseif(SAFETY_PROFILE STREQUAL "ubsan")
      set(flags -fsanitize=undefined -fno-sanitize-recover=all)
    elseif(SAFETY_PROFILE STREQUAL "integer")
      set(flags -fsanitize=undefined,unsigned-integer-overflow,implicit-integer-conversion -fno-sanitize-recover=all)
    elseif(SAFETY_PROFILE STREQUAL "msan")
      set(flags -fsanitize=memory -fsanitize-memory-track-origins=2 -fPIE)
      target_link_options(${target} PRIVATE -pie)
    elseif(SAFETY_PROFILE STREQUAL "tsan")
      set(flags -fsanitize=thread -fPIE)
      target_link_options(${target} PRIVATE -pie)
    else()
      set(flags -fsanitize=address,undefined,fuzzer-no-link -fno-sanitize-recover=all)
    endif()
    target_compile_options(${target} PRIVATE ${flags})
    target_link_options(${target} PRIVATE ${flags})
  elseif(SAFETY_PROFILE STREQUAL "coverage")
    # P2-COV-ATOMIC-01: atomic counter updates, so worker threads lose no count (exact, repeatable counts)
    target_compile_options(${target} PRIVATE -O0 -g -fprofile-instr-generate -fcoverage-mapping -fprofile-update=atomic)
    target_link_options(${target} PRIVATE -fprofile-instr-generate -fcoverage-mapping)
  elseif(SAFETY_PROFILE STREQUAL "hardened")
    target_compile_options(${target} PRIVATE -O2 -g -fstack-protector-strong -fstack-clash-protection -D_FORTIFY_SOURCE=3 -fPIE)
    target_link_options(${target} PRIVATE -pie -Wl,-z,relro,-z,now,-z,noexecstack)
  elseif(SAFETY_PROFILE STREQUAL "gcc-analyzer")
    target_compile_options(${target} PRIVATE -O0 -fanalyzer -Wanalyzer-too-complex -Wanalyzer-symbol-too-complex)
  else()
    target_compile_options(${target} PRIVATE -g)
  endif()
endfunction()
# Amendment F item 3: an object that goes into a project shared library is PIC in every build.
# The hardened, msan and tsan settings of safety_target add -fPIE after CMake's -fPIC; the
# appended -fPIC comes last and wins (tools/project_check.py library_pic_problems checks it).
function(safety_position_independent target)
  set_property(TARGET ${target} PROPERTY POSITION_INDEPENDENT_CODE ON)
  target_compile_options(${target} PRIVATE -fPIC)
endfunction()
# Amendment F item 3: the framework settings of a project shared library (cmake/Project.cmake).
# The version script `map` exports only the declared names; every other symbol is local.
# C_VISIBILITY_PRESET hidden applies to the target's own empty unit only: the module objects
# keep default visibility, because a hidden symbol cannot be exported by a version script.
# -z defs only where no sanitizer or profile runtime stays undefined in a shared object.
# -z text refuses a text relocation (no writable code); tools/project_check.py checks the
# linked result (RELRO, BIND_NOW, GNU_STACK, TEXTREL) in the hardened gate.
function(safety_shared_library target output_name map)
  safety_target(${target})
  safety_position_independent(${target})
  set_target_properties(${target} PROPERTIES C_VISIBILITY_PRESET hidden
    OUTPUT_NAME "${output_name}" LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}" LINK_DEPENDS "${map}")
  target_link_options(${target} PRIVATE "-Wl,--version-script=${map}" -Wl,-z,text)
  if(SAFETY_PROFILE MATCHES "^(ordinary|strict|hardened)$")
    target_link_options(${target} PRIVATE -Wl,-z,defs)
  endif()
endfunction()
function(safety_add_program target)
  add_executable(${target} ${ARGN})
  safety_target(${target})
  target_link_libraries(${target} PRIVATE pthread)
endfunction()
# Amendment F item 3: a project test or program that can load the locked GLib finds the
# exact profile library of this build (SC_DEPENDENCY_PREFIX, cmake/FoundationLibraries.cmake).
function(safety_foundation_runtime_path target)
  if(NOT SC_DEPENDENCY_PREFIX MATCHES "^/opt/foundation/[A-Za-z0-9-]+$")
    message(FATAL_ERROR "locked foundation prefix is not selected")
  endif()
  set_target_properties(${target} PROPERTIES BUILD_RPATH "${SC_DEPENDENCY_PREFIX}/lib")
endfunction()
