# Operator Mode

Operator Mode executes workflows with visibility and control.

## Core controls
- Start runs from workflow templates.
- Pause/resume/advance runs.
- Retry step / skip step for recoverable failures.

## Visibility surfaces
- Pending approvals and action history.
- Operator run status and step details.
- Trace timeline with failure reasons.
- Artifacts/results generated per step.

## Safety behavior
- Approval policy defaults to `ask_once`.
- Path/domain/app allowlists are enforced for actions.
- Unsafe or unavailable capabilities fail with explicit messages.
