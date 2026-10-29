# Starter kit

For Stage 2 of `candidate-brief.md`. Two pieces, meant to be used together:

- `terraform/` — declares the Konnect Control Plane (`konnect_gateway_control_plane`). You need
  to add the service/route and the two AI Gateway plugin resources (AI Proxy, AI MCP Proxy) to
  reproduce your Stage 1 config as code. See the TODOs in `main.tf`.
- `helm/dp-values.yaml` — Helm values for deploying a self-managed, hybrid-mode data plane into
  a local Kubernetes cluster (`kind`/`minikube`), connected to the Terraform-managed Control
  Plane above.

Typical order of operations: `terraform apply` first (so you have a Control Plane and its
`control_plane_id` / `control_plane_endpoint` / `telemetry_endpoint` outputs), generate a
cluster certificate for that Control Plane from Konnect Manager, create the `kong-cluster-cert`
secret in your cluster, then `helm install` using `dp-values.yaml` with the Terraform outputs
filled in.

Not everything here works out of the box — see Stage 2 in `candidate-brief.md`.
