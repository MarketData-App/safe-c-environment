/* Modified file. Origin: LLVM compiler-rt/test/asan/TestCases/global-overflow.cpp
 * at llvm-project revision cd708029e0b2869e80abe31ddb175f7c35361f90.
 * License: Apache-2.0 WITH LLVM-exception; see
 * third_party/originals/llvm/llvm-project/compiler-rt/LICENSE.TXT.
 * Changed by MarketData-App (C17 qualification fixture); the full change is
 * third_party/patches/C04.patch. */
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static char global_data[10];
#include "support.h"
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    size_t i = (size_t)argc * 10;
    fixture_write(global_data, i);
    return global_data[0];
}
