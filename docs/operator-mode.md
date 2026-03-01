# Operator Mode (v1.0 RC)

Operator Mode is the control plane for workflow automation with safety and trace visibility.

## Primary controls
- Start run from workflow.
- Pause / resume / advance.
- Retry step / skip step for recoverable failures.

## Operator clarity goals
- Clear distinction between **pending approvals** and **executed steps**.
- Visible status transitions for failed/paused/completed states.
- Replay via workflow history and run inspection.

## Safety defaults
- Approval policy defaults to `ask_once`.
- Path/domain/app guardrails apply to actions.
- Worker unavailability falls back to local path when allowed, otherwise returns readable failure details.
