# Adapted from friendlyanon/cmake-init's Unlicense template. See upstream.lock.json.
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
  message(FATAL_ERROR "In-source builds are not supported; use a separate build directory.")
endif()
