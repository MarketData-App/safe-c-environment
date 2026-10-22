#include "pl_ieee.h"
#include "pl_kernel_cli.h"
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* The option table and the value parsers of pl-kernel (specs/project/batch.md "pl-kernel command
 * line"): a translation unit of its own, so that each call inside the argument loop of
 * src/pl_kernel_cli.c is opaque to the GCC analyzer. */

/* The name of option k. */
static const char *pl_opt_name(size_t k) {
    switch (k) {
    case PL_OPT_CASE:
        return "--case";
    case PL_OPT_INPUT:
        return "--input";
    case PL_OPT_RECORDS:
        return "--records";
    case PL_OPT_LOOPS:
        return "--loops";
    case PL_OPT_THREADS:
        return "--threads";
    case PL_OPT_ECHO:
        return "--echo";
    case PL_OPT_MODELS:
        return "--models";
    case PL_OPT_OUTPUT:
        return "--output";
    case PL_OPT_CANONICAL:
        return "--canonical";
    case PL_OPT_TRACE:
        return "--trace";
    case PL_OPT_HANDSHAKE:
        return "--handshake";
    case PL_OPT_DTE_MIN:
        return "--dte-min";
    case PL_OPT_DTE_MAX:
        return "--dte-max";
    case PL_OPT_LO:
        return "--moneyness-lo";
    default:
        return "--moneyness-hi";
    }
}

/* 1 for an option that takes a value. */
int pl_opt_takes_value(size_t k) { return k != PL_OPT_ECHO && k != PL_OPT_HANDSHAKE; }

unsigned pl_opt_bit(size_t k) { return 1u << k; }

/* The options that the case accepts (bit 1 << option). */
unsigned pl_opt_allowed(int kase) {
    unsigned common = pl_opt_bit(PL_OPT_HANDSHAKE);
    for (size_t k = PL_OPT_CASE; k <= PL_OPT_THREADS; k++) {
        common |= pl_opt_bit(k);
    }
    if (kase == PL_CASE_SCAN) {
        const unsigned dte = pl_opt_bit(PL_OPT_DTE_MIN) | pl_opt_bit(PL_OPT_DTE_MAX);
        return common | dte | pl_opt_bit(PL_OPT_LO) | pl_opt_bit(PL_OPT_HI);
    }
    if (kase == PL_CASE_PROBE) {
        return common | pl_opt_bit(PL_OPT_OUTPUT);
    }
    const unsigned written = pl_opt_bit(PL_OPT_OUTPUT) | pl_opt_bit(PL_OPT_CANONICAL);
    const unsigned files = written | pl_opt_bit(PL_OPT_TRACE);
    return common | pl_opt_bit(PL_OPT_ECHO) | pl_opt_bit(PL_OPT_MODELS) | files;
}

/* The index of the option named arg, or PL_OPT_COUNT. */
size_t pl_opt_find(const char *arg) {
    for (size_t k = 0; k < PL_OPT_COUNT; k++) {
        if (strcmp(arg, pl_opt_name(k)) == 0) {
            return k;
        }
    }
    return PL_OPT_COUNT;
}

/* An unsigned decimal of one to seven digits in [lo, hi]: 0 and *out, or -1. */
int pl_parse_uint(const char *text, uint32_t lo, uint32_t hi, uint32_t *out) {
    uint32_t v = 0u;
    size_t n = 0u;
    while (*(text + n) != '\0') {
        const char c = *(text + n);
        if (c < '0' || c > '9' || n >= 7u) {
            return -1;
        }
        v = v * 10u + (uint32_t)(c - '0');
        n++;
    }
    if (n == 0u || v < lo || v > hi) {
        return -1;
    }
    *out = v;
    return 0;
}

/* An int64 decimal (an optional leading '-', then digits; strtoll refuses a value outside the
 * int64 range with ERANGE): 0 and *out, or -1. */
int pl_parse_int64(const char *text, int64_t *out) {
    const char *digits = text + (*text == '-' ? 1 : 0);
    if (*digits < '0' || *digits > '9') {
        return -1;
    }
    char *end = NULL;
    errno = 0;
    const long long v = strtoll(text, &end, 10);
    if (errno != 0 || end == NULL || *end != '\0') {
        return -1;
    }
    *out = (int64_t)v;
    return 0;
}

/* A finite binary64 (strtod over the whole text, which starts with a digit, a sign or a dot):
 * 0 and *out, or -1. */
int pl_parse_double(const char *text, double *out) {
    const char c = *text;
    if (!((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.')) {
        return -1;
    }
    char *end = NULL;
    const double v = strtod(text, &end);
    if (end == NULL || end == text || *end != '\0' || !pl_is_finite(v)) {
        return -1;
    }
    *out = v;
    return 0;
}

/* The case of the --case value, or -1. */
int pl_case_of(const char *text) {
    if (strcmp(text, "option-chain-greeks") == 0) {
        return PL_CASE_OPTION;
    }
    if (strcmp(text, "record-scan") == 0) {
        return PL_CASE_SCAN;
    }
    return strcmp(text, "probe") == 0 ? PL_CASE_PROBE : -1;
}

/* The counts and the mask: --records, --loops, --threads, --models. 0 or -1. */
int pl_parse_counts(const char **values, struct pl_kernel_args *a) {
    uint32_t records = 0u, threads = 0u, models = PL_MASK_ALL3;
    if (pl_parse_uint(*(values + PL_OPT_RECORDS), 1u, 20000u, &records) != 0) {
        return -1;
    }
    a->records = records;
    if (*(values + PL_OPT_LOOPS) != NULL &&
        pl_parse_uint(*(values + PL_OPT_LOOPS), 1u, 1000000u, &a->loops) != 0) {
        return -1;
    }
    if (*(values + PL_OPT_THREADS) != NULL &&
        pl_parse_uint(*(values + PL_OPT_THREADS), 0u, 4u, &threads) != 0) {
        return -1;
    }
    a->threads = threads;
    if (*(values + PL_OPT_MODELS) != NULL &&
        pl_parse_uint(*(values + PL_OPT_MODELS), 1u, PL_MASK_MODELS5, &models) != 0) {
        return -1;
    }
    a->models = (uint16_t)models;
    return a->kase != PL_CASE_OPTION && threads != 0u ? -1 : 0;
}

/* The record-scan window: all four values are required. 0 or -1. */
int pl_parse_window(const char **values, struct pl_kernel_args *a) {
    const int dte = *(values + PL_OPT_DTE_MIN) != NULL && *(values + PL_OPT_DTE_MAX) != NULL;
    if (!dte || *(values + PL_OPT_LO) == NULL || *(values + PL_OPT_HI) == NULL) {
        return -1;
    }
    if (pl_parse_int64(*(values + PL_OPT_DTE_MIN), &a->dte_min) != 0 ||
        pl_parse_int64(*(values + PL_OPT_DTE_MAX), &a->dte_max) != 0) {
        return -1;
    }
    if (pl_parse_double(*(values + PL_OPT_LO), &a->lo) != 0 ||
        pl_parse_double(*(values + PL_OPT_HI), &a->hi) != 0) {
        return -1;
    }
    return 0;
}
