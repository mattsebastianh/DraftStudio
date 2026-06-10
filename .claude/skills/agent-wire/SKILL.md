---
description: Define the inter-agent communication contract between two agents. Creates a wire definition file and updates both agents' tool definitions.
user-invocable: true
---

# Skill: /agent-wire

## Purpose
Formally define the handoff protocol between two agents.
A "wire" is the contract that describes how Agent A triggers Agent B and what data flows between them.

## Steps

1. **Identify the agents**
   If not provided, ask:
   - "Which agent is the SENDER (upstream)?"
   - "Which agent is the RECEIVER (downstream)?"
   - "What TRIGGERS the handoff?"

2. **Read both agents**
   - Read `agents/<SenderName>/agent.md`
   - Read `agents/<ReceiverName>/agent.md`
   - Read `agents/<SenderName>/tools.json`
   - Read `agents/<ReceiverName>/tools.json`

3. **Write the wire definition**
   Create `wires/<SenderName>_to_<ReceiverName>.yaml`:

   ```yaml
   wire:
     id: <sender>_to_<receiver>
     version: "1.0"
     created: <YYYY-MM-DD>

   sender:
     agent: <SenderName>
     trigger_condition: "<Human-readable description of when this fires>"
     trigger_event: "<event_name>"

   receiver:
     agent: <ReceiverName>
     entry_point: "<tool or function name the receiver exposes>"

   message_schema:
     type: object
     required: []
     properties:
       field_name:
         type: string
         description: "What this field contains"
         example: "example value"

   failure_handling:
     on_timeout:
       action: retry
       max_retries: 3
       backoff_seconds: 5
     on_error:
       action: escalate
       escalate_to: "<AgentName or human>"
     on_max_retries_exceeded:
       action: alert_human
       message: "Wire <sender>_to_<receiver> failed after 3 retries"

   metadata:
     description: "<One-sentence description of what this wire transfers>"
     data_sensitivity: [public | internal | confidential]
   ```

4. **Update sender's tools.json**
   Add a `send_to_<ReceiverName>` tool entry that matches the message schema.

5. **Update receiver's tools.json**
   Verify it has a matching tool/endpoint that accepts the schema.

6. **Update `agents/registry.yaml`**
   Add wire reference to both agents:
   ```yaml
   wires:
     outgoing:
       - wires/<SenderName>_to_<ReceiverName>.yaml
   ```

7. **Confirm**
   Report the wire file and both updated agent tool files.
