# RAISEDECK — Architecture

> Build and maintain an investor-update + data-room manifest from a metrics YAML, rendering monthly MRR/burn/runway updates with consistent KPIs.

```
input ──▶ collect ──▶ rules/analyzers ──▶ score ──▶ findings ──▶ table · json
                              │                          │
                         (this repo)                 MCP tool (agents)
```

- **collect** normalizes the target (file/dir/API) into records.
- **rules/analyzers** apply the heuristics shipped in `raisedeck/core.py`.
- **score** ranks by severity.
- **MCP server** (`raisedeck mcp`) exposes `scan` for Cognis.Studio agents.

Extend by adding a rule + a test + a `demos/NN-*/SCENARIO.md`. See [CONTRIBUTING.md](../CONTRIBUTING.md).
