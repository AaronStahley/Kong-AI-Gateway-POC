output "gateway_id" {
  description = "AI Gateway ID. The Helm chart's gatewayId: Kong Operator mirrors this gateway and attaches the data plane to it."
  value       = konnect_ai_gateway.this.id
}

output "configuration_endpoint" {
  description = "Cluster endpoint the data plane gets its configuration from (the operator reads it from Konnect; shown for troubleshooting)."
  value       = konnect_ai_gateway.this.endpoints.configuration
}

output "telemetry_endpoint" {
  description = "Cluster endpoint the data plane reports analytics to."
  value       = konnect_ai_gateway.this.endpoints.telemetry
}

output "engineering_tools" {
  description = "GitHub MCP tools engineering may use. part-02/test_gateway.py expects exactly these."
  value       = local.engineering_tools
}
