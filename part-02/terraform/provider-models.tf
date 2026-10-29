# Anthropic provider and the model allow-list.

# The key comes from a sensitive variable and is stored in Konnect, never in code or plan output.
resource "konnect_ai_gateway_model_provider" "anthropic" {
  gateway_id = konnect_ai_gateway.this.id

  anthropic = {
    name         = "anthropic"
    display_name = "Anthropic"
    managed_by   = local.managed_by
    config = {
      auth = {
        headers = [{
          name  = "x-api-key"
          value = var.anthropic_provider_api_key
        }]
      }
    }
  }
}

# Model allow-list: clients ask for an alias in the "model" field; anything else is rejected.
# Claude Code needs two: a main model and a fast one for background tasks.
locals {
  models = {
    claude-main = { display_name = "Claude (main)", target = "claude-sonnet-5-5" }
    claude-fast = { display_name = "Claude (fast/background)", target = "claude-haiku-5-5" }
  }
}

resource "konnect_ai_gateway_model" "this" {
  for_each   = local.models
  gateway_id = konnect_ai_gateway.this.id

  model = {
    name         = each.key
    display_name = each.value.display_name
    managed_by   = local.managed_by
    formats      = [{ type = "anthropic" }]
    capabilities = ["generate"]
    config = {
      route = {
        paths = ["/"]
        model = {
          body_param = "model"
          values     = [each.key]
        }
      }
    }
    access = {
      auth_strategies = [konnect_ai_gateway_auth_strategy.gateway_key.key_auth.name]
    }
    targets = [{
      name     = each.value.target
      provider = konnect_ai_gateway_model_provider.anthropic.anthropic.name
      config   = { anthropic = {} }
    }]
    # Konnect's read-back order, to keep `plan` clean (Kong runs policies by priority, not position).
    # If plan ever shows them swapped, swap these two lines.
    policies = [
      konnect_ai_gateway_policy.token_limits.name,
      konnect_ai_gateway_policy.pii_sanitizer.name,
    ]
  }
}
