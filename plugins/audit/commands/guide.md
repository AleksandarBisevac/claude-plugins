---
description: 'Ask the plugin about itself — what a config key does, how the plan gate grades, what the journal can prove — answered from its own docs with a citation for every claim, by the read-only guide agent.'
argument-hint: '<question about the audit plugin>'
allowed-tools: Agent
---

# /audit:guide — ask the plugin about itself

Spawn the plugin's guide agent (`Agent` tool, `subagent_type: "audit:guide"`) with the
user's question as the prompt, verbatim:

```
$ARGUMENTS
```

- **If the question above is empty**, do not spawn anything. Ask the user what they want to
  know about the plugin (one line), and mention the zero-token alternative: the panel's help
  drawer (`/audit:panel`) already carries every config key's description.
- **Relay the agent's answer as-is**, citations included. Do not answer from your own
  knowledge and do not strip the citations — a claim about what the gate does is only worth
  keeping if it names the doc line it came from.
- The agent is mechanically read-only (Read/Grep/Glob) and cheap (`model: haiku`); it never
  changes anything, so there is nothing to confirm with the user before spawning it.

The conversational half of the plugin's help lives here; the zero-token half is the panel's
help drawer. When the drawer answers the question, prefer pointing there — it costs nothing.
