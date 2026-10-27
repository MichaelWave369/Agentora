"""Local-only, explicitly non-authoritative Streamlit Development Board R0 view."""


def render_development_board(st, api_get) -> None:
    st.title("Φ Development Board · R0")
    st.warning(
        "DESIGN / DEMO MODE ONLY. No live coding workers, GitHub writes, "
        "verification authority, automatic merge or deployment are connected."
    )
    st.caption("Nine skill responsibilities, not nine permission grants. "
               "The original source files have not been imported.")

    payload = api_get("/api/development-board/skills", "Development Board skill registry")
    skills = payload.get("skills", []) if isinstance(payload, dict) else []
    if skills:
        st.subheader("Nine-skill crew")
        for skill in skills:
            with st.expander(f"{skill['name']} · {skill['stage']}"):
                st.markdown(skill["description"])
                st.caption(f"Legacy identifier: {skill['legacy_id']}")
                st.markdown("Evidence requested: " + ", ".join(skill["requires"]))
        st.caption("Catalog provenance: " + payload.get("source_status", "UNKNOWN"))
    else:
        st.info("The nine-skill catalog is unavailable. Check the local API.")

    st.subheader("Your local draft")
    st.caption("This is a browser-session planning note only. It is not stored in "
               "Agentora's database, sent to a model, approved, or submitted as a PR.")
    title = st.text_input("Work item title", value="", key="devboard_title")
    repo = st.text_input("Repository or project", value="", key="devboard_repo")
    objective = st.text_area("Objective and acceptance criteria", value="",
                             key="devboard_objective")
    if st.button("Keep draft in this session", key="devboard_save_draft"):
        if not title.strip() or not objective.strip():
            st.warning("A title and acceptance criteria are required for a draft.")
        else:
            st.session_state["development_board_draft"] = {
                "title": title.strip()[:200],
                "repository": repo.strip()[:200] or "(not selected)",
                "objective": objective.strip()[:4000],
                "status": "SPEC_DRAFT",
                "approval": "NOT_REQUESTED",
                "commit_sha": None,
                "verification": "NO_EVIDENCE",
                "mode": "LOCAL_SESSION_DRAFT",
            }
    draft = st.session_state.get("development_board_draft")
    if draft:
        st.json(draft)
    else:
        st.info("No local draft yet. Create one above, or inspect the fictional demonstration below.")

    st.subheader("Fictional proof receipt")
    demo = api_get("/api/development-board/demo", "Development Board fixture")
    if isinstance(demo, dict) and demo.get("mode") == "SYNTHETIC_FIXTURE":
        for item in demo.get("work_items", []):
            st.markdown(f"**{item['id']}: {item['title']}**")
            st.caption("SYNTHETIC FIXTURE. Fake SHA, fake approver and fake test reference.")
            st.json({
                "repo": item.get("repo"), "spec_approval": item.get("spec_approval"),
                "submitted_commit_sha": item.get("submitted_commit_sha"),
                "frozen_spec_digest": item.get("frozen_spec_digest"),
                "assessment": item.get("receipt_assessment"),
                "pending_human_decisions": item.get("pending_human_decisions"),
            })
    else:
        st.info("No sample fixture available. No live evidence is implied.")
    st.caption("R0 remains read-only: no automatic release authority.")
    render_handoff_pilot(st)
    st.subheader("R1-B · Controlled scratch builder/verifier")
    st.info(
        "Operator CLI only. The builder and independently implemented verifier run as "
        "two real local child processes, but this is a deterministic HTML fixture, "
        "not an autonomous coding agent or OS sandbox. No GitHub writes or merges."
    )
    st.caption(
        "Open docs/DEVELOPMENT_BOARD_R1B_WORKERS.md. Review the supplied JSON spec, "
        "copy the digest from the read-only plan step, then run the explicit local "
        "command yourself. The dashboard does not dispatch subprocesses."
    )
    st.code(
        "python -m app.services.development_board.r1b_cli plan "
        "examples/development-board/r1b-fixture-spec.json",
        language="powershell",
    )

    st.subheader("R1-C · Local Ollama model proposal")
    st.info(
        "Operator-run CLI only. A local Ollama model proposes one untrusted static "
        "HTML document in a new scratch folder. The separate verifier checks "
        "the frozen spec and exact artifact bytes. This is not PhiBot draft-PR "
        "execution, a secure sandbox, or permission to merge."
    )
    st.caption(
        "See docs/DEVELOPMENT_BOARD_R1C_OLLAMA.md. You must explicitly approve "
        "the frozen specification digest and local model call in your own terminal. "
        "No web or Streamlit action launches the model or writes to a repo."
    )
    st.code(
        "python -m app.services.development_board.r1c_cli plan "
        "examples/development-board/r1b-fixture-spec.json",
        language="powershell",
    )


def render_handoff_pilot(st) -> None:
    """Deliberate, user-clicked local evidence comparison. No job dispatch."""
    import json

    from app.services.development_board.r1_handoff import (
        fetch_local_gitporch, preview_handoff,
    )

    st.subheader("R1-A · Exact-commit evidence handoff")
    st.warning(
        "REVIEW-ONLY. GitPorch and PhiBot source claims are not authenticated. "
        "Even matching PASS reports cannot authorize merging or deployment."
    )
    st.caption(
        "Requires GitPorch running on your computer. Set "
        "AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED=1 in your local environment "
        "to enable a manual, loopback-only GET. Nothing runs automatically."
    )
    if st.button("Read local GitPorch PhiRunners status", key="devboard_gitporch_read"):
        st.session_state["devboard_gitporch_read"] = fetch_local_gitporch()
    gp_result = st.session_state.get("devboard_gitporch_read")
    if isinstance(gp_result, dict):
        st.json({
            "connection": gp_result.get("connection", "UNKNOWN"),
            "reason": gp_result.get("reason", ""),
            "health": (gp_result.get("snapshot") or {}).get("health"),
            "jobs_returned": len((gp_result.get("snapshot") or {}).get("jobs", [])),
        })
    st.caption(
        "Use the GitPorch local repo slug and the matching GitHub owner/repo. "
        "The exact 40-character SHA must identify the same code in both places."
    )
    local_repo = st.text_input("GitPorch local repository", value="", key="devboard_r1_local_repo")
    github_repo = st.text_input("GitHub owner/repository", value="", key="devboard_r1_gh_repo")
    pr_text = st.text_input("PhiBot draft PR number", value="", key="devboard_r1_pr")
    sha = st.text_input("Exact 40-character commit SHA", value="", key="devboard_r1_sha")
    phibot_json = st.text_area(
        "Paste a redacted PhiBot steward:verify JSON report (session only)",
        value="", key="devboard_r1_pb_report",
    )
    st.caption(
        "Never paste GitHub tokens, local credentials or private issue contents. "
        "A copied report is user-supplied, not a live authenticated GitHub check."
    )
    if st.button("Compare exact-commit reports", key="devboard_r1_compare"):
        try:
            pb = json.loads(phibot_json) if phibot_json.strip() else None
        except (ValueError, TypeError):
            pb = None
        pr = int(pr_text) if pr_text.isdecimal() else None
        snapshot = gp_result.get("snapshot") if isinstance(gp_result, dict) else None
        st.session_state["devboard_r1_result"] = preview_handoff({
            "local_repo": local_repo,
            "github_repo": github_repo,
            "pr_number": pr,
            "commit_sha": sha,
            "gitporch": snapshot,
            "phibot": pb,
        })
    result = st.session_state.get("devboard_r1_result")
    if result:
        st.json(result)
        st.caption(
            "REVIEW_READY_NOT_AUTHORIZED means both imported sources agree on one "
            "SHA and report passing checks, not that their claims are authentic "
            "or current. Human review remains mandatory."
        )
    else:
        st.info("No real handoff compared yet. R0 demo receipts do not qualify.")

