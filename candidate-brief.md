# Kong PS / Forward Deployed Engineer — Take-Home Exercise

## Why this exercise looks the way it does

This exercise is built to mirror a real Kong Professional Services engagement end to end: a
customer shows up with AI use cases that are only partly thought through, you ask questions and
reframe them into something buildable, you prototype fast to build confidence, you harden that
prototype into infrastructure-as-code for production, and — because this is how real engagements
go — the requirements may shift on you partway through.

You'll have a **live kickoff call** (30–45 min) followed by a **bounded async build** (target
~4–6 hours of hands-on effort, spread over however many days you need), followed by a **live
readout/demo** (45–60 min).

---

## Stage 0 — Live kickoff call

Your interviewer will play a customer stakeholder walking you through what they want. Treat it
like a real discovery call: ask clarifying questions, push back on anything that sounds
infeasible or contradictory, and don't be afraid to say "that doesn't quite work together —
here's what I think you actually mean." By the end of the call you should have a shared,
scoped understanding of what you're building.

**Within 24 hours of the call**, send your interviewer a short written recap (half a page is
plenty): the use cases you're actually building for, anything you flagged as contradictory or
infeasible and how you resolved it, and your phased plan (what you'll prototype first, what
becomes production infra). This recap is part of the deliverable — write it like you'd write it
for a real customer.

---

## Stage 1 — Quick prototype: Konnect Control Plane + local data plane

Goal: get something real running fast, the way you would in the first week of an engagement.

1. Sign up for a [Konnect](https://konghq.com/products/kong-konnect) free trial org if you don't
   already have one, and create a Control Plane.
2. Run a self-managed data plane locally with Docker in **hybrid mode**, connected to that
   Control Plane. Reference: [Hybrid mode — Kong Gateway](https://developer.konghq.com/gateway/hybrid-mode/).
3. Configure the **AI Proxy** plugin so that traffic is routed through Kong to a real LLM
   provider (Anthropic is the easiest path given the rest of this exercise, but use whatever the
   Stage 0 conversation pointed you toward). Kong has a worked example for this exact setup:
   [AI Proxy: Configure AI Proxy for Claude Code with Anthropic](https://developer.konghq.com/plugins/ai-proxy/examples/claude-code-anthropic/).
4. **Point Claude Code itself at your Kong route** and drive a real Claude Code session through
   it — i.e., Claude Code's own LLM traffic should flow through your Kong data plane on its way
   to Anthropic. See [Claude Code network configuration](https://code.claude.com/docs/en/network-config)
   for how Claude Code is redirected to a custom endpoint. Confirm the traffic is actually
   flowing through Kong (Konnect Advanced Analytics, or the data plane's own logs) — don't just
   confirm Claude Code still works, confirm it's going through your gateway.
5. Configure the **AI MCP Proxy** plugin to front at least one API or tool through Kong as an
   MCP endpoint. Reference: [AI MCP Proxy plugin](https://developer.konghq.com/plugins/ai-mcp-proxy/).
   Good candidates for this exercise include:
   - GitHub MCP Server (repo/PR/issues workflows): [GitHub MCP Server](https://github.com/github/github-mcp-server)
   - Atlassian Rovo MCP Server (Jira/Confluence/etc.): [Getting started with Atlassian Rovo MCP Server](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/)
   Add it to Claude Code as a remote MCP server and confirm it connects and that you can
   actually invoke the tool from inside a Claude Code session. See
   [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp) for the
   `claude mcp add` syntax.


---

## Stage 2 — Productionize: Terraform + Kubernetes data plane

Goal: take what you proved out in Stage 1 and turn it into something a customer's platform team
could actually run.

You've been given a **starter kit** in `starter-kit/` with:
- `terraform/` — a partial Terraform configuration using the official
  [`Kong/konnect` provider](https://registry.terraform.io/providers/Kong/konnect/latest) to
  declare a Control Plane. It is **not** complete — you need to add the AI Gateway plugin
  resources (AI Proxy, AI MCP Proxy) so the same config you hand-built in Stage 1 is reproducible
  as code.
- `helm/dp-values.yaml` — Helm values for deploying a self-managed, hybrid-mode data plane into
  a local Kubernetes cluster (`kind` or `minikube` both work fine) against the Terraform-managed
  Control Plane.

A note on tool choice, since it isn't obvious from the provider names alone: because this data
plane is Konnect-hybrid-managed, **all gateway configuration (services/routes/plugins) belongs
in the `konnect` Terraform provider**, not the separate `kong-gateway` provider — that one is for
fully self-managed Kong with no Konnect control plane involved at all.

Run `terraform apply`, deploy the Helm chart, and get the Kubernetes-hosted data plane connected
to your Control Plane. **Something in this starter kit is broken.** `terraform apply` will
succeed and the data plane pod will come up healthy, but the data plane will not show as
connected in Konnect. Debug it the way you would a real customer environment: check pod
status and logs, check what Konnect Manager shows about connected nodes, and check the hybrid
mode docs linked above for what has to match between control plane and data plane. Fix the
starter kit, don't work around it. **Write up what was wrong and how you found it** — this is
graded as its own thing, separate from whether you got there in the end.

Once the Kubernetes data plane is connected, re-point your Claude Code LLM traffic and MCP
connection at it and re-confirm both work end-to-end against the production-shaped setup.

---

## Submission

Send a repo (or zip) containing:
- Your Terraform code and Helm values (with any problems fixed).
- `WRITEUP.md` covering: your Stage 0 recap (or a link to the message you already sent), the
  architecture decisions you made and why, how you diagnosed and fixed the planted bug, and how
  you handled the mid-build customer update.
- Anything else you think is worth including (screenshots of Konnect Manager showing connected
  nodes, a Loom of the Claude Code session going through Kong, etc. — optional, not required).

**On time budget**: this is scoped for ~4–6 hours of hands-on effort. If you're well past that
and still stuck on something, stop, write down where you got to and what you'd do next, and
bring it to the readout. We'd rather see good judgment about when to stop than a perfect but
massively over-time submission.

---

## Stage 3 — Live readout/demo

Walk us through what you built, demo the Stage 1 prototype and the Stage 2 production setup live,
and narrate the bug you found and fixed. We'll ask about trade-offs: why hybrid mode instead of
alternatives, why you chose the AI MCP Proxy mode you did, what you'd change with more time, and
how you'd explain the Stage 0 contradiction back to the customer in plain language.

---

## Reference index

- Konnect hybrid mode: https://developer.konghq.com/gateway/hybrid-mode/
- AI Proxy plugin (Claude Code + Anthropic example): https://developer.konghq.com/plugins/ai-proxy/examples/claude-code-anthropic/
- AI Proxy plugin (general): https://developer.konghq.com/ai-gateway/
- AI MCP Proxy plugin: https://developer.konghq.com/plugins/ai-mcp-proxy/
- Konnect AI Cookbooks: https://developer.konghq.com/cookbooks/
- Kong Terraform providers overview: https://developer.konghq.com/terraform/
- `Kong/konnect` Terraform provider: https://registry.terraform.io/providers/Kong/konnect/latest
- Kong Helm charts: https://github.com/Kong/charts
- Claude Code network configuration (`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`): https://code.claude.com/docs/en/network-config
- Connect Claude Code to tools via MCP (`claude mcp add`): https://code.claude.com/docs/en/mcp
