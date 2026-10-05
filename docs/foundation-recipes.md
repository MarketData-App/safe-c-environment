# Checked foundation usage

Read [the contract](../specs/foundation-contract.md) before using an adapter.
The executable [recipes.c](../foundation/tests/recipes.c) is the canonical
compiled example. Qualification runs it with the ordinary, sanitizer, coverage,
fuzz-instrumented and hardened dependency profiles. Its AST checks receive no
boundary exemption.

Initialize automatic owners to NULL, check each annotated result, and use the
matching cleanup: `g_autoptr(ScText)`, `g_autoptr(ScBytesList)`,
`g_autoptr(ScBytesMap)`, `g_autoptr(GBytes)` and `g_autoptr(GError)`.
An owned text snapshot uses `g_autofree gchar *` or `g_free`. Returning an
automatic owner requires `g_steal_pointer`; returning its address directly
would leave the caller with a released object. Clear an existing owned output
before asking an accessor to publish a new owner.

`sc_bytes_copy` creates immutable independent storage from initialized caller
bytes. A nonempty `sc_bytes_slice` retains its parent; an empty slice is an
independent empty owner. `sc_bytes_read_u16be` checks the logical range and
decodes byte order without an unaligned integer cast. Lists and maps retain
their values; accessors return a new reference. Map keys are copied. Replacement
retains the incoming owner before releasing the previous owner, including when
both names designate the same object.

Choose limits before construction. Text accepts complete UTF-8 fragments with
no embedded NUL; snapshot storage includes a terminator outside its logical
length. Counts, key sizes and aggregate payload caps remain finite. Check size
addition/multiplication and signed lengths before allocation or narrowing;
choose the destination width's maximum before any explicit conversion.
Recoverable errors preserve container contents, ownership and pending errors.
An omitted GError receiver does not turn failure into success.

The default allocation profile is `glib-fail-stop`. These limits bound logical
work; they do not make ordinary GLib allocation failure recoverable. Error
reporting itself can allocate. No automatic restart or durability behavior is
selected by this starter.

Mutable adapters are confined to one thread. Immutable bytes can be shared
after synchronized publication while a live owner remains. Reference counting
does not synchronize a mutable container. A declared span length cannot prove
that the pointer denotes live initialized storage. These are caller conventions,
separate from the mechanically enforced API and profile inventories.

Use `./tools/safety foundation doctor`, `foundation check` and
`foundation selftest` alongside the existing fast/full/CI commands. Acquisition
is an explicit separate operation; checks never download or upgrade a library.
Application source directories remain empty until later authorization.
