# Part 1: Prototype (Konnect AI Gateway + Docker data plane)

A Kong AI Gateway 2.2 in Konnect, with its data plane and PII service running locally in Docker
(hybrid mode), configured with kongctl declarative YAML. Claude Code's model calls and GitHub MCP
traffic go through it on `http://localhost:8000`.

AI Gateway 2.x is hybrid only: Konnect runs the control plane and you run the data plane, which uses
the `kong/kong-ai-gateway` image (not `kong/kong-gateway`). Control plane and data plane versions
must match exactly.

## Prerequisites

- Docker with Compose v2, `curl`, `jq`, `openssl`
- [kongctl](https://developer.konghq.com/kongctl/) v1.21+: `curl -fsSL https://get.konghq.com/kongctl | sh`
- Claude Code CLI
- A Konnect account and personal access token, and an Anthropic API key (only the gateway uses it)
- ~4 GB disk (the PII image is ~2.5 GB) and ~4 GB free memory (the PII service idles at ~1.5 GB)

Run every command from the repository root.

### Environment file

```bash
cp part-01/.env.example part-01/.env      # fill in as you go
set -a; source part-01/.env; set +a       # re-run after every edit
```

| Variable | Used by | Purpose |
|---|---|---|
| `KONNECT_TOKEN` | API calls, kongctl | Konnect personal access token |
| `AI_GATEWAY_ID` | kongctl | The gateway to configure (step 1) |
| `KONG_CLUSTER_CONTROL_PLANE_HOST`, `KONG_CLUSTER_TELEMETRY_HOST` | docker compose | The gateway's cluster endpoint hostnames (step 1) |
| `ANTHROPIC_PROVIDER_API_KEY` | kongctl | The real Anthropic key. Stored in Konnect; Claude Code never reads this name. |
| `ENG_DEV_1_KEY`, `ENG_DEV_2_KEY`, `FIN_DEV_1_KEY` | kongctl, tests | One gateway key per developer (step 2) |
| `KONG_GATEWAY_KEY` | `shared/claude/mcp.json` | Which developer you are, e.g. `${ENG_DEV_1_KEY}` |
| `ANTHROPIC_API_KEY` | Claude Code | Follows `KONG_GATEWAY_KEY`. Two names because Claude Code won't expand this one in MCP headers. |
| `ANTHROPIC_BASE_URL`, `ANTHROPIC_DEFAULT_*_MODEL`, `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT`, `CLAUDE_CONFIG_DIR` | Claude Code | Point Claude Code at the gateway and its aliases, in a separate profile (step 3) |
| `GITHUB_PAT` | `shared/claude/mcp.json`, tests | The developer's own GitHub token (step 5) |

One file holds both admin and developer settings because one person plays both roles in the POC. In
a real rollout each developer has only their gateway key and GitHub token.

## Step 1: Gateway and data plane

1. **Create the gateway.** In Konnect, go to **AI Gateway → New AI Gateway** and name it
   `poc-part-01`. Then look up its ID and endpoints:

   ```bash
   curl -s https://us.api.konghq.com/v1/ai-gateways \
     -H "Authorization: Bearer $KONNECT_TOKEN" | jq '.data[] | {id, name, endpoints}'
   ```

   In `.env`, set `AI_GATEWAY_ID` and the two `KONG_CLUSTER_*_HOST` values. Use hostnames only:
   no `https://` and no port.

2. **Create and register the data plane certificate.** The data plane authenticates to Konnect
   over mTLS. Only the public certificate leaves your machine.

   ```bash
   openssl req -new -x509 -nodes -newkey rsa:2048 -days 365 -subj "/CN=poc-part-01-dp/C=US" \
     -keyout part-01/certs/tls.key -out part-01/certs/tls.crt
   chmod 640 part-01/certs/tls.key   # the container's user reads it through your group (HOST_GID)

   curl -s -X POST "https://us.api.konghq.com/v1/ai-gateways/$AI_GATEWAY_ID/data-plane-certificates" \
     -H "Authorization: Bearer $KONNECT_TOKEN" -H "Content-Type: application/json" \
     -d "$(jq -n --rawfile c part-01/certs/tls.crt '{cert: $c, title: "poc-part-01-dp"}')" | jq '{id, message}'
   ```

   A returned `id` means it's registered. `part-01/certs/` contents are gitignored.

3. **Start the containers** (`docker-compose.yaml`):

   ```bash
   docker compose -f part-01/docker-compose.yaml up -d
   ```

   | Service | Image | Role |
   |---|---|---|
   | `kong-dp` | `kong/kong-ai-gateway:2.2.0` | Data plane; pulls config from Konnect, proxies on :8000 |
   | `ai-pii-service` | `kong/ai-pii-service:v0.2.2-en` | PII detection for the sanitizer; reachable only from the data plane |

   Hybrid-mode settings in `docker-compose.yaml`: `KONG_ROLE=data_plane`, `KONG_DATABASE=off`,
   `KONG_KONNECT_MODE=on`, `KONG_CLUSTER_MTLS=pki`, the certificate paths, and the two endpoints
   from `.env`. Nothing else from `.env` reaches the container.

### Verify

```bash
docker compose -f part-01/docker-compose.yaml ps   # both running, kong-dp healthy
curl -i http://localhost:8000                      # 404 "no Route matched" from Kong: up, no config yet
```

Konnect → **poc-part-01 → Data plane nodes** shows `poc-part-01-dp` connected.

**Troubleshooting**
- `unexpected HTTP response code: 401` in the logs: the certificate isn't registered with this
  gateway, or it was regenerated after registering. Register it again; no restart is needed.
- TLS or handshake errors: the endpoint hostnames are wrong.
- `Permission denied` on `tls.key`: run `chmod 640`, and set `HOST_GID` to `id -g`.
- "No license found" at startup is normal: the license arrives once the node connects.

## Step 2: Apply the gateway configuration

All gateway configuration is kongctl YAML in `config/`. Konnect turns it into the routes and plugins
the data plane runs. It started as a `kongctl dump declarative` export of the gateway I first built
in the Konnect UI, cleaned up so it can be applied to any Konnect org
([how this was built](../WRITEUP.md#how-this-was-built)).

| File | Declares |
|---|---|
| `anthropic-provider.yaml` | Anthropic provider; key from `$ANTHROPIC_PROVIDER_API_KEY` |
| `models.yaml` | Allow-list: `claude-main` → Sonnet 5.5, `claude-fast` → Haiku 5.5, with auth, PII and token policies |
| `auth.yaml` | `key-auth` on `x-api-key`, stripped before forwarding |
| `consumers.yaml` | `eng-dev-1`, `eng-dev-2`, `fin-dev-1`, and the groups `engineering`, `finance`, `github-admins` |
| `github-mcp.yaml` | GitHub MCP on `/mcp/github` with a per-group tool allow list |
| `pii-sanitizer.yaml` | PII sanitizer, fail closed |
| `token-limits.yaml` | Token allowances per team and per engineer |

Generate a key for each developer and put it in `.env` (`ENG_DEV_1_KEY`, `ENG_DEV_2_KEY`,
`FIN_DEV_1_KEY`). Keys are write-only in Konnect, so `.env` is the only copy.

```bash
openssl rand -hex 32   # once per developer

export KONGCTL_DEFAULT_KONNECT_PAT=$KONNECT_TOKEN   # or: kongctl login
kongctl diff  -f part-01/config    # preview
kongctl apply -f part-01/config
kongctl diff  -f part-01/config    # no changes = applied
```

`apply` creates and updates but never deletes; `kongctl sync` also removes resources that are no
longer in the files. In CI, use a system account token.

## Step 3: Models (Claude Code through the gateway)

Clients ask for an **alias**, and the gateway maps it to an upstream model and adds the Anthropic
key. Any other model name is rejected, so the platform team can swap models without touching
laptops.

**Cheapest way to test with the real client** (minimal context, GitHub MCP only, reads `.env` for you):

```bash
make -C shared claude PART=1         # interactive
make -C shared claude-smoke PART=1   # 3 scripted prompts: model, GitHub MCP read, PII redaction
```

These start Claude Code with `env -i`, so only the client variables reach it, never the provider key
or Konnect token. They also use `--bare`, `--effort low` and a single built-in tool, to keep each
request small. A normal session sends ~30k tokens per prompt. For the normal tool set:
`make -C shared claude PART=1 CLAUDE_TOOLS=default` (don't run `claude` after sourcing `.env`: that exports the provider key).

### Verify

```bash
H=(-H "x-api-key: $KONG_GATEWAY_KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json")

# Allowed alias -> 200
curl -s http://localhost:8000/v1/messages "${H[@]}" \
  -d '{"model":"claude-main","max_tokens":20,"messages":[{"role":"user","content":"hi"}]}'

# Not on the allow-list -> 503 from Kong; never reaches Anthropic
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/messages "${H[@]}" \
  -d '{"model":"claude-opus-5-5","max_tokens":20,"messages":[{"role":"user","content":"hi"}]}'
```

In Konnect analytics, tokens for `claude-main` and `claude-fast` are attributed to `eng-dev-1`, and
the data plane logs show one entry per request (`docker compose -f part-01/docker-compose.yaml logs -f kong-dp`).

## Step 4: Developer keys and teams

There's no IdP in the POC, so each developer has a gateway key (an AI Consumer), grouped by team.
Analytics attribute every request to a developer and team, and policies target groups. Moving to SSO
replaces the auth strategy; the groups stay.

| Consumer | Group | Key |
|---|---|---|
| `eng-dev-1`, `eng-dev-2` | `engineering` | `ENG_DEV_1_KEY`, `ENG_DEV_2_KEY` |
| `fin-dev-1` | `finance` | `FIN_DEV_1_KEY` |
| none | `github-admins` | Owns GitHub tools nobody has approved (step 5) |

To act as finance, set `KONG_GATEWAY_KEY=${FIN_DEV_1_KEY}`, re-source `.env`, and restart Claude Code.

### Verify

```bash
# No key -> 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/messages \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-fast","max_tokens":20,"messages":[{"role":"user","content":"hi"}]}'
```

## Step 5: GitHub MCP

GitHub's remote MCP server is fronted as a **passthrough-listener** on `/mcp/github`: traffic is
proxied unchanged, and Kong adds auth, per-tool ACLs and analytics (no payload logging). Each request
carries the developer's gateway key (`x-api-key`, checked and stripped) and their own GitHub token
(`Authorization`, forwarded, so GitHub's audit log shows the real person).

Tool access is an **allow list**:

| Group | Tools |
|---|---|
| `engineering` | 12 read-and-comment tools: `get_me`, `get_file_contents`, `search_code`, `list_branches`, `list_commits`, `get_commit`, `issue_read`, `list_issues`, `search_issues`, `add_issue_comment`, `pull_request_read`, `list_pull_requests` |
| `finance` | none |
| `github-admins` | everything, including merge and delete |

Tools GitHub adds later stay admin-only until approved. Branch writes are ready in the file but
commented out until GitHub rulesets protect `main`, because ACLs can't limit which branch.

**Token:** each developer creates a GitHub fine-grained token with access to only the demo repo.
Give it Contents, Issues and Pull requests read/write, and a short expiry. It can merge on
purpose, so a refusal comes from the gateway, not GitHub. Put it in `.env` as `GITHUB_PAT`.

**Claude Code:** `make -C shared claude PART=1`, then `/mcp` lists the tools. Try "read the Kong/kong
README", "comment on issue #N" (works) and "merge PR #N" (no tool for it).

### Verify

```bash
mcp() { curl -s -X POST http://localhost:8000/mcp/github -H "x-api-key: $1" \
  -H "Authorization: Bearer $GITHUB_PAT" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -d "$2"; }
LIST='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

mcp "$ENG_DEV_1_KEY" "$LIST" | grep -o '"name":"[a-z_]*"' | sort -u   # the 12 approved tools
mcp "$FIN_DEV_1_KEY" "$LIST" | grep -o '"name":"[a-z_]*"' | wc -l     # 0
mcp "$ENG_DEV_1_KEY" '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"merge_pull_request","arguments":{"owner":"octocat","repo":"Hello-World","pullNumber":1}}}'   # denied by Kong
```

## Step 6: PII sanitizer

Each prompt goes to the PII service before Anthropic. Detected values become `PLACEHOLDERn` and the
redacted prompt is forwarded.

| Setting | Value | Why |
|---|---|---|
| `stop_on_error` | `true` | **Fail closed:** PII service down → request blocked |
| `skip_logging_sanitized_items` | `true` | Log counts, never the matched values |
| `sanitization_mode` / `recover_redacted` | `INPUT` / `false` | Redact prompts and forward; don't restore values |
| `anonymize` | SSN, card, bank, email, phone, national ID, licence, passport, medical, credentials | Identifiers and secrets |

Names, URLs, domains, IPs and dates are left out: they match all over source code, garble prompts
and add latency. The gap is customer names.

### Verify

```bash
# Reply shows placeholders because Anthropic never saw the values
curl -s http://localhost:8000/v1/messages "${H[@]}" \
  -d '{"model":"claude-fast","max_tokens":60,"thinking":{"type":"disabled"},"messages":[{"role":"user","content":"Echo this text back verbatim, nothing else: Contact jane.doe@example.com or 212-555-0147."}]}'

# Fail closed: stop the PII service, re-run the request -> HTTP 500 "failed to sanitize request" after ~10 s
docker compose -f part-01/docker-compose.yaml stop ai-pii-service
# ...re-run the request above...
docker compose -f part-01/docker-compose.yaml start ai-pii-service
```

After a restart, some requests can fail for up to 30 s while Kong's cached DNS miss expires.

## Step 7: Team token limits

`ai-rate-limiting-advanced` counts prompt + completion tokens. Every matching entry applies, so an
engineer is stopped by whichever runs out first.

| Header | Applies to | Allowance |
|---|---|---|
| `policy-1` | `engineering` team (shared) | 1,000,000 / day |
| `policy-2` | `finance` team | 1,000 / hour (demo value) |
| `policy-3` | each developer, any group | 1,000,000 / day ceiling, so nobody is unlimited |
| `policy-4` | each engineer | 250,000 / day |

Over the limit: **HTTP 429** with `X-AI-RateLimit-Retry-After`. Tokens are counted from the
response, so the request that crosses the limit completes and the next one is refused. Counters live
in the data plane's memory (`strategy: local`). Several replicas need Redis. Counters are kept per
model, so each allowance applies per model ([gaps](../WRITEUP.md#gaps-and-the-path-to-production)).

### Verify

```bash
# Finance: 200 ... then 429
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "request $i: %{http_code}\n" http://localhost:8000/v1/messages \
    -H "x-api-key: $FIN_DEV_1_KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
    -d '{"model":"claude-main","max_tokens":300,"messages":[{"role":"user","content":"Write 200 words about car insurance."}]}'
done
```

## Test suite

Every check above in one run (a few hundred tokens). `--fail-closed` also stops and restarts the
PII service:

```bash
python3 part-01/test_gateway.py [--fail-closed]
```

Expect all `PASS`, plus three `XFAIL` for the known issues below. See the
[root README](../README.md#tests) for the check list.

## Known issues (AI Gateway 2.2.0)

- The sanitizer round-trips Anthropic requests through an internal format and breaks three cases:
  adaptive thinking on `claude-fast` (400), an image in a tool result (500), and an image-only
  message (500). Workarounds: chat on `claude-main`, and avoid image reads while the sanitizer is on.
  Scanning only the latest message is **not** a workaround, because Claude Code resends the full
  history every turn.
- An unlisted model gets 503, so Claude Code retries it.
- PII hit counts are produced by the gateway but not shown in Konnect analytics. They'd go to a SIEM
  through a logging policy.

Details and how each was found: [WRITEUP.md](../WRITEUP.md#problems-hit-along-the-way).

## Evidence

Screenshot of Konnect analytics for poc-part-01 (requests by model, provider and status; tokens by developer): [`evidence/`](evidence/).

## References

- [Kong AI Gateway](https://developer.konghq.com/ai-gateway/) · [AI MCP Server](https://developer.konghq.com/ai-gateway/entities/ai-mcp-server/) · [Data plane certificates](https://developer.konghq.com/ai-gateway/entities/ai-data-plane-certificate/)
- [kongctl](https://developer.konghq.com/kongctl/) (`kongctl explain <resource> --extended` shows the schema)
- [GitHub remote MCP server](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md)
