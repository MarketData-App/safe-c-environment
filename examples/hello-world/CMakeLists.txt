cmake_minimum_required(VERSION 3.25)
project(hello_world LANGUAGES C)
include("${SAFE_C_ROOT}/cmake/Project.cmake")
safety_project("${CMAKE_CURRENT_SOURCE_DIR}")
