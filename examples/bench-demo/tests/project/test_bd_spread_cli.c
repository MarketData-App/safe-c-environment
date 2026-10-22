#include "bd_spread.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Tests of the program logic of bd-spread, derived from specs/project/bd_spread.md: argc 0 and 2
 * and argv NULL give the usage result and nothing on out; argc 1 writes 196 lines (4 header lines
 * with one result text and 192 span lines); an out stream that refuses writes gives 4. REQUIRE
 * stays active under NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int: results are combined without branches, so GCC
 * -fanalyzer explores one path per loop. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { LINE = 160, RESULT = 23 };

/* argc 0 and 2 and argv NULL: return 2, nothing on out, the usage line on err each time. */
static void program_usage(void) {
    char prog[] = "bd-spread";
    char extra[] = "1";
    char *two[] = {prog, extra, NULL};
    char *none[] = {NULL};
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(out != NULL && err != NULL);
    unsigned int ok = AS_BIT(bd_spread_cli_main(2, two, out, err) == 2);
    ok &= AS_BIT(bd_spread_cli_main(0, none, out, err) == 2);
    ok &= AS_BIT(bd_spread_cli_main(1, NULL, out, err) == 2);
    const long usage = (long)sizeof "usage: bd-spread\n" - 1L;
    ok &= AS_BIT(ftell(out) == 0L) & AS_BIT(ftell(err) == 3L * usage);
    REQUIRE(ok);
    REQUIRE(fclose(out) == 0 && fclose(err) == 0);
}

/* argc 1: the serial line first, then 3 traced headers with the same result text and 192 spans. */
static void program_output(void) {
    char prog[] = "bd-spread";
    char *argv[] = {prog, NULL};
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(out != NULL && err != NULL);
    REQUIRE(bd_spread_cli_main(1, argv, out, err) == 0);
    REQUIRE(fseek(out, 0L, SEEK_SET) == 0);
    char first[LINE] = {0};
    REQUIRE(fgets(first, (int)sizeof first, out) != NULL);
    const char *result = strstr(first, "result=");
    REQUIRE(strncmp(first, "# workers=0 result=", 19U) == 0 && result != NULL);
    REQUIRE(strlen(result) == (size_t)RESULT + 1U);
    char line[LINE] = {0};
    unsigned int headers = 0U;
    unsigned int lines = 1U;
    unsigned int same = 1U;
    while (fgets(line, (int)sizeof line, out) != NULL) {
        const char *at = strstr(line, "result=");
        const unsigned int header = AS_BIT(strncmp(line, "# workers=", 10U) == 0);
        const char *probe = at != NULL ? at : result;
        lines += 1U;
        headers += header & AS_BIT(at != NULL);
        same &= AS_BIT(strncmp(probe, result, (size_t)RESULT) == 0);
    }
    REQUIRE(headers == 3U && lines == 196U && same == 1U);
    REQUIRE(ftell(err) == 0L);
    REQUIRE(fclose(out) == 0 && fclose(err) == 0);
}

/* A stream opened for reading rejects every write: return 4. */
static void program_refused_write(void) {
    char prog[] = "bd-spread";
    char *argv[] = {prog, NULL};
    FILE *read_only = fopen("/dev/null", "r");
    if (read_only == NULL) {
        (void)fputs("fopen /dev/null failed\n", stderr);
        exit(1);
    }
    const int rc = bd_spread_cli_main(1, argv, read_only, stderr);
    REQUIRE(fclose(read_only) == 0);
    REQUIRE(rc == 4);
}

int main(void) {
    program_usage();
    program_output();
    program_refused_write();
    puts("PASS bd_spread cli");
    return 0;
}
