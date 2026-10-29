# Part 2: starter kit (planted bug)

The brief's starter kit (classic control plane + `kong/kong` data plane chart), run as provided to
reproduce, diagnose and fix the planted bug. [`../starter-kit/`](../starter-kit/) is the original,
untouched; this folder is the working copy, so `diff starter-kit/terraform/outputs.tf part-02-starter-kit/terraform/outputs.tf` shows the fix.

Why a separate folder: Part 2 ([`../part-02/`](../part-02/README.md)) is built on AI Gateway 2.2 and
Kong Operator, as agreed at kickoff, and never runs the kit's control plane or chart, so it never
hit the bug. The kit's AI Proxy / AI MCP Proxy TODOs are not built here: that config is delivered
as AI Gateway 2.2 entities in [`../part-02/terraform/`](../part-02/terraform/).

## The bug

The kit passed Terraform's endpoint outputs (`https://…` URLs) straight into Kong's
`cluster_control_plane` / `cluster_telemetry_endpoint`, which need `host:port`, so the data plane
crash-looped. Fixed in [`terraform/outputs.tf`](terraform/outputs.tf). Investigation:
[WRITEUP.md](../WRITEUP.md#planted-bug-what-broke-and-how-i-found-it). Evidence:
[`evidence/`](evidence/).

## Run it

The kit's README steps, on the Part 2 kind cluster (`make -C part-02 cluster`) in a separate
`starter-kit` namespace. I watched pods and logs with k9s (the screenshots in `evidence/`);
the `kubectl` commands below show the same thing.

```bash
cd part-02-starter-kit
export TF_VAR_konnect_personal_access_token=<Konnect token>
KONNECT_TOKEN=$TF_VAR_konnect_personal_access_token

# 1. Control plane
terraform -chdir=terraform init
terraform -chdir=terraform apply
CP_ID=$(terraform -chdir=terraform output -raw control_plane_id)

# 2. Cluster certificate, pinned on the control plane (same as Konnect Manager's
#    "Generate certificate"; files stay in certs/, which is gitignored)
openssl req -new -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:secp384r1 \
  -keyout certs/tls.key -out certs/tls.crt -days 1095 -subj "/CN=kong_clustering"
jq -n --rawfile cert certs/tls.crt '{cert: $cert}' | \
  curl -sS -X POST "https://us.api.konghq.com/v2/control-planes/$CP_ID/dp-client-certificates" \
  -H "Authorization: Bearer $KONNECT_TOKEN" -H "Content-Type: application/json" -d @-

# 3. Secret and data plane
kubectl create namespace starter-kit
kubectl -n starter-kit create secret generic kong-cluster-cert \
  --from-file=tls.crt=certs/tls.crt --from-file=tls.key=certs/tls.key
helm repo add kong https://charts.konghq.com && helm repo update
helm install kong-dp kong/kong -n starter-kit --version 3.4.1 -f helm/dp-values.yaml \
  --set env.cluster_control_plane="$(terraform -chdir=terraform output -raw control_plane_endpoint)" \
  --set env.cluster_telemetry_endpoint="$(terraform -chdir=terraform output -raw telemetry_endpoint)"

# 4. Check
kubectl -n starter-kit get pods
kubectl -n starter-kit logs deploy/kong-dp-kong --tail=30      # add --previous after a crash
kubectl -n starter-kit get deploy kong-dp-kong -o yaml | grep -A1 CLUSTER_
```

Then check Konnect Manager → `ps-fe-exercise` → Data plane nodes.

Differences from the kit's README, none of them part of the fix: namespace `starter-kit` instead of
`kong` (Part 2 uses `kong` on the same cluster), the certificate pinned through the Konnect API
instead of the Konnect Manager button, and the chart version pinned.

Clean up: `helm uninstall kong-dp -n starter-kit`, `kubectl delete namespace starter-kit`, and
`terraform -chdir=terraform destroy` to remove the control plane.
