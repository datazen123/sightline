"""Thin UI: deal sheet, cited investor Q&A, risk flags, and the context
inspector panel (one of the two non-cuttable features per docs/build-spec.md).

Run: uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agents.llm import MissingAPIKeyError
from agents.orchestrator import Orchestrator

st.set_page_config(page_title="Sightline - Larkveil Residences", layout="wide")


@st.cache_resource
def get_orchestrator() -> Orchestrator:
    return Orchestrator()


def show_citations(citations: list[dict]) -> None:
    for c in citations:
        doc_id = c["doc_id"] if isinstance(c, dict) else c.doc_id
        location = c["location"] if isinstance(c, dict) else c.location
        snippet = c["snippet"] if isinstance(c, dict) else c.snippet
        st.caption(f"[{doc_id} | {location}] “{snippet}”")


SEVERITY_COLOR = {"low": "blue", "medium": "orange", "high": "red"}


def main() -> None:
    st.title("Sightline")
    st.caption(
        "Deal-room diligence agent - synthetic demo corpus (Larkveil Residences, "
        "fictional). See docs/ in the repo for the design notes."
    )

    orch = get_orchestrator()

    with st.sidebar:
        st.subheader("Deal room documents")
        for d in orch.list_documents():
            st.write(f"- {d.title} ({d.pages}p)")
        st.divider()
        st.caption(
            "Requires ANTHROPIC_API_KEY in .env for the agent tabs. "
            "Document list above works without a key."
        )

    tab_sheet, tab_qa, tab_risk, tab_memo, tab_inspector = st.tabs(
        ["Deal Sheet", "Investor Q&A", "Risk Findings", "Memos", "Context Inspector"]
    )

    with tab_sheet:
        st.subheader("Extracted Deal Sheet")
        if st.button("Extract deal sheet + financials", key="extract_btn"):
            try:
                with st.spinner("Extractor agent reading the deal room..."):
                    deal_sheet = orch.get_deal_terms()
                    financials = orch.get_financials()
                st.session_state["deal_sheet"] = deal_sheet
                st.session_state["financials"] = financials
            except MissingAPIKeyError as e:
                st.error(str(e))

        if "deal_sheet" in st.session_state:
            ds = st.session_state["deal_sheet"]
            fin = st.session_state["financials"]
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Deal terms**")
                st.write(f"Property: {ds.property_name}")
                st.write(f"Address: {ds.address}")
                st.write(f"Units: {ds.units}")
                st.write(f"Strategy: {ds.strategy}")
                st.write(f"Purchase price: ${ds.purchase_price:,.0f}")
                st.write(f"Target hold: {ds.target_hold_years} years")
                st.write(f"Projected IRR: {ds.projected_irr}")
                st.write(f"Projected MOIC: {ds.projected_moic}")
                st.write("Fees: " + "; ".join(ds.fees))
                show_citations([c.model_dump() for c in ds.citations])
            with col2:
                st.markdown("**Financials**")
                st.write(f"T-12 NOI: {fin.t12_noi}")
                st.write(f"In-place occupancy: {fin.in_place_occupancy}")
                st.write(f"Pro forma Year 1 NOI: {fin.proforma_year1_noi}")
                st.write(f"Exit cap rate: {fin.exit_cap_rate}")
                st.write(f"Market cap rate: {fin.market_cap_rate}")
                for u in fin.unit_mix:
                    st.write(f"- {u}")
                show_citations([c.model_dump() for c in fin.citations])

    with tab_qa:
        st.subheader("Ask a question about this deal")
        st.caption(
            "Try both kinds: a factual one ('what is the acquisition fee?') "
            "and a judgment one ('is this sponsor trustworthy?') to see the "
            "judgment boundary in action."
        )
        question = st.text_input("Question", key="qa_question")
        if st.button("Ask", key="qa_btn") and question:
            try:
                with st.spinner("Investor Q&A agent working..."):
                    answer = orch.ask(question)
                badge = "verifiable" if answer.classification == "verifiable" else "judgment required"
                st.markdown(f"**Classification:** `{badge}`  |  **Answered:** {answer.answered}")
                st.write(answer.text)
                show_citations([c.model_dump() for c in answer.citations])
            except MissingAPIKeyError as e:
                st.error(str(e))

    with tab_risk:
        st.subheader("Risk findings")
        if st.button("Run risk review", key="risk_btn"):
            try:
                with st.spinner("Risk/Underwriter agent cross-checking documents..."):
                    findings = orch.flag_risks()
                st.session_state["findings"] = findings
            except MissingAPIKeyError as e:
                st.error(str(e))

        for f in st.session_state.get("findings", []):
            color = SEVERITY_COLOR.get(f.severity, "gray")
            st.markdown(
                f"##### :{color}[{f.severity.upper()}] {f.title}  "
                f"`{f.classification}`"
            )
            st.write(f.explanation)
            show_citations([c.model_dump() for c in f.evidence])
            st.divider()

    with tab_memo:
        st.subheader("Generated memos")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Draft internal diligence memo", key="memo_btn"):
                try:
                    with st.spinner("Summarizer agent drafting..."):
                        st.session_state["memo"] = orch.diligence_memo()
                except MissingAPIKeyError as e:
                    st.error(str(e))
            if "memo" in st.session_state:
                st.text_area("Diligence memo", st.session_state["memo"], height=300)
        with c2:
            if st.button("Draft investor summary", key="inv_summary_btn"):
                try:
                    with st.spinner("Summarizer agent drafting..."):
                        st.session_state["inv_summary"] = orch.investor_summary()
                except MissingAPIKeyError as e:
                    st.error(str(e))
            if "inv_summary" in st.session_state:
                st.text_area("Investor summary", st.session_state["inv_summary"], height=300)

    with tab_inspector:
        st.subheader("Context inspector")
        st.caption(
            "Every agent call, logged: system prompt, exactly what context it "
            "received, what was excluded and why, and token counts."
        )
        if not orch.log.entries:
            st.info("No agent calls yet - use the other tabs first.")
        for entry in reversed(orch.log.entries):
            st.markdown(f"**{entry.agent}** - {entry.timestamp}")
            st.write(
                f"Tokens in: {entry.tokens_in}  |  Tokens out: {entry.tokens_out}"
            )
            with st.expander("System prompt"):
                st.code(entry.system_prompt)
            st.write("Retrieved context:")
            for c in entry.retrieved_context:
                st.caption(f"- {c}")
            st.write(f"Excluded: {entry.excluded}")
            st.divider()


if __name__ == "__main__":
    main()
