# Set from part-02/.env as TF_VAR_* (no .tfvars with secrets). State still holds them: local and
# gitignored here, an encrypted remote backend in production.

variable "konnect_personal_access_token" {
  description = "Konnect personal access token (a system account token in CI)."
  type        = string
  sensitive   = true
}

variable "konnect_server_url" {
  description = "Konnect region API base URL."
  type        = string
  default     = "https://us.api.konghq.com"
}

variable "gateway_name" {
  description = "Name of the Konnect AI Gateway. Immutable: changing it replaces the gateway."
  type        = string
  default     = "poc-part-02"
}

variable "anthropic_provider_api_key" {
  description = "The real Anthropic API key. Stored in Konnect; developers never see it."
  type        = string
  sensitive   = true
}

variable "developer_keys" {
  description = "Gateway key per developer (consumer name => key). Generate with `openssl rand -hex 32`; a new value replaces that developer's key."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for name in ["eng-dev-1", "eng-dev-2", "fin-dev-1"] : contains(keys(var.developer_keys), name)])
    error_message = "developer_keys needs a key for eng-dev-1, eng-dev-2 and fin-dev-1."
  }
}
