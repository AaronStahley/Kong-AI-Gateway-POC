# GitHub's remote MCP server in passthrough mode: Kong adds key auth, per-tool ACLs and analytics.
# x-api-key (gateway key) is checked and stripped; Authorization (developer's GitHub token) is forwarded.
# Allow list: engineering gets engineering_tools, finance none, github-admins (empty) everything else.

locals {
  # Tool names as GitHub's tools/list returns them.
  engineering_tools = [
    # Context
    "get_me",
    # Read code
    "get_file_contents",
    "search_code",
    "list_branches",
    "list_commits",
    "get_commit",
    # Issues: read and comment
    "issue_read",
    "list_issues",
    "search_issues",
    "add_issue_comment",
    # Branch writes: ACLs can't limit which branch, so enable only once GitHub rulesets protect main.
    # "create_branch",
    # "create_or_update_file",
    # "push_files",
    # "create_pull_request",
    # Pull requests: read
    "pull_request_read",
    "list_pull_requests",
  ]
}

resource "konnect_ai_gateway_mcp_server" "github" {
  gateway_id = konnect_ai_gateway.this.id

  passthrough_listener = {
    name         = "github"
    display_name = "GitHub"
    managed_by   = local.managed_by
    config = {
      url = "https://api.githubcopilot.com/mcp/"
      route = {
        paths      = ["/mcp/github"]
        strip_path = true
      }
      logging = {
        payloads = false
        audits   = true
      }
    }
    access = {
      consumer = {
        auth_strategies = [konnect_ai_gateway_auth_strategy.gateway_key.key_auth.name]
        # Default for unlisted tools (Part 1's `acls`; here `acls` is a server-level gate instead).
        default_tool_acls = {
          allow = [konnect_ai_gateway_consumer_group.this["github-admins"].name]
        }
      }
    }
    # A tool's ACL replaces the default (no merging), so each entry repeats github-admins.
    tools = [for tool in local.engineering_tools : {
      name = tool
      access = {
        acls = {
          allow = [
            konnect_ai_gateway_consumer_group.this["engineering"].name,
            konnect_ai_gateway_consumer_group.this["github-admins"].name,
          ]
        }
      }
    }]
  }
}
