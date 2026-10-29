terraform {
  required_version = ">= 1.5.0"

  required_providers {
    konnect = {
      source  = "Kong/konnect"
      version = "~> 3.27"
    }
  }
}

provider "konnect" {
  personal_access_token = var.konnect_personal_access_token
  server_url            = var.konnect_server_url
}
