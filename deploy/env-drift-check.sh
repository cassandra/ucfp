#!/bin/bash
# Verify that all four declarations of the environment-variable set agree:
#
#   1. the app           ucfp/environment/server.py  (all_env_var_names: the
#                        _ENV_SPEC table plus the list-valued extras) -- canonical
#   2. the generator     deploy/env-generate.py --example
#   3. the installer     install.sh --list-env-vars  (the standalone one-liner,
#                        which duplicates the set in its own heredoc)
#   4. the template      local.env.example
#
# install.sh and local.env.example cannot import the app (install.sh is curled
# standalone; the template is just text), so each restates the variable set.
# This check is what keeps those copies honest. Drift in any source means a
# missed update -- treated as a build failure.
#
# Compared as name sets (sorted, unique); values are ignored. Assumes the
# virtualenv is active (the app-side extraction imports the project).
set -euo pipefail

cd "$( dirname "${BASH_SOURCE[0]}" )/.."

extract_names() {
    # An env-file-shaped stream on stdin -> just the KEY names.
    grep -E '^[A-Z][A-Z0-9_]+=' | sed 's/=.*//' | sort -u
}

app_names=$(
    cd src && python -c \
        "from ucfp.environment.server import all_env_var_names; print('\n'.join(sorted(set(all_env_var_names()))))"
)
generator_names=$( python3 deploy/env-generate.py --example | extract_names )
install_names=$( bash install.sh --list-env-vars )
example_names=$( extract_names < local.env.example )

fail() {
    local label_a="$1" set_a="$2" label_b="$3" set_b="$4"
    echo
    echo "Env-var drift between ${label_a} and ${label_b}:"
    diff -u \
        <( printf '%s\n' "${set_a}" ) \
        <( printf '%s\n' "${set_b}" ) \
        | sed "s|^---.*|--- ${label_a}|; s|^+++.*|+++ ${label_b}|" || true
    echo
    echo "Fix: update whichever source is behind so all four declare the same set."
    exit 1
}

[[ "${app_names}" == "${generator_names}" ]] || fail \
    "server.py (all_env_var_names)" "${app_names}" \
    "deploy/env-generate.py --example" "${generator_names}"

[[ "${app_names}" == "${install_names}" ]] || fail \
    "server.py (all_env_var_names)" "${app_names}" \
    "install.sh --list-env-vars" "${install_names}"

[[ "${app_names}" == "${example_names}" ]] || fail \
    "server.py (all_env_var_names)" "${app_names}" \
    "local.env.example" "${example_names}"

count=$( printf '%s\n' "${app_names}" | wc -l | tr -d '[:space:]' )
echo "env-drift-check: OK (${count} env vars consistent across server.py, env-generate.py, install.sh, and local.env.example)"
