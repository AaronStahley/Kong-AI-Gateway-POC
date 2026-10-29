# The AI Gateway control plane (hybrid: the data plane runs in the cluster, see part-02/helm).
# Pinned to 2.2 with auto-upgrade off: CP and DP must match, so 2.3 is a change here and in values.yaml.

locals {
  managed_by = { tool = "terraform" }
}

resource "konnect_ai_gateway" "this" {
  name                 = var.gateway_name
  display_name         = "POC Part 2"
  description          = "Kong AI Gateway POC, production shape: Terraform control plane, Kong Operator data plane."
  deployment_type      = "hybrid"
  min_runtime_version  = "2.2"
  runtime_auto_upgrade = false
}
