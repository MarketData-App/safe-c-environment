#pragma once
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/* Program logic of pl-kernel (specs/project/batch.md "pl-kernel command line"). argv holds argc
 * pointers; any of them may be NULL. Returns 0 on success, 2 on a usage or input error, 3 on a
 * kernel failure and 4 on an I/O failure. Uses static buffers: one call at a time. */
int pl_kernel_main(int argc, char **argv, FILE *out, FILE *err);

/* The parts of pl-kernel in src/pl_kernel_cli.c, src/pl_kernel_run.c and src/pl_kernel_self.c. */
enum pl_kernel_case { PL_CASE_OPTION = 0, PL_CASE_SCAN = 1, PL_CASE_PROBE = 2 };

enum pl_kernel_reason {
    PL_REASON_OK = 0,
    PL_REASON_USAGE = 1,
    PL_REASON_INPUT = 2,
    PL_REASON_KERNEL = 3,
    PL_REASON_IO = 4
};

enum pl_kernel_mode { PL_MODE_RUN = 0, PL_MODE_SELF_CHECK = 1, PL_MODE_PRINT_PARAMS = 2 };

/* The checked run options (paths borrowed from argv; NULL when absent). */
struct pl_kernel_args {
    int kase;
    const char *input;
    const char *output;
    const char *canonical;
    const char *trace;
    size_t records;
    uint32_t loops;
    unsigned threads;
    int echo;
    int handshake;
    uint16_t models;
    int64_t dte_min;
    int64_t dte_max;
    double lo;
    double hi;
};

/* The run options of pl-kernel (src/pl_kernel_opts.c). */
enum pl_opt {
    PL_OPT_CASE = 0,
    PL_OPT_INPUT,
    PL_OPT_RECORDS,
    PL_OPT_LOOPS,
    PL_OPT_THREADS,
    PL_OPT_ECHO,
    PL_OPT_MODELS,
    PL_OPT_OUTPUT,
    PL_OPT_CANONICAL,
    PL_OPT_TRACE,
    PL_OPT_HANDSHAKE,
    PL_OPT_DTE_MIN,
    PL_OPT_DTE_MAX,
    PL_OPT_LO,
    PL_OPT_HI,
    PL_OPT_COUNT
};

/* The index of the option named arg (a NUL-terminated text), or PL_OPT_COUNT. */
size_t pl_opt_find(const char *arg);

/* 1 for an option that takes a value. */
int pl_opt_takes_value(size_t k);

/* 1u << k. */
unsigned pl_opt_bit(size_t k);

/* The options that the case accepts (bit 1 << option). */
unsigned pl_opt_allowed(int kase);

/* An unsigned decimal of one to seven digits in [lo, hi]: 0 and *out, or -1. */
int pl_parse_uint(const char *text, uint32_t lo, uint32_t hi, uint32_t *out);

/* An int64 decimal (an optional leading '-', then digits, within the int64 range): 0 and *out,
 * or -1. */
int pl_parse_int64(const char *text, int64_t *out);

/* A finite binary64 (strtod over the whole text, which starts with a digit, a sign or a dot):
 * 0 and *out, or -1. */
int pl_parse_double(const char *text, double *out);

/* The case of the --case value, or -1. */
int pl_case_of(const char *text);

/* --records (1-20,000, required), --loops (1-1,000,000), --threads (0-4; 0 only outside the
 * option case) and --models (1-31) from values (indexed by enum pl_opt, NULL when absent) into
 * *a; a->kase is set. 0 or -1. */
int pl_parse_counts(const char **values, struct pl_kernel_args *a);

/* The four record-scan window values (all required) into *a. 0 or -1. */
int pl_parse_window(const char **values, struct pl_kernel_args *a);

/* Returns the mode (enum pl_kernel_mode) and fills *a for PL_MODE_RUN, or -1 for a usage error. */
int pl_kernel_parse(int argc, char **argv, struct pl_kernel_args *a);

/* One run of a case: reads the input, runs the loops, writes the files and the PLK1 line to out.
 * Returns an enum pl_kernel_reason. */
int pl_kernel_run(const struct pl_kernel_args *a, FILE *out);

/* The four self-check parts; PLK1 status=OK self_check=4 on out. Returns an enum
 * pl_kernel_reason (PL_REASON_KERNEL when a part fails). */
int pl_kernel_self_check(FILE *out);

/* The PLPARAMS line (crr_steps and the alo_scheme values) on out. Returns an enum
 * pl_kernel_reason. */
int pl_kernel_print_params(FILE *out);

/* The bytes of one probe input and output record (specs/project/batch.md "pl-kernel command
 * line"). */
#define PL_PROBE_IN_BYTES 72u
#define PL_PROBE_OUT_BYTES 64u

/* PL_REASON_OK when every one of the n 72-byte probe records has a model 0.0-4.0 and a zero
 * field with the bits 0, else PL_REASON_INPUT (src/pl_kernel_probe.c). */
int pl_probe_check(const uint8_t *input, size_t n);

/* One 72-byte probe record through pl_price_and_greeks into its 64-byte output record. */
void pl_probe_record(const uint8_t *rec, const struct pl_params *p, uint8_t *out);
