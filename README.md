# rc-mcp-server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes the [RevenueCat REST API](https://www.revenuecat.com/docs/api-v1) as tools for AI agents.

**Drop-in billing access for any MCP-compatible agent.** Connect Claude Desktop, Claude Code, or any MCP client — your agent can now check entitlements, grant promotional access, and read subscriber data without custom integration code.

---

## Tools

| Tool | What it does |
|------|-------------|
| `rc_get_subscriber` | Fetch full subscriber info: entitlements, subscriptions, metadata |
| `rc_check_entitlement` | Check if a subscriber has a given entitlement active (with expiry + grace period) |
| `rc_grant_entitlement` | Grant a promotional entitlement (daily → lifetime) |
| `rc_revoke_entitlement` | Revoke promotional entitlements |
| `rc_get_offerings` | Fetch available offerings and packages |
| `rc_set_attributes` | Set subscriber attributes (custom metadata) |
| `rc_delete_subscriber` | Delete a subscriber (GDPR/CCPA, requires `confirm: true`) |

---

## Quick Start

### Install

```bash
pip install rc-mcp-server
# or
uv tool install rc-mcp-server
```

### Configure

Set your RevenueCat API key:

```bash
export REVENUECAT_API_KEY=sk_...
```

### Run

```bash
rc-mcp-server
```

The server uses **stdio transport** — it's designed to be launched by an MCP client.

---

## Claude Desktop Integration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "revenuecat": {
      "command": "rc-mcp-server",
      "env": {
        "REVENUECAT_API_KEY": "sk_..."
      }
    }
  }
}
```

Then ask Claude: *"Check if user abc123 has the premium entitlement"* — and it'll call `rc_check_entitlement` directly.

---

## Claude Code Integration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "revenuecat": {
      "command": "rc-mcp-server",
      "env": {
        "REVENUECAT_API_KEY": "sk_..."
      }
    }
  }
}
```

---

## Example Prompts

Once connected, your agent can handle requests like:

- *"Does user `$RCAnonymousID:abc123` have the `premium` entitlement?"*
- *"Grant a 30-day trial of `pro` to user `user_456`"*
- *"What offerings are available for `user_789`?"*
- *"Tag user `user_123` with cohort=`beta` and source=`web`"*
- *"Delete subscriber `user_999` — GDPR request confirmed"*

---

## API Key Permissions

Use your RevenueCat **secret key** (starts with `sk_`). The public app key won't work for most operations.

Find yours at: RevenueCat Dashboard → Project → API Keys → Secret keys

---

## Development

```bash
# Install with dev deps
uv sync --dev

# Run tests
uv run pytest

# Lint
uv run ruff check .
uv run ruff format .
```

---

## What This Is For

Standard RevenueCat SDKs (iOS, Android, React Native) handle purchase validation client-side. This server is for **backend and agent use cases**:

- An AI agent checking entitlements before performing a privileged action
- A support agent granting a comp subscription directly from a chat interface
- An automated churn flow revoking promotional access after a grace period
- A billing agent handling GDPR deletion requests without touching the dashboard

If you're building agent-native apps on RevenueCat, this is the missing bridge.

---

## Related Projects

- [churnwall](https://github.com/zarpa-cat/churnwall) — Programmatic subscriber retention engine
- [rc-entitlement-gate](https://github.com/zarpa-cat/rc-entitlement-gate) — Lightweight entitlement checks with caching
- [rc-agent-starter](https://github.com/zarpa-cat/rc-agent-starter) — Bootstrap a full RC project via API

---

MIT License · Built by [Zarpa](https://zarpa-cat.github.io)
