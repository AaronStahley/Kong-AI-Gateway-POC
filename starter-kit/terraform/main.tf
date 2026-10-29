# Starter kit — intentionally incomplete. See candidate-brief.md Stage 2.
#
# This declares the Control Plane your Kubernetes data plane will connect to. It does NOT yet
# declare the AI Gateway plugin config you built by hand in Stage 1 (AI Proxy, AI MCP Proxy) —
# that's part of the exercise. Add a konnect_gateway_service, konnect_gateway_route, and the two
# plugin resources referencing this control plane's id.

resource "konnect_gateway_control_plane" "this" {
  name          = var.control_plane_name
  description   = "PS/FDE exercise — hybrid mode, Kubernetes data plane"
  cluster_type  = "CLUSTER_TYPE_CONTROL_PLANE"
  auth_type     = "pinned_client_certs"
}

# TODO (candidate): konnect_gateway_service — the upstream/target for your route(s).
# resource "konnect_gateway_service" "llm" {
#   control_plane_id = konnect_gateway_control_plane.this.id
#   name              = "llm-upstream"
#   host              = "..."
#   port              = 443
#   protocol          = "https"
# }

# TODO (candidate): konnect_gateway_route — what Claude Code / your MCP client actually hits.
# resource "konnect_gateway_route" "llm" {
#   control_plane_id = konnect_gateway_control_plane.this.id
#   name              = "llm-route"
#   paths             = ["/"]
#   service = {
#     id = konnect_gateway_service.llm.id
#   }
# }

# TODO (candidate): konnect_gateway_plugin_ai_proxy — reproduce your Stage 1 AI Proxy config here.
# See: https://registry.terraform.io/providers/Kong/konnect/latest/docs/resources/gateway_plugin_ai_proxy

# TODO (candidate): konnect_gateway_plugin_ai_mcp_proxy — reproduce your Stage 1 AI MCP Proxy config here.
# See: https://registry.terraform.io/providers/Kong/konnect/latest/docs/resources/gateway_plugin_ai_mcp_proxy
