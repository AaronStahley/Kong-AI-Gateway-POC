# Kong AI Gateway POC

A proof of concept for an insurance customer. Developers use Claude Code, and every model call and
GitHub MCP tool call goes through Kong AI Gateway 2.2. Kong decides which models and tools each team
can use, redacts PII before prompts leave the network, and caps token spend per team.

Built in two parts: a fast prototype (Docker data plane, kongctl config), then the same gateway in
production shape (Terraform control plane, Kong Operator data plane on Kubernetes).

## What it proves

The customer's bar for production: *"LLM access from Claude going through the gateway, MCP access
from Claude going through the gateway, and some PII detection and sanitization."*

| Requirement | How it's met | Proved by |
|---|---|---|
| Governed model access | Gateway holds the Anthropic key; developers use their own gateway key; only `claude-main` and `claude-fast` are allowed | Suite step 3–4; `claude-smoke` model check |
| Governed MCP access | GitHub MCP behind Kong; engineering gets 12 read-and-comment tools, finance none, only `github-admins` (empty) can merge or delete | Suite step 5; `claude-smoke` MCP check |
| PII protection, secure by default | Prompts redacted before Anthropic; PII service down → request blocked | Suite step 6 (`--fail-closed`); `claude-smoke` PII check |
| Usage control | Token allowances per team and per engineer (counted per model, see WRITEUP gaps); usage dashboard as code | Suite step 7; `shared/dashboard` |

## Architecture

The control plane runs in Konnect (SaaS). The data plane and the PII service run in the customer's
environment, so prompts are redacted before they leave. Prompts and responses never reach Konnect
(payload logging is off); it stores the config, including the Anthropic key.

| Component | Part 1 (prototype) | Part 2 (production shape) |
|---|---|---|
| Control plane + config | Konnect, configured with kongctl YAML (`part-01/config`) | Konnect, configured with Terraform (`part-02/terraform`) |
| Data plane `kong/kong-ai-gateway:2.2.0` | Docker Compose | Kong Operator on kind (Helm), standing in for EKS |
| PII service `kong/ai-pii-service` | Docker Compose | Kubernetes Deployment (same Helm chart) |
| Upstreams | Anthropic API, GitHub remote MCP server | same |
| Client | Claude Code, pointed at `http://localhost:8000` | same address, no client changes |

AI Gateway 2.x is used instead of the brief's plugin-based approach, as agreed with the customer at
kickoff. Models, MCP servers, consumers and policies are first-class Konnect entities. Reasons and
trade-offs are in [WRITEUP.md](WRITEUP.md).

## Repository layout

| Path | Contents |
|---|---|
| [`part-01/`](part-01/README.md) | Prototype: Docker Compose data plane, kongctl config, runbook |
| [`part-02/`](part-02/README.md) | Production shape: Terraform, Helm chart, kind config, Makefile, runbook |
| [`shared/`](shared/) | Test suite, Claude Code smoke test and session launcher, MCP client config, usage dashboard |
| [`starter-kit/`](starter-kit/) | Starter kit provided with the brief, as provided |
| [`part-02-starter-kit/`](part-02-starter-kit/README.md) | The starter kit run as provided, with the planted bug found and fixed |
| [`WRITEUP.md`](WRITEUP.md) | Decisions, problems found, gaps and path to production |
| [`stage0-recap-email.md`](stage0-recap-email.md) | Kickoff recap sent to the customer (scope source of truth) |
| `candidate-brief.md` | The exercise brief |

## Quick start

You need a Konnect token, an Anthropic API key, and a GitHub fine-grained token. Each part has its
own `.env` (copy it from `.env.example`). The part READMEs list every prerequisite.

**Part 1 (Docker).** Create the gateway in the Konnect UI first, then follow the
[Part 1 runbook](part-01/README.md). In short:

```bash
docker compose -f part-01/docker-compose.yaml up -d   # after registering the DP certificate
kongctl apply -f part-01/config
python3 part-01/test_gateway.py
```

**Part 2 (Terraform + kind).** Stop Part 1 first: both use port 8000.

```bash
make -C part-02 up      # Terraform gateway + kind + Kong Operator + data plane
make -C part-02 test
```

**Either part** (the dashboard needs both gateways):

```bash
make -C shared claude-smoke PART=2   # real Claude Code through the gateway (3 cheap prompts)
make -C shared claude PART=2         # interactive Claude Code session through the gateway
make -C shared dashboard             # apply the usage dashboard to Konnect
```

## Tests

`shared/gateway_suite.py` holds every check. Each part's `test_gateway.py` adapts it to its
environment (where the expected tools come from, and how to stop the PII service). The checks call
the gateway directly with tiny requests, so a full run costs a few hundred tokens.

| Step (the suite runs 6 last) | Checks |
|---|---|
| 3–4 Models and keys | `claude-main` and `claude-fast` answer; unlisted model → 503; tool-use conversation works; no key → 401 |
| 5 GitHub MCP | no key → 401; engineering sees exactly the approved tools; finance sees none; engineering's `get_me` reaches GitHub; engineering's `merge_pull_request` and finance's `get_me` are denied by Kong |
| 6 PII | email and phone redacted; known 2.2.0 issues tracked; `--fail-closed`: PII service down → request blocked |
| 7 Token limits | engineering has limit headers; one engineer's tokens hit the team counter but not another's own; finance → 429 once over; the ceiling is per developer |

Results: `PASS`, `FAIL`, `SKIP` (missing `.env` value), `XFAIL` (a documented 2.2.0 limitation still
fails as expected), `XPASS` (a limitation now works: update the docs). Exit code 0 means no failures.

`shared/claude_smoke.py` (`make -C shared claude-smoke`) runs the real Claude Code client through
the gateway. It checks a model reply, a GitHub MCP read, and PII redaction.

Static checks for Part 2: `make -C part-02 lint` (terraform fmt/validate, helm lint/template).

## Evidence

Screenshots of Konnect: [`part-01/evidence/`](part-01/evidence/) and
[`part-02/evidence/`](part-02/evidence/). Starter kit bug, before and after the fix:
[`part-02-starter-kit/evidence/`](part-02-starter-kit/evidence/).
