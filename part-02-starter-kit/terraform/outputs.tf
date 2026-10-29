output "control_plane_id" {
  description = "Control plane UUID — needed for any additional resources you add, and useful when reading Konnect Manager."
  value       = konnect_gateway_control_plane.this.id
}

# The provider returns URLs (https://<host>); Kong's cluster_* settings need <host>:<port>.
output "control_plane_endpoint" {
  description = "Config-plane endpoint the data plane connects to (cluster_control_plane in Kong Gateway env vars / Helm values)."
  value       = "${trimprefix(konnect_gateway_control_plane.this.config.control_plane_endpoint, "https://")}:443"
}

output "telemetry_endpoint" {
  description = "Telemetry endpoint the data plane reports to (cluster_telemetry_endpoint in Kong Gateway env vars / Helm values)."
  value       = "${trimprefix(konnect_gateway_control_plane.this.config.telemetry_endpoint, "https://")}:443"
}
