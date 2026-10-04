# C template assessment

Assessed friendlyanon/cmake-init at `7e0c52fc73f235b073501407b71a27a94b5f7e42`.
Read the generator README, GPL notice, template-specific Unlicense, C executable
template, preset and in-source guard. Executed only the reviewed upstream
`compile_template` function in an offline, unprivileged scratch container using
the retained toolchain. The template and interpreter were read-only mounts.
This was a CMake template assessment, not a full generator invocation.

Context: `name=scratch_demo`, `version=0.1.0`, `description=template assessment only`,
`homepage=''`, `std=17`, `cmake_321=True`, `pm=False`. The rendered CMake output SHA256
was `967974798a1c33d770dd3a9d300a08f324e9311b78baaa8836e7f6be1a94d532`.
It declares C17, a library/object target, executable, installation and developer
mode. The interpreter and original templates remain provenance-tracked references;
they are not invoked during ordinary checks or instantiation.

Adopted the small in-source guard and explicit C-language/target structure. Kept
target-scoped checks and configuration original to this repository. Declined the
generated application, install rules, package managers and developer-mode bypass:
this starter has no application and always runs its protected safety gates. No
generated `main.c` or package-manager dependency was imported. Generator GPL terms
and template Unlicense terms remain distinct; first-party licensing awaits the owner.

Reproduce the rendering in scratch using the retained `template.py` with
`print(compile_template(template_text, context)())` and the context above (the
captured output includes print's final newline). Execute that
reviewed interpreter only inside the isolated pinned image; the host assessment
output is disposable and does not authorize an acceptance baseline.
