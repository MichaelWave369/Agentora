# Operator Mode (v1.0.0)

Operator Mode is Agentora’s controlled workflow automation plane.

## Core controls
- Start operator runs from workflows.
- Pause / resume / advance execution.
- Retry / skip step for recoverable failures.

## Visibility
- Pending approvals and action history.
- Operator run status and step outcomes.
- Replay via workflow history.

## Safety behavior
- Approval policy defaults to `ask_once`.
- Path/domain/app guardrails are enforced.
- Worker unavailability falls back to local execution when allowed.
