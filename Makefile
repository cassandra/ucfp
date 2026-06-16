TEST_JS_PORT := 8765
NOW_DATE := $(shell date -u +'%Y-%m-%dT%H:%M:%SZ')
SCRIPTS = deploy/env-generate.py deploy/env-drift-check.sh deploy/local/run_container.sh \
	dev/dev-setup.sh install.sh update.sh

.DEFAULT_GOAL := check
.PHONY: check test test-parallel lint lint-strict test-js test-all \
	env-build env-build-dev env-drift-check fix-permissions \
	check-docker docker-build docker-run docker-run-fg docker-stop

# Targets assume the deployment env is sourced and the virtualenv is active.

# ----- Environment generation -------------------------------------------------
# Interactively generate an env file. `env-build-dev` writes the shell-sourced
# .private/env/development.sh (non-Docker dev); `env-build` writes the
# docker-compose env file for the local Docker run.

env-build:	fix-permissions
	./deploy/env-generate.py --env-name local

env-build-dev:	fix-permissions
	./deploy/env-generate.py --env-name development

fix-permissions:
	@chmod +x $(SCRIPTS)

# Verify env-generate.py and the app (server.py) declare the same env vars.
env-drift-check:	fix-permissions
	@bash deploy/env-drift-check.sh

# What should pass before committing / in CI.
check:	lint test env-drift-check

# ----- Python / Django tests --------------------------------------------------

test:
	cd src && ./manage.py test

test-parallel:
	cd src && ./manage.py test --parallel 4

# ----- flake8 -----------------------------------------------------------------
# `lint` is the lenient CI config (real errors only); `lint-strict` additionally
# enforces line length and the rest of the style rules.

lint:
	cd src && flake8 --config=.flake8-ci .

lint-strict:
	cd src && flake8 --config=.flake8 .

# ----- JavaScript (QUnit, in-browser) -----------------------------------------
# Serves the static directory and opens the master test runner
# (tests/test-all.html). Press Ctrl+C to stop the server when done. See
# docs/dev/frontend/javascript-testing.md.

test-js:
	@echo "Starting test server on http://localhost:$(TEST_JS_PORT)/tests/test-all.html"
	@echo "Press Ctrl+C to stop the server when done."
	@sleep 1 && ( \
		if command -v xdg-open > /dev/null; then \
			xdg-open http://localhost:$(TEST_JS_PORT)/tests/test-all.html; \
		elif command -v open > /dev/null; then \
			open http://localhost:$(TEST_JS_PORT)/tests/test-all.html; \
		fi \
	) &
	@python -m http.server $(TEST_JS_PORT) --directory src/ucfp/static

# All automated test suites we have. (E2E is added later when Playwright lands.)
test-all:	test test-js

# ----- Docker (local self-hosted run) -----------------------------------------
# The container is self-contained: supervisord runs redis + gunicorn + nginx
# (see package/docker_*.conf). `docker-build` bakes the image; `docker-run`
# launches it with the local env file (~/.ucfp/env/local.env, from `make
# env-build`) and host-mounted data dirs (~/.ucfp/{database,media}). See
# deploy/run_container.sh for the run details and overridable flags.

# Fail fast if the Docker daemon is not running.
check-docker:
	@docker info > /dev/null 2>&1 || \
		(echo "ERROR: Docker is not running. Please start Docker and try again." && exit 1)

docker-build:	check-docker deploy/local/Dockerfile
	@VERSION=$$(cat VERSION); \
	docker build \
		-f deploy/local/Dockerfile \
		--label "name=ucfp" \
		--label "version=$$VERSION" \
		--label "build-date=$(NOW_DATE)" \
		--tag ucfp:$$VERSION \
		--tag ucfp:latest .

docker-run:	check-docker fix-permissions
	./deploy/local/run_container.sh -bg

docker-run-fg:	check-docker fix-permissions
	./deploy/local/run_container.sh

docker-stop:
	docker stop ucfp
