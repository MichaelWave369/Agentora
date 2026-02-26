# Contributing

## Add an agent template
1. Add YAML in `agents/marketplace/` with required fields (`name`, `version`, `description`, `tags`, `required_tools`, `default_models`, `mode`, `agents`, `edges`).
2. Add/update tests in `server/tests/test_marketplace.py`.

## Add a tool plugin
1. Implement tool in `server/app/services/tools/builtins.py`.
2. Register in `server/app/services/tools/registry.py`.
3. Add permission and tests.

## Share via CoEvo
- Export template YAML through `/api/templates/export/{id}`.
- Publish externally (manual process; no telemetry/upload in Agentora by default).
