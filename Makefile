.DEFAULT_GOAL := help

UV ?= uv
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
FPL ?= $(VENV)/bin/fpl

MODEL ?= full
HORIZON ?= 4
THRESHOLD ?= 2.0
MAX_HITS ?= 0
GWS ?= 6
TOP ?= 25
TO_GW ?= 19
SEASON ?= 2025-26
FROM_GW ?= 5

.PHONY: help setup test doctor update load-history odds refresh my-team fixtures \
	projections recommend recommend-save chips settle backtest backtest-teams \
	backtest-minutes check-scoring

help: ## Show available targets and common parameter overrides
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target> [NAME=value]\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf '\nCommon parameters: MODEL=%s HORIZON=%s THRESHOLD=%s MAX_HITS=%s TO_GW=%s SEASON=%s FROM_GW=%s\n' "$(MODEL)" "$(HORIZON)" "$(THRESHOLD)" "$(MAX_HITS)" "$(TO_GW)" "$(SEASON)" "$(FROM_GW)"

setup: ## Create or update the virtual environment from uv.lock
	$(UV) sync --dev

test: ## Run the complete test suite
	$(PYTHON) -m pytest -q

doctor: ## Check Python, dependencies, settings, and FPL API access
	$(FPL) doctor

update: ## Download current-season FPL data
	$(FPL) update

load-history: ## Load historical states and results into the database
	$(FPL) load-history

odds: ## Download odds and calculate expected goal rates
	$(FPL) odds

refresh: ## Refresh current-season data and bookmaker odds
	$(FPL) update
	$(FPL) odds

my-team: ## Show the current squad, bank, transfers, and chips
	$(FPL) my-team

fixtures: ## Show fixture and clean-sheet projections; override GWS=6
	$(FPL) fixtures --gws $(GWS)

projections: ## Show full-model projections; override TOP=25 and POSITION=DEF
	$(FPL) projections --top $(TOP) $(if $(POSITION),--position $(POSITION),)

recommend: ## Recommend transfers; override MODEL, HORIZON, THRESHOLD, or MAX_HITS
	$(FPL) recommend --model $(MODEL) --horizon $(HORIZON) --threshold $(THRESHOLD) --max-hits $(MAX_HITS)

recommend-save: ## Recommend transfers and save the run for later settlement
	$(FPL) recommend --model $(MODEL) --horizon $(HORIZON) --threshold $(THRESHOLD) --max-hits $(MAX_HITS) --save

chips: ## Value available chips through TO_GW=19
	$(FPL) chips --model $(MODEL) --to-gw $(TO_GW)

settle: ## Settle saved recommendations after finished gameweeks
	$(FPL) settle

backtest: ## Backtest MODEL=full on SEASON=2025-26 from FROM_GW=5 to TO_GW=19
	$(FPL) backtest --model $(MODEL) --season $(SEASON) --from-gw $(FROM_GW) --to-gw $(TO_GW)

backtest-teams: ## Backtest clean-sheet probabilities for SEASON=2025-26
	$(FPL) backtest-teams --season $(SEASON)

backtest-minutes: ## Backtest the minutes model for SEASON=2025-26
	$(FPL) backtest-minutes --season $(SEASON)

check-scoring: ## Recompute FPL points and report mismatches for SEASON=2025-26
	$(FPL) check-scoring --season $(SEASON)
