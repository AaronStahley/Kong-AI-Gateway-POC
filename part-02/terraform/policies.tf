# Policies attached to both models (config = the Kong plugin config, as JSON). Every field is listed,
# defaults included, because Konnect returns them filled in and `plan` would otherwise never be clean.

# PII and secret redaction on prompts, via the ai-pii-service from the Helm chart.
resource "konnect_ai_gateway_policy" "pii_sanitizer" {
  gateway_id   = konnect_ai_gateway.this.id
  name         = "pii-sanitizer"
  display_name = "PII sanitizer"
  type         = "ai-sanitizer"
  enabled      = true
  global       = false
  managed_by   = local.managed_by

  config = jsonencode({
    host              = "ai-pii-service" # the Kubernetes Service, in the data plane's namespace
    port              = 8080
    scheme            = "http"
    sanitization_mode = "INPUT"
    redact_type       = "placeholder"
    # Identifiers and secrets only: names, url, domain, ip and date match all over source code.
    anonymize = [
      "ssn",
      "creditcard",
      "bank",
      "email",
      "phone",
      "nationalid",
      "driverlicense",
      "passport",
      "medical",
      "credentials",
    ]
    block_if_detected            = false # redact and forward
    stop_on_error                = true  # fail closed if the PII service is down
    skip_logging_sanitized_items = true  # log counts, never the matched values
    recover_redacted             = false

    # Defaults, unchanged
    timeout                        = 10000 # a down PII service fails requests after this long
    keepalive_timeout              = 60000
    allow_all_conversation_history = true # Claude Code resends earlier turns, so scan them all
    continue_on_detection          = false
    rejection_mode                 = "none"
    custom_patterns                = null
    proxy_config                   = null
  })
}

# Token allowances (prompt + completion). Over the limit: HTTP 429.
# Every matching entry is enforced. Headers number entries by position, so append new ones:
# policy-1 engineering team, 2 finance team, 3 per-developer ceiling, 4 per engineer.
# Demo values: finance's is tiny so the 429 is easy to show. Counters are per pod (strategy local);
# several replicas need redis.
locals {
  token_limit_entries = [
    { # engineering team: 1,000,000 tokens per day, shared
      match       = [{ type = "consumer_group", values = [konnect_ai_gateway_consumer_group.this["engineering"].name] }]
      window_type = "sliding"
      limits      = [{ limit = 1000000, window_size = 86400 }]
    },
    { # finance team: 1,000 tokens per hour, a demo value that trips after a few small requests
      match       = [{ type = "consumer_group", values = [konnect_ai_gateway_consumer_group.this["finance"].name] }]
      window_type = "sliding"
      limits      = [{ limit = 1000, window_size = 3600 }]
    },
    { # ceiling per developer (even outside a group); keep >= the largest group allowance.
      # partition_by: one counter per consumer; without it, one bucket for everyone
      match       = [{ type = "consumer", partition_by = true }]
      window_type = "sliding"
      limits      = [{ limit = 1000000, window_size = 86400 }]
    },
    { # each engineer's share of the engineering allowance: 250,000 tokens per day
      # (AND: any consumer in that group, each with its own counter)
      match = [
        { type = "consumer_group", values = [konnect_ai_gateway_consumer_group.this["engineering"].name] },
        { type = "consumer", partition_by = true },
      ]
      window_type = "sliding"
      limits      = [{ limit = 250000, window_size = 86400 }]
    },
  ]

  # The same entries with Konnect's defaults filled in (see the top of this file).
  token_limit_policies = [for entry in local.token_limit_entries : merge(
    { id = null, timezone = null },
    entry,
    {
      match = [for m in entry.match : merge({ key = null, partition_by = false, values = null }, m)]
      limits = [for l in entry.limits : merge(
        { tokens_count_strategy = "total_tokens", period = null, month_day = null, week_start_day = null }, l
      )]
    },
  )]
}

resource "konnect_ai_gateway_policy" "token_limits" {
  gateway_id   = konnect_ai_gateway.this.id
  name         = "token-limits"
  display_name = "Team token limits"
  type         = "ai-rate-limiting-advanced"
  enabled      = true
  global       = false
  managed_by   = local.managed_by

  config = jsonencode({
    strategy              = "local"
    tokens_count_strategy = "total_tokens"
    policies              = local.token_limit_policies

    # Defaults, unchanged
    window_type                    = "sliding"
    identifier                     = "consumer"
    error_code                     = 429
    error_message                  = "AI token rate limit exceeded for provider(s): "
    error_hide_providers           = false
    hide_client_headers            = false
    disable_penalty                = false
    retry_after_jitter_max         = 0
    dictionary_name                = "kong_rate_limiting_counters"
    decrease_by_fractions_in_redis = false
    custom_cost_count_function     = null
    request_prompt_count_function  = null
    header_name                    = null
    namespace                      = null
    path                           = null
    sync_rate                      = null
    # Only used with strategy = "redis" (production with several replicas)
    redis = {
      host                     = "127.0.0.1"
      port                     = 6379
      database                 = 0
      username                 = null
      password                 = null
      ssl                      = false
      ssl_verify               = true
      server_name              = null
      timeout                  = 2000
      connect_timeout          = 2000
      read_timeout             = 2000
      send_timeout             = 2000
      keepalive_pool_size      = 256
      keepalive_backlog        = null
      connection_is_proxied    = false
      cloud_authentication     = null
      cluster_addresses        = null
      cluster_nodes            = null
      cluster_max_redirections = 5
      sentinel_addresses       = null
      sentinel_master          = null
      sentinel_nodes           = null
      sentinel_password        = null
      sentinel_role            = null
      sentinel_username        = null
    }
  })
}
