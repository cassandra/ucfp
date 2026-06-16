# Project Structure

## Directory Structure

### Top-level Directory
- `src`: application source code
- `deploy`: deploy/build inputs, split by lane -- `deploy/local` (self-host
  image + run script), `deploy/droplet` (cloud/MySQL adaptation), `deploy/package`
  (shared docker configs), plus the shared `env-generate.py` / `env-drift-check.sh`
- `dev`: developer bootstrap scripts (`dev-setup.sh`, `init-env-dev.sh`)
- `docs`: all documentation suitable to live in markdown
- `data`: local data, ignored by git and docker
- `Makefile`: convenience wrappers for building, testing, packaging, and running
- `VERSION`: single source of truth for the running version
- `install.sh` / `update.sh`: one-line self-host installer / updater
- `docker-compose.example.yml` / `local.env.example`: self-host compose + env templates

### The `src` Directory

Apps are **top-level siblings** under `src/`, not nested under an `apps/`
package. The project's own config package is named for the project.

- `ucfp`: the project config package -- entry-point `urls.py`/`views.py`, Django
  config (`settings/`, `wsgi.py`, `asgi.py`, `middleware.py`), the
  client/server `environment/`, and the app-wide `static/` and `templates/`
- `common`: reusable, domain-agnostic infrastructure (utilities, base classes,
  the `antinode` ajax framework, singletons, enums)
- `notify`, `background`, `testing`: other reusable infrastructure apps
- `custom`: the custom user model and other project-wide customizations
- `user`: user-facing account features
- `organization`: extends the custom user model to allow for groups of users
- `bin`: helper scripts that run inside the Docker container

A new self-contained feature app is a new top-level sibling (e.g. `src/blog/`),
not `src/ucfp/blog/`. Code that the project *owns and declares* (config,
site-root shell, the env spec) lives in `ucfp/`; self-contained apps it *uses*
are siblings.

## Module Structure

All new files should adhere to these naming and directory conventions.

### New Application Modules / Django Apps

New coherent and semi-independent subsystems that are domain-specific, should be placed in `src/ucfp/${MODULE_NAME}` where `MODULE_ANME` is the name of the module that would be added to `INSTALLED_APPS`.

If a new module si introduced that is generally useful across many domains, it is worth considering if it should be added to the base `https://github.com/cassandra/zzz-app` project for future project use.

### Application Module Structure

**Filenames: Django Conventions**:
- `admin.py` : Django admin model registrations
- `apps.py` : app metadata and initialization
- `migrations/` : Django migrations
- `models.py` : database ORM models
- `urls.py` : url patterns
- `views.py` : views

**Filenames: App Conventions**:
- `constants.py` : shared constants for this module (for client/server-shared
  ids and names, see the `AppConst` pattern in
  [Frontend Guidelines](../frontend/frontend-guidelines.md))
- `context_processors.py` : Django context processors
- `decorators.py` : decorators
- `enums.py` : enums relevant to this module (subclass `LabeledEnum`)
- `forms.py` : Django forms
- `middleware.py` : middleware
- `signals.py` : Django signal definitions
- `schemas.py` : non-DB, in-memory container models with little
  business logic
- `view_mixins.py` : view helpers that use `HttpRequest` / `HttpResponse`

**Filenames: Reserved for Auto-discovery Mechanisms**:
- `monitors.py` : auto-discovered background monitor tasks
- `settings.py` : auto-discovered user-configuration options

**Filename Patterns**:
- `*_data.py` : larger in-memory data classes needing their own module
- `*_helpers.py` : general helpers with miscellaneous responsibilities
- `*_manager.py` : a central control module, usually extending `Singleton`
- `*_utils.py` : stateless utility functions

**Directories: Django Conventions**:
- `management/commands` : management commands
- `templates` : templates
- `templatetags` : template tag definitions

**Directories: App Conventions**:
- `assets` : non-code files and data that business logic depends on
- `templates/{app_name}/pages` : an entire HTML page or sub-page
- `templates/{app_name}/modals` : modal dialog fragments
- `templates/{app_name}/panes` : an HTML fragment
- `tests` : all module-specific tests
- `tests/data` : non-code data supporting tests
- `tests/ui` : development-only UI tests and devtools (auto-discovered `urls.py`)
