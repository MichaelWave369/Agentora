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
    st.caption("NEXT: scoped local executor and separate verifier adapters, "
               "exact-SHA proof, human-observed Code Brown usability gate. "
               "No automatic release authority.")
