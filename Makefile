ifeq ($(OS),Windows_NT)
# The short path avoids the space in "Program Files", which older Windows
# builds of GNU Make otherwise hand to cmd.exe instead of Git Bash.
SHELL := C:/Progra~1/Git/bin/bash.exe
HUGO ?= hugo.exe
UV ?= uv.exe
else
SHELL := bash
HUGO ?= hugo
UV ?= uv
endif

.SHELLFLAGS := -c
.DEFAULT_GOAL := help

SOURCE ?=
ARCHIVE ?=
RECORD ?=
PERSONA ?=
OWNER_HANDLE ?=
PUBLIC_ARCHIVE ?=
OWNER_CONTROLLED ?=
STAGING ?=
OVERRIDES ?=
TWITTER_ARCHIVE ?=
MASTODON_ARCHIVE ?=

.PHONY: help check-tools serve build test archive-check archive-schema import-archive stage-archive resolve-links preview-archive promote-public-corpus validate-public-corpus ingest-one

help: ## Show available targets.
	@echo "check-tools        Confirm Hugo and uv"
	@echo "serve              Run the local Hugo server"
	@echo "build              Build without publishing"
	@echo "test               Run synthetic importer tests"
	@echo "archive-check      Inspect aggregate external archive structure"
	@echo "archive-schema     Inspect archive field names without values"
	@echo "import-archive     Dry-run a reviewed social archive"
	@echo "stage-archive      Write normalized records outside the repository"
	@echo "resolve-links      Cache unresolved public t.co redirects once"
	@echo "preview-archive    Compile ignored Hugo drafts for make serve"
	@echo "promote-public-corpus  Create tracked public-only canonical data"
	@echo "validate-public-corpus Validate tracked data and reject tracked archives"
	@echo "ingest-one         Reserved fail-closed Mastodon one-post importer"

check-tools: ## Confirm the Git Bash-oriented Hugo and uv toolchain.
	@command -v $(HUGO) >/dev/null || { echo "error: hugo is required" >&2; exit 1; }
	@command -v $(UV) >/dev/null || { echo "error: uv is required" >&2; exit 1; }
	@$(HUGO) version
	@$(UV) --version

serve: check-tools ## Run the local Hugo development server.
	$(HUGO) server --disableFastRender --renderToMemory

build: check-tools validate-public-corpus ## Validate and build the site without publishing it.
	$(HUGO) build --renderToMemory --gc --minify

test: ## Run importer tests through uv; fixtures must be synthetic.
	$(UV) run python -m unittest discover -s tests -p 'test_*.py'

archive-check: ## Safely inspect archive structure: make archive-check SOURCE=twitter ARCHIVE=/outside/repo/archive.zip
	@test -n "$(SOURCE)" || { echo "error: SOURCE=twitter or SOURCE=mastodon is required" >&2; exit 2; }
	@test -n "$(ARCHIVE)" || { echo "error: ARCHIVE=/absolute/path/outside/repo is required" >&2; exit 2; }
	$(UV) run python scripts/import_archive.py inspect --source "$(SOURCE)" --archive "$(ARCHIVE)"

archive-schema: ## Report source schema keys, never values.
	@test "$(SOURCE)" = "twitter" -o "$(SOURCE)" = "mastodon" || { echo "error: SOURCE=twitter or SOURCE=mastodon is required" >&2; exit 2; }
	@test -n "$(ARCHIVE)" || { echo "error: ARCHIVE=/absolute/path/outside/repo is required" >&2; exit 2; }
	$(UV) run python scripts/import_archive.py schema --source "$(SOURCE)" --archive "$(ARCHIVE)"

import-archive: ## Privacy-safe dry run; emits aggregate counts only.
	@test "$(SOURCE)" = "twitter" -o "$(SOURCE)" = "mastodon" || { echo "error: SOURCE=twitter or SOURCE=mastodon is required" >&2; exit 2; }
	@test -n "$(ARCHIVE)" || { echo "error: ARCHIVE=/absolute/path/outside/repo is required" >&2; exit 2; }
	@test -n "$(PERSONA)" || { echo "error: PERSONA=reviewed-owner-key is required" >&2; exit 2; }
	@if [ "$(SOURCE)" = twitter ]; then \
		test -n "$(OWNER_HANDLE)" || { echo "error: OWNER_HANDLE=reviewed-handle is required" >&2; exit 2; }; \
		test "$(PUBLIC_ARCHIVE)" = YES || { echo "error: set PUBLIC_ARCHIVE=YES only after confirming this persona's posts were public" >&2; exit 2; }; \
		$(UV) run python scripts/import_archive.py import --source twitter --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-handle "$(OWNER_HANDLE)" --assume-public --dry-run $(if $(OVERRIDES),--overrides "$(OVERRIDES)",); \
	else \
		test "$(OWNER_CONTROLLED)" = YES || { echo "error: set OWNER_CONTROLLED=YES only for an owner-controlled Mastodon archive" >&2; exit 2; }; \
		$(UV) run python scripts/import_archive.py import --source mastodon --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-controlled --dry-run; \
	fi

stage-archive: ## Write reviewed normalized records to a new external staging directory.
	@test -n "$(STAGING)" || { echo "error: STAGING=/new/path/outside/repo is required" >&2; exit 2; }
	@test "$(SOURCE)" = "twitter" -o "$(SOURCE)" = "mastodon" || { echo "error: SOURCE=twitter or SOURCE=mastodon is required" >&2; exit 2; }
	@test -n "$(ARCHIVE)" || { echo "error: ARCHIVE=/absolute/path/outside/repo is required" >&2; exit 2; }
	@test -n "$(PERSONA)" || { echo "error: PERSONA=reviewed-owner-key is required" >&2; exit 2; }
	@if [ "$(SOURCE)" = twitter ]; then \
		test -n "$(OWNER_HANDLE)" || { echo "error: OWNER_HANDLE=reviewed-handle is required" >&2; exit 2; }; \
		test "$(PUBLIC_ARCHIVE)" = YES || { echo "error: set PUBLIC_ARCHIVE=YES only after confirming this persona's posts were public" >&2; exit 2; }; \
		$(UV) run python scripts/import_archive.py import --source twitter --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-handle "$(OWNER_HANDLE)" --assume-public --output "$(STAGING)" $(if $(OVERRIDES),--overrides "$(OVERRIDES)",); \
	else \
		test "$(OWNER_CONTROLLED)" = YES || { echo "error: set OWNER_CONTROLLED=YES only for an owner-controlled Mastodon archive" >&2; exit 2; }; \
		$(UV) run python scripts/import_archive.py import --source mastodon --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-controlled --output "$(STAGING)"; \
	fi

preview-archive: ## Compile quarantined Hugo drafts that make serve can display.
	@test "$(SOURCE)" = "twitter" -o "$(SOURCE)" = "mastodon" || { echo "error: SOURCE=twitter or SOURCE=mastodon is required" >&2; exit 2; }
	@test -n "$(ARCHIVE)" || { echo "error: ARCHIVE=/absolute/path/outside/repo is required" >&2; exit 2; }
	@test -n "$(PERSONA)" || { echo "error: PERSONA=reviewed-owner-key is required" >&2; exit 2; }
	@if [ "$(SOURCE)" = twitter ]; then \
		test -n "$(OWNER_HANDLE)" || { echo "error: OWNER_HANDLE=reviewed-handle is required" >&2; exit 2; }; \
		test "$(PUBLIC_ARCHIVE)" = YES || { echo "error: set PUBLIC_ARCHIVE=YES only after confirming this persona's posts were public" >&2; exit 2; }; \
		$(UV) run python scripts/import_archive.py preview --source twitter --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-handle "$(OWNER_HANDLE)" --assume-public $(if $(OVERRIDES),--overrides "$(OVERRIDES)",); \
	else \
		test "$(OWNER_CONTROLLED)" = YES || { echo "error: set OWNER_CONTROLLED=YES only for an owner-controlled Mastodon archive" >&2; exit 2; }; \
		$(UV) run python scripts/import_archive.py preview --source mastodon --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-controlled; \
	fi

resolve-links: ## Resolve remaining public t.co redirects into the ignored local cache.
	@test "$(SOURCE)" = "twitter" || { echo "error: SOURCE=twitter is required" >&2; exit 2; }
	@test -n "$(ARCHIVE)" || { echo "error: ARCHIVE=/absolute/path/outside/repo is required" >&2; exit 2; }
	@test -n "$(PERSONA)" || { echo "error: PERSONA=reviewed-owner-key is required" >&2; exit 2; }
	@test -n "$(OWNER_HANDLE)" || { echo "error: OWNER_HANDLE=reviewed-handle is required" >&2; exit 2; }
	@test "$(PUBLIC_ARCHIVE)" = "YES" || { echo "error: set PUBLIC_ARCHIVE=YES only after confirming this persona's posts were public" >&2; exit 2; }
	$(UV) run python scripts/import_archive.py resolve-links --source twitter --archive "$(ARCHIVE)" --persona "$(PERSONA)" --owner-handle "$(OWNER_HANDLE)" --assume-public

promote-public-corpus: ## Promote reviewed Twitter and Mastodon records into tracked canonical data.
	@test -n "$(TWITTER_ARCHIVE)" || { echo "error: TWITTER_ARCHIVE=/path/outside/repo.zip is required" >&2; exit 2; }
	@test -n "$(MASTODON_ARCHIVE)" || { echo "error: MASTODON_ARCHIVE=/path/outside/repo.zip is required" >&2; exit 2; }
	@test -n "$(PERSONA)" || { echo "error: PERSONA=reviewed-owner-key is required" >&2; exit 2; }
	@test -n "$(OWNER_HANDLE)" || { echo "error: OWNER_HANDLE=reviewed-handle is required" >&2; exit 2; }
	@test "$(PUBLIC_ARCHIVE)" = YES || { echo "error: set PUBLIC_ARCHIVE=YES only after confirming this Twitter persona's posts were public" >&2; exit 2; }
	@test "$(OWNER_CONTROLLED)" = YES || { echo "error: set OWNER_CONTROLLED=YES only for an owner-controlled Mastodon archive" >&2; exit 2; }
	$(UV) run python scripts/import_archive.py promote-public \
		--twitter-archive "$(TWITTER_ARCHIVE)" \
		--mastodon-archive "$(MASTODON_ARCHIVE)" \
		--persona "$(PERSONA)" \
		--owner-handle "$(OWNER_HANDLE)" \
		--assume-twitter-public \
		--owner-controlled

validate-public-corpus: ## Validate tracked public data and ensure no raw archive is tracked.
	@test -z "$$(git ls-files '*.zip' '*.tgz' '*.tar.gz')" || { echo "error: a raw archive is tracked by Git" >&2; exit 2; }
	@test -f assets/public_archive/manifest.json || { echo "error: public corpus is missing; run make promote-public-corpus" >&2; exit 2; }
	@if git check-ignore -q assets/public_archive/manifest.json; then echo "error: public corpus is ignored and cannot be published" >&2; exit 2; fi
	$(UV) run python scripts/import_archive.py validate-public

ingest-one: ## Reserved one-post Mastodon entry point; currently fail-closed.
	@test -n "$(RECORD)" || { echo "error: RECORD=/path/to/one-exported-record.json is required" >&2; exit 2; }
	$(UV) run python scripts/import_archive.py ingest-one --source mastodon --record "$(RECORD)"
