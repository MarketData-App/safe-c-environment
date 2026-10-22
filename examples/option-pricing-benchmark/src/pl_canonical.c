#include "pl_canonical.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* Canonical result bytes (specs/project/protocol.md "Canonical form"): a transliteration of
 * optionlab.reference.canonical_result (reference.py:311-348). json.dumps(sort_keys=True,
 * separators=(',', ':')) fixes the key order and the separators, so they are fixed strings
 * here; the numbers go through pl_sink_hex_bits. */

/* The JSON string of a status 0-8 of spec 3.3 (the caller has checked the range). */
static const char *pl_status_name(unsigned status) {
    switch (status) {
    case PL_INVALID_INPUT:
        return "\"INVALID_INPUT\"";
    case PL_EXPIRED:
        return "\"EXPIRED\"";
    case PL_NO_BID:
        return "\"NO_BID\"";
    case PL_CROSSED:
        return "\"CROSSED\"";
    case PL_MODEL_DOMAIN:
        return "\"MODEL_DOMAIN\"";
    case PL_BELOW_MIN:
        return "\"BELOW_MIN\"";
    case PL_ABOVE_MAX:
        return "\"ABOVE_MAX\"";
    case PL_NOT_CONVERGED:
        return "\"NOT_CONVERGED\"";
    default:
        return "\"OK\"";
    }
}

struct pl_key {
    const char *name;
    int index;
};

/* Model i (0-4) in sorted key order (alo, baw, bjs, bsm, crr) with its MODELS5 index. */
static struct pl_key pl_model_key(size_t i) {
    struct pl_key key = {"\"crr\":{", PL_MODEL_CRR};
    switch (i) {
    case 0u:
        key.name = "\"alo\":{";
        key.index = PL_MODEL_ALO;
        break;
    case 1u:
        key.name = "\"baw\":{";
        key.index = PL_MODEL_BAW;
        break;
    case 2u:
        key.name = "\"bjs\":{";
        key.index = PL_MODEL_BJS;
        break;
    case 3u:
        key.name = "\"bsm\":{";
        key.index = PL_MODEL_BSM;
        break;
    default:
        break;
    }
    return key;
}

#define PL_KEY_FLAGS (-1)
#define PL_KEY_STATUS (-2)
#define PL_MODEL_KEYS 9u

/* Key f (0-8) of a model object in sorted order with its field index (or flags, status). */
static struct pl_key pl_field_key(size_t f) {
    struct pl_key key = {"\"vega\":[", PL_VEGA};
    switch (f) {
    case 0u:
        key.name = "\"delta\":[";
        key.index = PL_DELTA;
        break;
    case 1u:
        key.name = "\"flags\":[";
        key.index = PL_KEY_FLAGS;
        break;
    case 2u:
        key.name = "\"gamma\":[";
        key.index = PL_GAMMA;
        break;
    case 3u:
        key.name = "\"iv\":[";
        key.index = PL_IV;
        break;
    case 4u:
        key.name = "\"price\":[";
        key.index = PL_PRICE;
        break;
    case 5u:
        key.name = "\"rho\":[";
        key.index = PL_RHO;
        break;
    case 6u:
        key.name = "\"status\":[";
        key.index = PL_KEY_STATUS;
        break;
    case 7u:
        key.name = "\"theta\":[";
        key.index = PL_THETA;
        break;
    default:
        break;
    }
    return key;
}

/* One value of the column `key` of model part m. */
static void pl_write_value(struct pl_sink *s, const struct pl_model_result *m, int key) {
    if (key == PL_KEY_FLAGS) {
        pl_sink_uint(s, m->flags);
    } else if (key == PL_KEY_STATUS) {
        pl_sink_text(s, pl_status_name(m->status));
    } else {
        const double v = *(m->values + key);
        if (pl_is_nan(v)) {
            pl_sink_text(s, "null");
        } else {
            pl_sink_text(s, "\"");
            pl_sink_hex_bits(s, v);
            pl_sink_text(s, "\"");
        }
    }
}

/* The model object of MODELS5 index k: {"delta":[...],...,"vega":[...]}. */
static void pl_write_model(struct pl_sink *s, const struct pl_contract_result *rows, size_t n,
                           int k) {
    for (size_t f = 0; f < PL_MODEL_KEYS; f++) {
        const struct pl_key key = pl_field_key(f);
        pl_sink_text(s, f == 0u ? "" : ",");
        pl_sink_text(s, key.name);
        for (size_t i = 0; i < n; i++) {
            pl_sink_text(s, i == 0u ? "" : ",");
            pl_write_value(s, (rows + i)->model + k, key.index);
        }
        pl_sink_text(s, "]");
    }
}

/* 1 when every selected part of rows[0..n) may enter the bytes: status 0-8, no infinity. */
static int pl_rows_valid(const struct pl_contract_result *rows, size_t n, unsigned mask) {
    for (size_t i = 0; i < n; i++) {
        for (size_t k = 0; k < PL_MODELS; k++) {
            const struct pl_model_result *m = (rows + i)->model + k;
            if ((mask >> k & 1u) == 0u) {
                continue;
            }
            if (m->status > PL_OK) {
                return 0;
            }
            for (size_t j = 0; j < PL_FIELDS; j++) {
                const double v = *(m->values + j);
                if (!pl_is_nan(v) && !pl_is_finite(v)) {
                    return 0;
                }
            }
        }
    }
    return 1;
}

int pl_canonical_write(struct pl_sink *s, const struct pl_contract_result *rows, size_t n,
                       uint16_t models) {
    const unsigned mask = models;
    if (mask == 0u || mask > PL_MASK_MODELS5 || !pl_rows_valid(rows, n, mask)) {
        return -1;
    }
    if (mask == PL_MASK_ALL3) {
        pl_sink_text(s, "{\"digest_form\":\"ocg-v1\",\"models\":{");
    } else {
        pl_sink_text(s, "{\"digest_form\":\"ocg-v1m\",\"mask\":");
        pl_sink_uint(s, mask);
        pl_sink_text(s, ",\"models\":{");
    }
    int first = 1;
    for (size_t i = 0; i < PL_MODELS; i++) {
        const struct pl_key key = pl_model_key(i);
        if ((mask >> (unsigned)key.index & 1u) == 0u) {
            continue;
        }
        pl_sink_text(s, first ? "" : ",");
        first = 0;
        pl_sink_text(s, key.name);
        pl_write_model(s, rows, n, key.index);
        pl_sink_text(s, "}");
    }
    pl_sink_text(s, "},\"n\":");
    pl_sink_uint(s, n);
    pl_sink_text(s, "}");
    return pl_sink_flush(s) == 0 ? 0 : -2;
}
