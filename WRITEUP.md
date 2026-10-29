# Kong AI Gateway POC: write-up

## Stage 0 recap

Recap sent on Oct 23. The copy here has names and email headers removed: [stage0-recap-email.md](stage0-recap-email.md).

The customer's bar for moving to production: "LLM access from Claude going through the gateway, MCP access
from Claude going through the gateway, and some PII detection and sanitization."

What we're building for:

1. **Model access.** Claude Code calls Anthropic only through Kong. Kong holds the provider key and
   decides which models are allowed.
2. **MCP access.** GitHub MCP through Kong. Each group gets a set list of tools, for example
   engineering can read code and comment on issues but can't merge or delete.
3. **PII and secrets.** Prompts are redacted before they leave. If the PII check fails, the request
   is blocked.
4. **Usage.** Token allowances per team, and a view of spend by model, team and user.

What I flagged on the call:

- Production in two weeks fits a pilot with one team, not a company-wide rollout. The customer's IdP,
  EKS egress and PII service HA are the critical path.
- Fail closed makes the PII service as critical as the gateway.
- Konnect is SaaS: it gets usage metadata only, payload logging stays off, and redaction doesn't
  replace provider retention terms.
- No IdP yet, so each developer gets a key mapped to a team group. SSO later is a config change.

Plan: a Docker prototype first, then the same config in Terraform with a Kubernetes data plane
(Kong Operator via Helm, on kind in place of EKS). Built on AI Gateway 2.2, pinned, instead of the
plugin-based approach. IdP, EKS, PII HA, shared rate-limit counters and retention agreements come
after the POC.

## Architecture: choices and trade-offs

| Area | Choice | Reason and trade-off |
| --- | --- | --- |
| Platform | AI Gateway 2.2 instead of AI Proxy / AI MCP Proxy plugins | Models, providers, MCP servers, groups and policies are Konnect entities; Konnect generates the routes and plugins. Fewer pieces to wire together. Agreed with the customer at kickoff. |
| Platform | Version pinned | Image `kong/kong-ai-gateway:2.2.0`, gateway minimum runtime 2.2, auto-upgrade off. Control plane and data plane must match exactly, so 2.3 is a deliberate change in both places. |
| Platform | Hybrid mode | Konnect runs the control plane. The data plane and its PII service run in the customer's environment, so prompts are redacted before they leave. |
| Model access | Two aliases, everything else refused | `claude-main` → Sonnet 5.5, `claude-fast` → Haiku 5.5. The Anthropic key is stored in Konnect and pushed to the data plane; it's never on developer laptops. |
| Identity | One key per developer, in a group | Policies and tool ACLs refer to `engineering` and `finance`, so swapping key-auth for SSO later doesn't touch them. |
| GitHub MCP | Passthrough | GitHub already hosts an MCP server; Kong filters its tools rather than generating them. |
| GitHub MCP | Allow list | Only `github-admins` (empty for now) gets a tool by default; each approved tool adds `engineering`. A first deny list of three tools also gave engineering push, branch and PR creation. New GitHub tools stay off until approved. |
| GitHub MCP | Developer's own GitHub token | GitHub's audit log shows who did what. Cost: the token also works against GitHub directly. A shared gateway-held token is simpler; the customer's choice. |
| PII | Redact and forward; block on failure | Placeholders replace matches. If the PII service is down or errors, the request is blocked. Matched values and bodies aren't logged, so nothing sensitive reaches Konnect. |
| PII | Identifiers and secrets only | SSN, cards, bank, email, phone, IDs, credentials. Names, URLs, IPs and dates match all over source code and slow every request. Names are the gap, which matters for an insurer. |
| Usage | Team and per-engineer token budgets | Engineering 1M/day shared and 250k/day each; finance separate. Demo numbers; set real ones from a few weeks of usage. |
| Usage | Dashboard in kongctl, not Terraform | A change from the recap: the provider has no dashboard resource. Still code (`shared/dashboard`). |
| Phase 2 | Terraform owns the gateway; the operator runs only the data plane | `KonnectAIGateway` in `Mirror` mode reads the gateway and never edits it, so each layer has one owner. The operator also creates and registers the data plane certificate. |

A Kubernetes/GitOps-first team could let the operator own the gateway too (one tool, Argo CD, drift
correction). Against that: its AI Gateway APIs are `v1alpha1`, config lives in the cluster, and
Terraform teams lose their workflow. I used Terraform because that's what we agreed.

## Planted bug: what broke and how I found it

**Where:** [`part-02-starter-kit/`](part-02-starter-kit/README.md). Part 2 uses AI Gateway 2.2 and Kong
Operator, as agreed at kickoff, so it never ran the kit's classic control plane or `kong/kong` chart
and never hit the bug. I ran the kit as provided in a copy of it (the original `starter-kit/` is
untouched), on the Part 2 kind cluster in its own namespace, and fixed it there.

**Symptom.** `terraform apply` succeeded, but the data plane pod went into `CrashLoopBackOff`.
The brief expected a healthy pod that doesn't connect; here it crash-looped. The single fix below was
enough for the node to connect.

**How I found it** (pods and logs in k9s):

| Step | What it showed |
| --- | --- |
| Pod status | `CrashLoopBackOff` |
| Previous container's logs | Kong exits during init: `Malformed cluster endpoint address` in `kong/tools/messaging.lua` (`check_address`) |
| The environment the pod got | `KONG_CLUSTER_CONTROL_PLANE=https://<id>.us.cp.konghq.com`, a URL with a scheme and no port (same for telemetry) |
| Where that came from | The raw `terraform output` values. The kit's `outputs.tf` describes them as the values for `cluster_control_plane` / `cluster_telemetry_endpoint`, and its README passes them with `--set` unchanged |
| What Kong expects | `host:port`, per the [configuration reference](https://developer.konghq.com/gateway/configuration/) (hybrid mode data plane section). Part 1 already used `<host>:443`. The provider docs don't say which format the attribute returns, so I went by the real output value |
| Provider version | The kit's `~> 3.5` constraint and no lock file meant `init` took the newest 3.x, 3.27.0. If the version the kit was written against returned a format Kong accepted, the newer provider may have hidden the brief's intended bug (healthy pod, not connected) behind this crash. Not verified. Either way, a loose constraint can change an output's format underneath you |

**Root cause.** A format mismatch at the handoff between Terraform and Helm: the provider returns
the endpoints as URLs, Kong's `cluster_*` settings need `host:port`, and the kit wires one straight
into the other.

**Fix.** In the kit's `outputs.tf`, strip the scheme and add the port, so the kit's documented
`--set` step works as written:

```diff
-  value = konnect_gateway_control_plane.this.config.control_plane_endpoint
+  value = "${trimprefix(konnect_gateway_control_plane.this.config.control_plane_endpoint, "https://")}:443"
```

(Same for `telemetry_endpoint`.) Fixing it in the output rather than in the `--set` command keeps a
single place that knows the format. It assumes `https://` and port 443.

**Confirmed.** `terraform apply` changed only the two outputs. After redeploying, the pod ran with 0
restarts, and Konnect showed the node as Connected, In sync and Compatible (3.4.3.29). Evidence:
[`part-02-starter-kit/evidence/`](part-02-starter-kit/evidence/).

**What carries over to Part 2.** The same hybrid settings apply (data plane role, mTLS cluster
certificate, control plane and telemetry endpoints, versions that match the control plane), but Kong
Operator handles them: it reads the endpoints from Konnect and creates and registers the certificate.
That's why Part 2 never saw this.

## What was tested

Both phases ran the same scripted checks ([shared/gateway_suite.py](shared/gateway_suite.py)),
through a thin adapter per environment ([part-01](part-01/test_gateway.py) for Docker,
[part-02](part-02/test_gateway.py) for Kubernetes). Results:

- Model access: valid key returns 200; no key 401; a model off the allow-list is rejected with 503.
- GitHub MCP: engineering sees the 12 approved tools, finance 0; engineering's `merge_pull_request`
  and finance's `get_me` are denied when called by name; `add_issue_comment` lands on GitHub under
  the developer's own account.
- Known 2.2.0 sanitizer issues (adaptive thinking on Haiku, images in tool results, image-only
  messages) are tracked as expected failures, so a fix shows up as soon as it lands.
- PII: email and phone arrive at the model as placeholders. With the PII service stopped, the request
  returns 500 and is not forwarded.
- Token limits: finance gets 429 with `Retry-After` once its allowance is used; one engineer's usage
  lowers the team counter, not another engineer's.
- Part 2: `terraform plan` reported no changes after apply. On the kind data plane (2.2.0, connected
  and in sync in Konnect), the full suite with the fail-closed check gave 18 passed, 0 failed,
  3 expected failures (Oct 28).
- Part 2 with the real client: a Claude Code session through the kind data plane called GitHub
  through Kong (engineering's 12 tools listed), and a prompt with a phone number, email and SSN
  reached the model as three placeholders. With `ai-pii-service` scaled to 0, the same prompt was
  blocked with a gateway 500 (`connection refused`), which Claude Code retried. As finance, the same
  MCP server connected with no tools, and a prompt over the hourly allowance got
  `429 AI token rate limit exceeded`. These show under `poc-part-02` in the usage dashboard:
  tokens by team, developer and model, finance's 429, and MCP tool calls by team.

Evidence: [`part-02/evidence/`](part-02/evidence/) (node connected, suite output, Claude Code
session, dashboard).

Runbooks: [part-01/README.md](part-01/README.md), [part-02/README.md](part-02/README.md).

## Problems hit along the way

| Issue | Evidence and fix |
| --- | --- |
| Data plane `OOMKilled` on kind | Exit 137 about 4 s after each start; 20 worker processes logged; `nproc` = 20. Kong's `auto` worker count follows the node's CPUs, not the pod's limit. Part 1 had the same 20 workers but no memory limit. Set `KONG_NGINX_WORKER_PROCESSES=2` (about 520 MB). Keep workers equal to the CPU limit in production. |
| Token limit capped the wrong users | A no-match limit entry applies to everyone, and the first version was one shared bucket: an org-wide 1M/day cap. Found from `X-AI-RateLimit-Remaining-*` headers, fixed by partitioning per consumer. Verify limits through response headers, not config. |
| PII sanitizer vs Claude Code (2.2.0) | Adaptive thinking on `claude-fast` returns 400; images in tool results and image-only messages return 500. Isolated with minimal curl requests after detaching the policy. No fix released. Workarounds: chat on `claude-main`, avoid image reads. Candidate bug report for Kong. |
| Provider drift in Terraform | Konnect fills in policy defaults and reorders a model's policies, so `plan` was never clean. Fixed in code (Konnect's defaults listed in `policies.tf`, policy order matched in `provider-models.tf`), not with `ignore_changes`, which would hide real drift. |
| `${ANTHROPIC_API_KEY}` empty in `.mcp.json` headers | Claude Code does not expand it there (header-capture listener). A separate `KONG_GATEWAY_KEY` variable works around it. |
| PII requests still failing after the PII container restarted (Part 1) | Up to 30 s of `DNS resolution failed` from some workers. Docker drops a stopped container's name and each Kong worker caches the miss (`dns_not_found_ttl`). The suite waits 30 s after recovery. On kind the name keeps resolving to the Service: with the PII service scaled to 0 the error is `connection refused`, not a DNS failure, so this is a Docker Compose artifact. |
| Unlisted model returns 503, not 4xx | The allow-list rejects in ~2 ms without reaching Anthropic, but as a 5xx Claude Code retries it and it inflates the error rate. Still to check whether the status is configurable. |
| MCP `acls` locked engineering out in Terraform | Provider 3.27's `acls` is a server-level gate checked before tool ACLs; Part 1's default-tool rule maps to `default_tool_acls`. The suite's tool-list checks catch either mistake. |

## Mid-build requirement change

No change in requirements arrived during the build, although the brief expects one, and I haven't
invented one to fill this section. Had one come, I would have compared it with the scope
agreed in the [Stage 0 recap](stage0-recap-email.md), assessed the impact on Terraform, Helm and
the test suite, confirmed the change with the customer in writing, and shipped it with a matching
test.

## Gaps and the path to production

| Gap | Why it matters | Next step |
| --- | --- | --- |
| Names aren't redacted | Customer names and addresses can reach Anthropic | Add entity types per team and measure the latency cost |
| Sanitizer breaks some Claude Code requests on 2.2.0 | Haiku thinking and image reads fail | Retest on 2.3; test every model or client change against the guardrails first |
| PII outage blocks all AI traffic | Developers see slow, retried 5xx errors | PII service replicas, monitoring, shorter timeout |
| PII detection log not built | Promised in the recap (who, PII type, count); the counts aren't in Konnect analytics | Logging policy to the customer's SIEM (deferred) |
| Cost shows $0 | Konnect has no prices for these models, so spend reads zero | Set `input_cost` / `output_cost` on the model targets (untested) |
| Token counters are per pod, in memory | Restarts reset allowances; replicas count separately | Redis-backed counters |
| Token allowances count per model | Each model keeps its own counters: an engineer at 0 left on `claude-main` still had 247k on `claude-fast` (`X-AI-RateLimit-Remaining-*` headers). The 250k/engineer and 1M/team budgets are effectively per model, roughly doubling the cap | Check in Kong's docs whether counters can be shared across models; otherwise set per-model limits that add up to the budget |
| Redaction isn't a retention agreement | Missed PII is still governed by provider terms | Confirm retention, training use and region with each provider |
| Developers could bypass the gateway | Controls only apply to traffic through Kong | MDM-managed Claude Code settings, keys only on the gateway, egress to providers blocked except from Kong |
| GitHub PATs live on laptops | Long-lived secret that also works directly against GitHub | SSO to Kong plus a GitHub App; meanwhile PAT approval, short expiry, IP allow list |
| Branch writes disabled | Tool ACLs can't limit which branch | Turn on once GitHub rulesets protect `main` |

Not built: IdP integration, EKS deployment, Atlassian MCP, OpenCode, Insomnia collection. Built from
the stretch goals: MCP tool calls in the usage dashboard.

## How this was built

I started Part 1 by hand: building the gateway in the Konnect UI, and making quick changes and
debugging through Konnect's MCP server from Claude Code. Once it worked, I captured it with
`kongctl dump declarative`, so the setup could be applied again to another Konnect environment
instead of rebuilt by hand. I cleaned up the export (secrets replaced with `!env`, references between
entities) and from then on changed the gateway through that YAML. Part 1 was later torn down and
rebuilt from its README.

Part 2 was built from Part 1's working config rather than from scratch. Each kongctl file maps to a
`konnect_ai_gateway_*` Terraform resource (provider, models, MCP server, auth strategy, consumers and
groups, policies), so the Terraform was mostly a translation of settings already proven in Part 1.
The Helm chart took the data plane image and the PII service from Part 1's Docker Compose file, with
Kong Operator taking over the parts Compose did by hand (cluster endpoints and the data plane
certificate). The same test suite then ran against both, which is how I knew the translation was
faithful.

I used Claude Code as a pair: researching Kong docs, drafting config and docs, and querying Konnect
through its MCP server. I ran every apply, deploy and test myself and made the design calls.
