# Environment Variables

Adding (or removing, or renaming) an environment variable that the app reads
touches **four** sources. A cross-source drift check covers all four
automatically; the one thing it cannot check -- that the app-side field is
wired to the right env-var name -- relies on code review.

## When to read this

Any time you add a new env-var dependency in app code: a new credential, a new
feature flag, a new config knob. If the app reads it from the environment
(always via `EnvironmentSettings`, never `os.environ` directly in app code), the
ritual below applies.

## The four sources

In recommended order:

1. **`src/ucfp/environment/server.py`** -- the single source of truth. Two parts:

   - Add a row to the `_ENV_SPEC` table: `_EnvVarSpec( field, env_name, kind,
     default )`. Use `default = None` for required vars (absence raises
     `ImproperlyConfigured`); use an empty/zero/false default for optional.
   - Add the matching field to the `EnvironmentSettings` dataclass with its type
     and default.

   Field names are intentionally **not** required to match env-var names --
   `EnvironmentSettings.SECRET_KEY` reads `DJANGO_SECRET_KEY`,
   `EnvironmentSettings.REDIS_HOST` reads `UCFP_REDIS_HOST`. The mapping (the
   `UCFP_` prefix and any rename) lives in the `_ENV_SPEC` row. Pick a field
   name that reads naturally in app code; the env-var name follows the project's
   `UCFP_` / `DJANGO_` convention (`ENV_PREFIX` is the one place the prefix is
   set).

   `all_env_var_names()` is what the drift check anchors on. It returns every
   `_ENV_SPEC` env-var name plus the extras that `get()` reads directly (the
   list-valued `UCFP_EXTRA_HOST_URLS` / `UCFP_EXTRA_CSP_URLS` and the
   `UCFP_SECRET_URL_PREFIX_UUID` transform). **A var that needs more than a
   simple read** -- a value transform, cross-field logic -- is handled
   explicitly in `EnvironmentSettings.get()` rather than the table; when you add
   one, also append its env-var name to the `all_env_var_names()` extras list so
   the drift check sees it.

2. **`deploy/env-generate.py`** -- two edits in the same file:
   - Add an entry to `SETTING_SECTIONS` under the appropriate section (or add a
     new section). Include a placeholder value and an inline required/optional note.
   - Assign a real value: in the `__init__` overlay (`self._settings_map.update(...)`)
     for fixed defaults, or in `generate_env_file()` for interactively-filled vars.

   `validate_settings()` fails the run if a var is declared in `SETTING_SECTIONS`
   but never assigned (or assigned but not declared), so this step self-checks the
   moment you run `make env-build`.

3. **`install.sh`** -- the heredoc between `<< INSTALL_ENV_FILE_EOF` and
   `INSTALL_ENV_FILE_EOF` (the unique terminator lets `install.sh --list-env-vars`
   extract names unambiguously). Add a `KEY=value` line: a literal default, or
   `${SHELL_VAR}` interpolation for generated values (e.g.
   `DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}`).

4. **`local.env.example`** at the repo root -- add the `KEY=value` line (blank or
   placeholder). The easy way to keep it canonical is to regenerate the variable
   list from the generator:

   ```shell
   ./deploy/env-generate.py --example
   ```

## Verification

After the edits, run the drift check:

```shell
make env-drift-check
```

It compares the variable-name sets across all four sources --
`server.py` (`all_env_var_names()`), `deploy/env-generate.py --example`,
`install.sh --list-env-vars`, and `local.env.example` -- and fails with a
labeled diff on mismatch. It is wired into `make check` and the
`Check Env-Var Drift` step in `.github/workflows/django-tests.yml`.

## Vars read via ENV but kept out of the generated env files

Some variables should be readable through `ENV` in every environment yet **not**
written into the generated self-host env files (an operator supplies them only
when they opt in -- e.g. a MySQL connection for a cloud deployment). Mark the
`_EnvVarSpec` row `in_env_file = False`: `get()` still reads it (with its
default), but `all_env_var_names()` excludes it, so `env-generate.py`,
`install.sh`, and `local.env.example` are not required to declare it and the
drift check stays green. See [Droplet Setup](../project/droplet-setup.md).

## What the drift check does *not* cover

- **The `_ENV_SPEC` field-to-env-var wiring** -- the check confirms the same
  *set of env-var names* exists everywhere, not that `_EnvVarSpec` maps each name
  to the intended `EnvironmentSettings` field. A typo'd field or env name is a
  **code-review responsibility**.
- **Direct `os.environ` access elsewhere** -- app code should route all env
  access through `EnvironmentSettings`; nothing enforces it. An
  `os.environ.get('UCFP_SOMETHING_NEW')` added elsewhere is caught only by review.

If a var reaches production without `install.sh` and the example file knowing
about it, users will not have it set. The drift check is the first line; code
review is the second.
