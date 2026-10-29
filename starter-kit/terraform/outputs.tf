output "control_plane_id" {
  description = "Control plane UUID — needed for any additional resources you add, and useful when reading Konnect Manager."
  value       = konnect_gateway_control_plane.this.id
}

output "control_plane_endpoint" {
  description = "Config-plane endpoint the data plane connects to (cluster_control_plane in Kong Gateway env vars / Helm values)."
  value       = konnect_gateway_control_plane.this.config.control_plane_endpoint
}

output "telemetry_endpoint" {
  description = "Telemetry endpoint the data plane reports to (cluster_telemetry_endpoint in Kong Gateway env vars / Helm values)."
  value       = konnect_gateway_control_plane.this.config.telemetry_endpoint
}
