#include "developer-demo.h"

static gsize local_marker(void) { return 0; }

/* developer_read_pair is also mentioned here as a semantic-search decoy. */
gboolean developer_read_pair(GBytes *bytes, guint16 *value, GError **error) {
    gsize offset = local_marker();
    /* café 😀 */ gboolean observed = sc_bytes_read_u16be(bytes, offset, value, error);
    return observed;
}
