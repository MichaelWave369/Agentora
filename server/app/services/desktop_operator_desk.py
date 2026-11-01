"""Phi Operator Desk R3: standalone native local proposal review UI.

This module deliberately has no broker or execution imports. Reviewing is a
metadata-only R2 inbox transition, never a desktop action.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
from typing import Any

from app.services.desktop_inbox import ProposalError, ProposalInbox


class OperatorPolicy:
    """Exact application review policy, not an operating-system grant."""

    def __init__(self, apps: dict[str, frozenset[str]]):
        self.apps = apps

    @classmethod
    def load(cls, path: Path) -> "OperatorPolicy":
        path = Path(path).expanduser()
        if path.is_symlink():
            raise ProposalError("policy_symlink_forbidden")
        try:
            if not path.is_file() or path.stat().st_size > 16384:
                raise ProposalError("invalid_policy_file")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise ProposalError("invalid_policy_file") from None
        if (not isinstance(value, dict) or set(value) != {"version", "apps"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["apps"], dict) or len(value["apps"]) > 32):
            raise ProposalError("invalid_policy_schema")
        apps: dict[str, frozenset[str]] = {}
        for name, policy in value["apps"].items():
            if (not isinstance(name, str) or not name or len(name) > 80
                    or name != name.strip()
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
                    or not isinstance(policy, dict)
                    or set(policy) != {"observe", "click"}
                    or any(type(policy[k]) is not bool for k in ("observe", "click"))):
                raise ProposalError("invalid_policy_schema")
            apps[name] = frozenset(op for op in ("observe", "click") if policy[op])
        return cls(apps)

    def permits(self, app: str, operation: str) -> bool:
        return operation in self.apps.get(app, frozenset())


class OperatorDeskModel:
    """Headless controller for the GUI. It cannot issue any desktop actions."""

    def __init__(self, inbox: ProposalInbox, policy: OperatorPolicy):
        self.inbox = inbox
        self.policy = policy

    def get(self, item_id: str) -> dict[str, Any]:
        return self.inbox.get(item_id)

    def list(self, status: str = "pending") -> list[dict[str, Any]]:
        # In contrast to R2 list(), get() checks each payload against its digest.
        return [self.get(row["id"]) for row in self.inbox.list(status=status, limit=100)]

    def details(self, item_id: str) -> str:
        item = self.get(item_id)
        p = item["proposal"]
        allowed = self.policy.permits(p["app"], p["operation"])
        return (
            "PHI DESKTOP INTENT  |  NO EXECUTION\n\n"
            f"Status: {item['status']}\n"
            f"Review policy: {'ELIGIBLE FOR REVIEW' if allowed else 'POLICY DENIED'}\n"
            f"Application: {p['app']}\n"
            f"Operation: {p['operation']}\n"
            f"Reason: {p['reason']}\n"
            f"Target hint (untrusted): {p['target_hint'] or '(none)'}\n"
            f"Source label (untrusted): {p['source']}\n"
            f"Correlation: {p['correlation_id'] or '(none)'}\n\n"
            f"Proposal ID: {item['id']}\n"
            f"Digest (SHA256, not signed): {item['digest']}\n"
            f"Expiry (epoch): {item['expires_at']}\n\n"
            "Marking reviewed is not a permission grant. Only the separate\n"
            "R1 broker, with a fresh observation and independent local\n"
            "human confirmation, can perform a desktop click."
        )

    def review(self, item_id: str, shown_digest: str, decision: str) -> dict[str, Any]:
        item = self.get(item_id)
        if shown_digest != item["digest"]:
            raise ProposalError("proposal_changed_refresh_required")
        if item["status"] != "pending":
            raise ProposalError("proposal_stale_or_not_pending")
        if decision == "reviewed":
            p = item["proposal"]
            if not self.policy.permits(p["app"], p["operation"]):
                raise ProposalError("operation_policy_denied")
        elif decision != "rejected":
            raise ProposalError("invalid_decision")
        return self.inbox.review(item_id, shown_digest, decision)

    def handoff(self, item_id: str) -> str:
        item = self.get(item_id)
        p = item["proposal"]
        if not self.policy.permits(p["app"], p["operation"]):
            raise ProposalError("operation_policy_denied")
        return self.inbox.handoff(item_id)


def run_window(model: OperatorDeskModel) -> None:
    """Tkinter is imported only when an actual local GUI is requested."""
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk

    root = tk.Tk()
    root.title("Phi Operator Desk | Agentora")
    root.geometry("1000x680")
    root.minsize(760, 480)
    root.configure(bg="#101925")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Desk.Treeview", font=("Segoe UI", 10), rowheight=28,
                    background="#142131", fieldbackground="#142131",
                    foreground="#e3edf7")
    style.configure("Desk.Treeview.Heading", font=("Segoe UI", 10, "bold"),
                    background="#233447", foreground="#d9e9fa")
    style.map("Desk.Treeview", background=[("selected", "#245a76")])

    header = tk.Frame(root, bg="#101925")
    header.pack(fill="x", padx=22, pady=(18, 8))
    tk.Label(header, text="Φ  OPERATOR DESK", font=("Segoe UI", 19, "bold"),
             bg="#101925", fg="#cceafb").pack(anchor="w")
    tk.Label(header, text="LOCAL PROPOSAL INBOX  |  REVIEW IS NOT EXECUTION",
             font=("Segoe UI", 10), bg="#101925", fg="#93aab9").pack(anchor="w")

    bar = tk.Frame(root, bg="#101925")
    bar.pack(fill="x", padx=22, pady=10)
    tk.Label(bar, text="Show", bg="#101925", fg="#d2dfee").pack(side="left")
    status = tk.StringVar(root, "pending")
    filter_box = ttk.Combobox(bar, textvariable=status, width=14, state="readonly",
                              values=["pending", "reviewed", "rejected", "expired", "all"])
    filter_box.pack(side="left", padx=10)
    tk.Button(bar, text="Refresh", command=lambda: refresh(),
              padx=16, relief="flat").pack(side="left")
    summary = tk.StringVar(root, "Ready")
    tk.Label(bar, textvariable=summary, bg="#101925", fg="#96adba").pack(side="right")

    columns = ("operation", "app", "source", "state")
    table = ttk.Treeview(root, columns=columns, show="headings", height=9,
                         selectmode="browse", style="Desk.Treeview")
    for key, label, width in (
        ("operation", "Intent", 100), ("app", "Application", 270),
        ("source", "Source label", 200), ("state", "State", 125),
    ):
        table.heading(key, text=label)
        table.column(key, width=width, minwidth=75)
    table.pack(fill="both", expand=True, padx=22, pady=(0, 12))

    details = tk.Text(root, wrap="word", height=13, bg="#152334", fg="#e2edf8",
                      insertbackground="#e2edf8", relief="flat", padx=14, pady=12,
                      font=("Consolas", 10), state="disabled")
    details.pack(fill="both", expand=True, padx=22, pady=(0, 10))
    buttons = tk.Frame(root, bg="#101925")
    buttons.pack(fill="x", padx=22, pady=(0, 18))
    tk.Label(buttons, text="Nothing executes from this window",
             bg="#101925", fg="#96adba").pack(side="left")
    tk.Button(buttons, text="Reject", width=13,
              command=lambda: decide("rejected")).pack(side="right", padx=(8, 0))
    tk.Button(buttons, text="Mark reviewed", width=16,
              command=lambda: decide("reviewed")).pack(side="right", padx=(8, 0))
    tk.Button(buttons, text="Manual handoff", width=17,
              command=lambda: handoff()).pack(side="right", padx=(8, 0))
    displayed: dict[str, str] = {}

    def selected() -> str | None:
        selection = table.selection()
        return selection[0] if selection else None

    def write_details(value: str) -> None:
        details.configure(state="normal")
        details.delete("1.0", "end")
        details.insert("1.0", value)
        details.configure(state="disabled")

    def on_select(_event=None) -> None:
        item_id = selected()
        if not item_id:
            write_details("Select a proposal to inspect the intent and review policy.")
            return
        try:
            write_details(model.details(item_id))
        except ProposalError as exc:
            write_details("Proposal unavailable: " + exc.code)

    def refresh() -> None:
        old_selection = selected()
        try:
            items = model.list(status.get())
        except (ProposalError, OSError) as exc:
            messagebox.showerror("Inbox error", str(exc), parent=root)
            return
        displayed.clear()
        for iid in table.get_children():
            table.delete(iid)
        for item in items:
            p = item["proposal"]
            table.insert("", "end", iid=item["id"],
                         values=(p["operation"], p["app"], p["source"], item["status"]))
            displayed[item["id"]] = item["digest"]
        summary.set(f"{len(items)} proposals (up to 100)")
        if old_selection in displayed:
            table.selection_set(old_selection)
            table.see(old_selection)
        on_select()

    def decide(decision: str) -> None:
        item_id = selected()
        if not item_id:
            return
        try:
            item = model.get(item_id)
            if displayed.get(item_id) != item["digest"]:
                raise ProposalError("proposal_changed_refresh_required")
            if item["status"] != "pending":
                raise ProposalError("proposal_stale_or_not_pending")
            p = item["proposal"]
            if decision == "reviewed" and not model.policy.permits(p["app"], p["operation"]):
                raise ProposalError("operation_policy_denied")
            challenge = "REVIEW " + secrets.token_hex(4)
            entered = simpledialog.askstring(
                "Confirm local intent review",
                f"Application: {p['app']}\nOperation: {p['operation']}\n"
                f"Reason: {p['reason']}\nDecision: {decision}\n\n"
                "This records a decision. It does NOT act on the desktop.\n"
                f"Type exactly: {challenge}", parent=root,
            )
            if entered != challenge:
                return
            model.review(item_id, displayed[item_id], decision)
            refresh()
            messagebox.showinfo("Decision recorded",
                                f"Marked {decision}. No desktop action performed.",
                                parent=root)
        except (ProposalError, OSError) as exc:
            messagebox.showerror("Review denied", str(exc), parent=root)
            refresh()

    def handoff() -> None:
        item_id = selected()
        if not item_id:
            return
        try:
            write_details(model.handoff(item_id))
        except (ProposalError, OSError) as exc:
            messagebox.showerror("Manual handoff unavailable", str(exc), parent=root)

    table.bind("<<TreeviewSelect>>", on_select)
    filter_box.bind("<<ComboboxSelected>>", lambda event: refresh())
    refresh()
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phi native local proposal desk. Never executes desktop actions."
    )
    parser.add_argument("--db", type=Path, default=Path.home() / ".agentora" / "desktop-inbox.db")
    parser.add_argument("--policy", type=Path, required=True, help="Explicit per-app review policy")
    args = parser.parse_args(argv)
    try:
        run_window(OperatorDeskModel(ProposalInbox(args.db), OperatorPolicy.load(args.policy)))
    except (ProposalError, OSError, ImportError) as exc:
        print(f"Operator Desk could not start: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if type(exc).__module__ == "tkinter" and type(exc).__name__ == "TclError":
            print("Operator Desk needs a graphical local desktop with Tk support.", file=sys.stderr)
            return 2
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
