# Stage 0 Recap

Thanks for walking me through your goals yesterday. Here's what I heard and how I plan to approach the POC. Let me know if I got anything wrong.

## What we're building for

1. Governed model access for coding agents. Claude Code sends its LLM traffic through Kong. The gateway decides which models are allowed and holds the provider credentials, so developers never handle them.
2. Governed MCP access. For the POC, GitHub MCP goes through Kong with tool-level restrictions by group. For example, Engineering can read code and comment on issues, but can't merge pull requests or delete files. Atlassian follows the same pattern (work Jira tickets, but don't create projects or spaces), and so can other internal systems later.
3. PII and secret protection, secure by default. Prompts are scanned before they leave your network. When PII is detected, I'll redact it by default and forward the cleaned prompt. Let me know if you'd rather block the request outright. If detection fails or is unavailable, the request is blocked and the harness gets a gateway error. Each detection is recorded in the gateway logs (who sent it, PII type and count), so you can report a hit rate.
4. Usage control. Model control comes first (item 1), then per-team token allowances so nobody wakes up to a surprise bill. A usage dashboard shows token spend and cost by model, team and user.

## Things I want to flag

- Timeline. As I mentioned on the call, end of month is a squeeze. Production in about two weeks is realistic for a governed pilot with one engineering team. It isn't realistic for a company-wide rollout. The critical path runs through your side: IdP integration, EKS networking and egress, and running the PII service with high availability. My proposal is a POC demo next week, then a production pilot, then a wider rollout.
- Secure-by-default means the PII check is now critical. Every prompt depends on the PII detection service. If it goes down, all AI traffic is blocked. That's what you want for security, but it means the service needs to run with redundancy and monitoring, just like the gateway itself.
- "PII never leaves the network" and SaaS observability. The Konnect control plane is SaaS. By default, it receives only usage, cost, and latency metadata, not prompts or responses. I'll keep payload logging off and also turn off the sanitizer's logging of the matched values, so PII doesn't end up in logs either. Redaction also doesn't replace data-retention terms, which you should confirm separately with Anthropic and any other model providers you use.
- Redaction isn't perfect. I'll show where it works and where it misses or over-redacts, so you can decide what's acceptable.
- Identity for the POC. We can't use your IdP yet, so each developer gets their own key mapped to a team group. Moving to your SSO groups is a configuration change in production, not a redesign.

## Platform version

As we agreed, I'll build on AI Gateway 2.2, the current stable release, rather than the older plugin-based approach. Models, MCP servers, consumer groups, and guardrails become first-class Konnect entities instead of plugins wired onto routes. That's simpler for your platform team to own, and you can configure tool-level access directly on each MCP server. I'll pin the data plane to 2.2 for the POC and look at 2.3 once it's released.

## Phased plan

- Phase 1: prototype. A Konnect AI Gateway with a local data plane. Claude Code model traffic and GitHub MCP calls go through Kong, with a model allow-list, tool-level access by group, PII redaction including a fail-closed demo, and team token limits.
- Phase 2: production shape. The same configuration as code (Terraform, using the Kong Konnect provider's AI Gateway resources), and the data plane deployed on Kubernetes with Kong Operator (installed with Helm) as a local stand-in for your EKS cluster. The usage dashboard starts from Konnect's built-in AI gateway template and is managed in Terraform too.
- Stretch goals, if time allows. Atlassian MCP with the "work tickets only" restriction, OpenCode through the gateway, and adding MCP server activity to the usage dashboard.
- After the POC. IdP integration, EKS deployment, high availability for the PII service, rate-limit counters shared across gateway replicas, and provider retention agreements.
