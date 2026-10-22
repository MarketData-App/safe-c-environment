#include "pl_kernel_cli.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Program logic of pl-kernel (specs/project/batch.md "pl-kernel command line"): the argument
 * parser and the exit codes. The option table and the value parsers are in src/pl_kernel_opts.c,
 * the runs in src/pl_kernel_run.c, src/pl_kernel_loop.c and src/pl_kernel_probe.c, the
 * self-check and the parameters in src/pl_kernel_self.c. */

static const char pl_usage[] =
    "usage: pl-kernel --self-check | --print-params | --case option-chain-greeks|record-scan|probe "
    "--input PATH --records N [options] (specs/project/batch.md)\n";

/* Collects the options of argv[1 .. argc-1] into values; returns the bit set of the options
 * seen, or 0 for an unknown, repeated or NULL argument or a missing value. */
static unsigned pl_collect(int argc, char **argv, const char **values) {
    unsigned seen = 0u;
    int i = 1;
    while (i < argc) {
        const char *arg = *(argv + i);
        const size_t k = arg == NULL ? PL_OPT_COUNT : pl_opt_find(arg);
        if (k == PL_OPT_COUNT || (seen & pl_opt_bit(k)) != 0u) {
            return 0u;
        }
        seen |= pl_opt_bit(k);
        if (pl_opt_takes_value(k)) {
            if (i + 1 >= argc || *(argv + i + 1) == NULL) {
                return 0u;
            }
            *(values + k) = *(argv + i + 1);
            i++;
        }
        i++;
    }
    return seen;
}

static void pl_args_init(struct pl_kernel_args *a) {
    a->kase = PL_CASE_OPTION;
    a->input = NULL;
    a->output = NULL;
    a->canonical = NULL;
    a->trace = NULL;
    a->records = 0u;
    a->loops = 1u;
    a->threads = 0u;
    a->echo = 0;
    a->handshake = 0;
    a->models = PL_MASK_ALL3;
    a->dte_min = 0;
    a->dte_max = 0;
    a->lo = 0.0;
    a->hi = 0.0;
}

/* The run options: 0 and *a, or -1. */
static int pl_parse_run(int argc, char **argv, struct pl_kernel_args *a) {
    const char *values[PL_OPT_COUNT] = {NULL};
    const unsigned seen = pl_collect(argc, argv, values);
    const unsigned named = pl_opt_bit(PL_OPT_CASE) | pl_opt_bit(PL_OPT_INPUT);
    const unsigned required = named | pl_opt_bit(PL_OPT_RECORDS);
    if ((seen & required) != required) {
        return -1;
    }
    a->kase = pl_case_of(*(values + PL_OPT_CASE));
    if (a->kase < 0) {
        return -1;
    }
    if ((seen & ~pl_opt_allowed(a->kase)) != 0u || pl_parse_counts(values, a) != 0) {
        return -1;
    }
    const unsigned echo_canonical = pl_opt_bit(PL_OPT_ECHO) | pl_opt_bit(PL_OPT_CANONICAL);
    if ((seen & echo_canonical) == echo_canonical) {
        return -1; /* fails closed: echo results have no canonical form (status 255) */
    }
    if (a->kase == PL_CASE_SCAN && pl_parse_window(values, a) != 0) {
        return -1;
    }
    a->input = *(values + PL_OPT_INPUT);
    a->output = *(values + PL_OPT_OUTPUT);
    a->canonical = *(values + PL_OPT_CANONICAL);
    a->trace = *(values + PL_OPT_TRACE);
    a->echo = (seen & pl_opt_bit(PL_OPT_ECHO)) != 0u;
    a->handshake = (seen & pl_opt_bit(PL_OPT_HANDSHAKE)) != 0u;
    return 0;
}

int pl_kernel_parse(int argc, char **argv, struct pl_kernel_args *a) {
    if (a == NULL || argv == NULL || argc < 2) {
        return -1;
    }
    pl_args_init(a);
    const char *first = *(argv + 1);
    if (argc == 2 && first != NULL && strcmp(first, "--self-check") == 0) {
        return PL_MODE_SELF_CHECK;
    }
    if (argc == 2 && first != NULL && strcmp(first, "--print-params") == 0) {
        return PL_MODE_PRINT_PARAMS;
    }
    return pl_parse_run(argc, argv, a) == 0 ? PL_MODE_RUN : -1;
}

/* The exit code and the failure reason text of an enum pl_kernel_reason. */
static int pl_exit_of(int reason) {
    if (reason == PL_REASON_OK) {
        return 0;
    }
    if (reason == PL_REASON_USAGE || reason == PL_REASON_INPUT) {
        return 2;
    }
    return reason == PL_REASON_KERNEL ? 3 : 4;
}

static const char *pl_reason_text(int reason) {
    if (reason == PL_REASON_USAGE) {
        return "usage";
    }
    if (reason == PL_REASON_INPUT) {
        return "input";
    }
    return reason == PL_REASON_KERNEL ? "kernel" : "io";
}

int pl_kernel_main(int argc, char **argv, FILE *out, FILE *err) {
    struct pl_kernel_args a;
    const int mode = pl_kernel_parse(argc, argv, &a);
    int reason = PL_REASON_USAGE;
    if (mode < 0) {
        (void)fputs(pl_usage, err);
    } else if (mode == PL_MODE_SELF_CHECK) {
        reason = pl_kernel_self_check(out);
    } else if (mode == PL_MODE_PRINT_PARAMS) {
        reason = pl_kernel_print_params(out);
    } else {
        reason = pl_kernel_run(&a, out);
    }
    if (reason != PL_REASON_OK) {
        (void)fprintf(out, "PLK1 status=FAIL reason=%s\n", pl_reason_text(reason));
        (void)fflush(out);
    }
    return pl_exit_of(reason);
}
