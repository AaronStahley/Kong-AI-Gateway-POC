# Targets shared by both parts. From the repository root: make -C shared help
# Claude Code targets take PART=1|2 and read that part's .env.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PART1_ENV := ../part-01/.env
PART2_ENV := ../part-02/.env
TF        := terraform -chdir=../part-02/terraform

.PHONY: help dashboard-diff dashboard claude claude-smoke

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

# --- Usage dashboard (kongctl) ----------------------------------------------------------------
# Gateway IDs feed the dashboard's `!env` filter (an empty one would hide that gateway, so stop).
# kongctl reads KONGCTL_DEFAULT_KONNECT_PAT, not KONNECT_TOKEN.
GATEWAY_IDS := \
	PART1_GATEWAY_ID="$$(set -a; source $(PART1_ENV); echo "$$AI_GATEWAY_ID")"; \
	PART2_GATEWAY_ID="$$($(TF) output -raw gateway_id)"; \
	: "$${PART1_GATEWAY_ID:?AI_GATEWAY_ID is empty in $(PART1_ENV)}"; \
	: "$${PART2_GATEWAY_ID:?no gateway_id output: run make -C part-02 tf-apply}"; \
	set -a; source $(PART2_ENV); set +a; \
	export PART1_GATEWAY_ID PART2_GATEWAY_ID KONGCTL_DEFAULT_KONNECT_PAT="$$KONNECT_TOKEN";

dashboard-diff: ## Preview the usage dashboard changes in Konnect (changes nothing)
	$(GATEWAY_IDS) kongctl diff -f dashboard

dashboard: ## Create/update the usage dashboard in Konnect (kongctl apply)
	$(GATEWAY_IDS) kongctl apply -f dashboard

# --- Claude Code through the gateway ----------------------------------------------------------
# env -i passes only the client variables below, so admin secrets in .env never reach Claude Code.
# Unset variables stay unset (not empty), so mcp.json's ${KONG_PROXY_URL:-...} default still works.
CLAUDE_VARS := CLAUDE_CONFIG_DIR ANTHROPIC_BASE_URL ANTHROPIC_API_KEY \
	ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL \
	CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT KONG_GATEWAY_KEY GITHUB_PAT KONG_PROXY_URL
CLAUDE_ENV = \
	case "$(PART)" in 1|2) ;; *) echo "Set PART=1 or PART=2" >&2; exit 2 ;; esac; \
	set -a; source ../part-0$(PART)/.env; set +a; \
	: "$${ANTHROPIC_API_KEY:?is empty in part-0$(PART)/.env}"; \
	: "$${CLAUDE_CONFIG_DIR:?is empty in part-0$(PART)/.env}"; \
	mkdir -p "$$CLAUDE_CONFIG_DIR"; cd ..; \
	env -i HOME="$$HOME" PATH="$$PATH" TERM="$${TERM:-xterm}" CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
	$(foreach v,$(CLAUDE_VARS),$${$(v):+$(v)="$$$(v)"})

# Built-in tools for the interactive session. GitHub MCP tools come from shared/claude/mcp.json.
# CLAUDE_TOOLS=default gives the normal set (more tool definitions, so more tokens per request).
CLAUDE_TOOLS ?= Read

claude: ## Start a cheap Claude Code session through the gateway (PART=1|2)
	@$(CLAUDE_ENV) claude --bare --model claude-main --effort low \
		--mcp-config shared/claude/mcp.json --strict-mcp-config --tools "$(CLAUDE_TOOLS)"

claude-smoke: ## Scripted Claude Code checks through the gateway (PART=1|2)
	@$(CLAUDE_ENV) python3 shared/claude_smoke.py
