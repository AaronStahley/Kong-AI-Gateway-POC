variable "konnect_personal_access_token" {
  description = "Konnect Personal Access Token (Org Admin or equivalent). Export as TF_VAR_konnect_personal_access_token rather than hardcoding it here."
  type        = string
  sensitive   = true
}

variable "konnect_server_url" {
  description = "Konnect region API base URL for your org, e.g. https://us.api.konghq.com, https://eu.api.konghq.com, https://au.api.konghq.com."
  type        = string
  default     = "https://us.api.konghq.com"
}

variable "control_plane_name" {
  description = "Name for the Konnect Control Plane this exercise creates."
  type        = string
  default     = "ps-fe-exercise"
}
