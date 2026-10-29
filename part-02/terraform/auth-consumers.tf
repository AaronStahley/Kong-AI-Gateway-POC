# Client authentication, teams and developers.

# Gateway key in x-api-key (where Claude Code sends ANTHROPIC_API_KEY). Stripped before forwarding;
# the provider's real Anthropic key is added upstream.
resource "konnect_ai_gateway_auth_strategy" "gateway_key" {
  gateway_id = konnect_ai_gateway.this.id

  key_auth = {
    name         = "gateway-key-auth"
    display_name = "Gateway key auth"
    managed_by   = local.managed_by
    config = {
      key_names        = ["x-api-key"]
      key_in_header    = true
      key_in_query     = false
      hide_credentials = true
    }
  }
}

# Teams and developers: one consumer and key per developer, standing in for the IdP (SSO later swaps
# the auth strategy; groups stay).
locals {
  consumer_groups = {
    engineering = "Engineering"
    finance     = "Finance"
    # Holds rights to destructive GitHub tools (see github-mcp.tf). Empty in the POC.
    github-admins = "GitHub admins"
  }

  # eng-dev-2 tells the shared team allowance apart from the per-engineer one.
  consumers = {
    eng-dev-1 = { display_name = "Engineering developer 1", group = "engineering" }
    eng-dev-2 = { display_name = "Engineering developer 2", group = "engineering" }
    fin-dev-1 = { display_name = "Finance developer 1", group = "finance" }
  }
}

resource "konnect_ai_gateway_consumer_group" "this" {
  for_each     = local.consumer_groups
  gateway_id   = konnect_ai_gateway.this.id
  name         = each.key
  display_name = each.value
  managed_by   = local.managed_by
}

resource "konnect_ai_gateway_consumer" "this" {
  for_each     = local.consumers
  gateway_id   = konnect_ai_gateway.this.id
  name         = each.key
  display_name = each.value.display_name
  type         = "api-key"
  managed_by   = local.managed_by
}

resource "konnect_ai_gateway_consumer_group_member" "this" {
  for_each          = local.consumers
  gateway_id        = konnect_ai_gateway.this.id
  consumer_group_id = konnect_ai_gateway_consumer_group.this[each.value.group].id
  consumer_id       = konnect_ai_gateway_consumer.this[each.key].id
}

# Keys from var.developer_keys. Konnect never returns them, but state holds them: protect it.
resource "konnect_ai_gateway_consumer_credential" "this" {
  for_each     = local.consumers
  gateway_id   = konnect_ai_gateway.this.id
  consumer_id  = konnect_ai_gateway_consumer.this[each.key].id
  name         = "${each.key}-key"
  display_name = "${each.key} key"
  type         = "api-key"
  api_key      = var.developer_keys[each.key]
  managed_by   = local.managed_by
}
