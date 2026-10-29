# Part 2: Production shape (Terraform control plane, Kong Operator data plane on kind)

The same gateway as Part 1, rebuilt the way a platform team would run it:

- **Terraform** (`Kong/konnect` provider 3.27) owns the Konnect AI Gateway and all its configuration.
- **Helm** installs Kong Operator and this repo's `poc-ai-gateway` chart. The chart asks the operator
  for a data plane attached to the Terraform gateway, and runs the PII service.
- **kind** stands in for the customer's EKS cluster.

The gateway serves the same address as Part 1 (`http://localhost:8000`), so Claude Code,
`shared/claude/mcp.json` and the test suite work unchanged. Run only one part at a time: both use
port 8000.

## Who owns what

| Layer | Defined in | Managed by |
|---|---|---|
| Gateway + all config (provider, models, auth, consumers, MCP, policies) | `terraform/` | Terraform |
| Kong Operator + CRDs | `kong/kong-operator` chart, `helm/operator-values.yaml` | Helm |
| Gateway reference (`KonnectAIGateway`, `source: Mirror`) | `helm/poc-ai-gateway` | Operator: read-only, never edits the gateway |
| Data plane (`AIGatewayDataPlane`) | `helm/poc-ai-gateway` | Operator: creates and registers the mTLS cert, runs `kong-ai-gateway:2.2.0` |
| PII service | `helm/poc-ai-gateway` | Kubernetes |
| Cluster (NodePort 30080 → `localhost:8000`) | `kind-config.yaml` | kind |

Terraform and the cluster meet at one value, `gateway_id`, which is passed to `helm install`.
**Mirror** rather than Origin, so the control plane has only one owner. Deleting the cluster leaves
the gateway in Konnect.

### From Part 1

| Part 1 | Part 2 |
|---|---|
| Gateway created in the UI | `terraform/gateway.tf`: pinned to 2.2, auto-upgrade off |
| `config/anthropic-provider.yaml`, `models.yaml` | `terraform/provider-models.tf` |
| `config/auth.yaml`, `consumers.yaml` | `terraform/auth-consumers.tf` |
| `config/github-mcp.yaml` | `terraform/github-mcp.tf` (tool list also an output, for the tests) |
| `config/pii-sanitizer.yaml`, `token-limits.yaml` | `terraform/policies.tf` |
| `docker-compose.yaml` data plane + hand-made certificate | `templates/konnect.yaml`, `dataplane.yaml`: the operator fills in the hybrid settings and the cert |
| `docker-compose.yaml` PII service | `templates/pii-service.yaml` |

## Prerequisites

- Docker, [kind](https://kind.sigs.k8s.io/), `kubectl`, Helm 3, Terraform ≥ 1.5, GNU Make, Python 3
- Claude Code CLI, a Konnect personal access token, and an Anthropic API key
- ~4 GB disk and ~4 GB free memory

```bash
cp part-02/.env.example part-02/.env   # KONNECT_TOKEN, ANTHROPIC_PROVIDER_API_KEY, three dev keys, GITHUB_PAT
```

The variables are the same as Part 1, plus derived `TF_VAR_*` lines (don't edit them). There are no
gateway IDs or hostnames to copy: Terraform outputs the ID and the operator finds the endpoints.

Each step below names its `make -C part-02 <target>`. `make -C part-02 help` lists the targets, and
`-n` prints a target's commands without running them. `make -C part-02 up` runs steps 1–3 (cluster first).

> Terraform state holds the provider key and developer keys. It's local and gitignored here. In
> production, use an encrypted remote backend (e.g. S3 + KMS) and a system account token in CI.

## Step 0: Stop Part 1

```bash
docker compose -f part-01/docker-compose.yaml down
```

## Step 1: Gateway and configuration (`make -C part-02 tf-apply`)

```bash
terraform -chdir=part-02/terraform init
terraform -chdir=part-02/terraform apply    # ~20 resources
```

### Verify

```bash
terraform -chdir=part-02/terraform plan     # "No changes"
terraform -chdir=part-02/terraform output   # gateway_id, endpoints, engineering_tools
```

Konnect → **AI Gateway → poc-part-02** shows the models, consumers, MCP server and policies, and no
nodes yet.

## Step 2: Cluster and Kong Operator (`make -C part-02 cluster operator`)

```bash
kind create cluster --config part-02/kind-config.yaml
helm repo add kong https://charts.konghq.com --force-update
helm upgrade --install kong-operator kong/kong-operator -n kong-system --create-namespace \
  --version 1.5.0-rapid.2.0 -f part-02/helm/operator-values.yaml --wait
```

`1.5.0-rapid.2.0` is the first chart version with the AI Gateway controllers. `operator-values.yaml`
turns on the Konnect and AI Gateway data plane controllers.

### Verify

```bash
kubectl -n kong-system get pods     # kong-operator Running
```

## Step 3: Data plane and PII service (`make -C part-02 konnect-secret gateway`)

```bash
kubectl create namespace kong
kubectl -n kong create secret generic konnect-token --from-literal=token="$KONNECT_TOKEN"
kubectl -n kong label secret konnect-token konghq.com/credential=konnect konghq.com/secret=true

helm upgrade --install poc-ai-gateway part-02/helm/poc-ai-gateway -n kong \
  --set gatewayId="$(terraform -chdir=part-02/terraform output -raw gateway_id)"
```

The token Secret is created outside the chart, so it never appears in values or the Helm release.
The operator only watches Secrets that carry those labels. The first install pulls the 2.5 GB PII
image. Until that service is ready, model requests fail closed.

### Verify

```bash
make -C part-02 status
#   konnectaigateway ai-gateway PROGRAMMED True; aigatewaydataplane ai-gateway-dp ready
#   pods ai-gateway-dp-... and ai-pii-service-... 1/1 Running
curl -i http://localhost:8000   # 404 "no Route matched" from Kong
```

Konnect → **poc-part-02 → Data plane nodes** shows the pod connected at 2.2.0. That proves the
operator's certificate, the endpoints and the versions all match.

**Troubleshooting**
- `KonnectAIGateway` not programmed: run `kubectl -n kong describe konnectaigateway ai-gateway`.
  It's usually the Secret (labels, or the key must be `token`) or a wrong `gatewayId`.
- No data plane pod: `kubectl -n kong describe aigatewaydataplane ai-gateway-dp`.
- `401` in data plane logs: Konnect rejected the certificate.
- Pod `OOMKilled` seconds after start: too many nginx workers. The chart pins
  `dataPlane.workerProcesses: 2`. Check with `kubectl -n kong logs <pod> | grep -c "start worker process"`.
- `localhost:8000` refused: Part 1 still holds the port, or the cluster was made without `kind-config.yaml`.

## Step 4: Claude Code through the cluster

Use the same commands as Part 1 steps 3 and 5, with `PART=2`:

```bash
make -C shared claude PART=2         # interactive; /mcp shows the GitHub tools
make -C shared claude-smoke PART=2   # model, GitHub MCP read, PII redaction
```

Konnect analytics for **poc-part-02** shows tokens per model from `eng-dev-1` and the MCP calls.
Data plane logs: `kubectl -n kong logs -f -l gateway-operator.konghq.com/managed-by-name=ai-gateway-dp`.

## Step 5: Test suite (`make -C part-02 test` or `test-fail-closed`)

```bash
python3 part-02/test_gateway.py [--fail-closed]
```

The checks are the same as Part 1's (`shared/gateway_suite.py`), with three differences: settings
come from `part-02/.env`, the expected tools come from `terraform output engineering_tools`, and
`--fail-closed` scales `ai-pii-service` to 0 and back. Expect all `PASS` plus three `XFAIL`.

Part 1's 30 s DNS delay after a PII restart doesn't happen here: the Service name keeps resolving,
so with no PII pods the error is `connection refused`. The suite's 30 s wait is only needed on Docker.

## Step 6: Usage dashboard (`make -C shared dashboard`)

`shared/dashboard/usage-dashboard.yaml` is one Konnect dashboard over both POC gateways, applied with
kongctl because the Terraform provider has no dashboard resource. It shows:

- tokens by team over time, by developer and by model
- enforcement as status codes by team and over time: 429 token limit, 503 unlisted model, 500 PII
  failed closed
- GitHub MCP tool calls by team, and the top MCP users

```bash
make -C shared dashboard-diff   # preview
make -C shared dashboard        # apply
```

It needs `AI_GATEWAY_ID` in `part-01/.env`, a Terraform state with `gateway_id`, and `KONNECT_TOKEN`
in `part-02/.env`. The file holds no IDs, so pointing it at other gateways only means changing the
two IDs the Makefile passes. No cost tiles: Konnect shows $0 for these models.

## Step 7: Teardown

```bash
make -C part-02 down         # delete the cluster; the gateway stays in Konnect
make -C part-02 tf-destroy   # delete the gateway and its config
```

Bring it back with `make -C part-02 cluster operator konnect-secret gateway` after `down`, or `make -C part-02 up` after `tf-destroy`.

## Production next steps

- **EKS:** a LoadBalancer/NLB Service, TLS on the proxy, and egress limited to Anthropic, GitHub and
  Konnect.
- **Workers = CPU limit:** otherwise memory changes with the instance type.
- **Redis for token counters:** local counters reset on every restart or rollout, and each replica
  counts separately.
- **PII service HA:** replicas and a PodDisruptionBudget. With fail closed, its uptime is the
  gateway's uptime.
- **GitOps:** the chart as an Argo CD Application; Terraform in CI with remote state.
- **Upgrades:** change `min_runtime_version` in `gateway.tf` and `dataPlane.image` in `values.yaml`
  together. Helm doesn't upgrade CRDs.

## Evidence

Screenshots of Konnect (connected data plane, analytics): [`evidence/`](evidence/).

## References

- [`Kong/konnect` Terraform provider](https://registry.terraform.io/providers/Kong/konnect/latest)
- [Kong AI Gateway with Kong Operator](https://developer.konghq.com/operator/konnect/ai-gateway/) · [Install](https://developer.konghq.com/operator/get-started/ai-gateway/install/) · [Deploy](https://developer.konghq.com/operator/get-started/ai-gateway/deploy/)
- [Kong Operator source](https://github.com/Kong/kong-operator) (tag `v2.4.0-rapid.2.0`)
- [kind port mappings](https://kind.sigs.k8s.io/docs/user/configuration/#extra-port-mappings)
