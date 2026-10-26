"""Page 6 - AI Finance Analyst: grounded Q&A and QBR drafts over approved analytical functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # `cloudspend` / `config` importable without pip install

import pandas as pd
import streamlit as st

from cloudspend.ai.analyst import answer
from cloudspend.ai.intents import SUPPORTED_QUESTIONS
from cloudspend.ai.llm import LLMNotAvailable, get_provider
from cloudspend.ai.tools import DataBundle
from components.common import setup_page
from components.kpi_cards import md_safe

ctx = setup_page("AI Finance Analyst")

EXAMPLES = [
    "Explain the month-over-month cost increase.",
    "Which departments are furthest over budget?",
    "Summarize the three highest-impact anomalies.",
    "Give me the current forecast and its limitations.",
    "Draft a QBR summary for the selected period.",
    "Investigate the cost increase in depth.",
]


@st.cache_data(ttl=600, show_spinner="Loading analysis data...")
def _bundle() -> DataBundle:
    return DataBundle.load()


def _use_example(text: str) -> None:
    st.session_state["ai_question"] = text
    st.session_state["ai_run"] = True


try:
    bundle = _bundle()
except Exception as exc:
    st.error(f"Could not load analysis data ({type(exc).__name__}).")
    st.stop()

try:
    provider = get_provider()
    provider_note = f"AI wording: {provider.name}" if provider else "AI wording: off (deterministic summaries)"
except LLMNotAvailable as exc:
    provider, provider_note = None, f"AI wording unavailable: {exc}"

st.caption(
    "Answers come from a fixed set of approved calculations over the reporting data. The analyst never writes or runs SQL, "
    "and every number in an answer is traced to a calculation below it. "
    f"{provider_note}. Period and filters default to the sidebar selection; a period or department named in your question "
    "overrides it."
)

# Deep link: ?q=<question> pre-fills and runs the question once (handy for demos and screenshots).
if (deep_q := st.query_params.get("q")) and not st.session_state.get("ai_deep_link_used"):
    st.session_state.update(ai_question=deep_q, ai_run=True, ai_deep_link_used=True)

st.markdown("**Try an example**")
cols = st.columns(len(EXAMPLES))
for i, (col, text) in enumerate(zip(cols, EXAMPLES, strict=True)):
    col.button(text, key=f"ex_{i}", on_click=_use_example, args=(text,), use_container_width=True)

st.text_area("Ask a question about the data", key="ai_question", height=80,
             placeholder="e.g. Which departments are furthest over budget in Q3 2025?")
ask = st.button("Ask", key="ai_ask", type="primary")

if ask or st.session_state.pop("ai_run", False):
    q = st.session_state.get("ai_question", "").strip()
    if not q:
        st.warning("Type a question first.")
    else:
        with st.spinner("Calculating..."):
            st.session_state["ai_answer"] = answer(q, bundle, ctx.filters, provider)

ans = st.session_state.get("ai_answer")
if ans is None:
    with st.expander("What can I ask?"):
        st.markdown("\n".join(f"- {q}" for q in SUPPORTED_QUESTIONS))
    st.stop()

st.divider()
st.markdown(md_safe(f"**Question:** {ans.question}"))
if ans.period:
    st.markdown(f"**Period used:** {ans.period}")
for w in ans.warnings:
    st.warning(w)

if ans.status == "blocked":
    st.warning(ans.text)
elif ans.status in ("unsupported", "no_data"):
    st.info(ans.text)
elif ans.status == "invalid":
    st.error(ans.text)
else:
    st.markdown(md_safe(ans.text))
    if ans.qbr is not None:
        st.download_button("Download QBR (Markdown)", ans.qbr.to_markdown(), file_name="cloudspend_qbr.md",
                           mime="text/markdown", key="qbr_download")

if ans.results:
    if ans.limitations and ans.qbr is None:  # a QBR carries its own limitations section
        st.markdown("**Limitations**")
        st.markdown(md_safe("\n".join(f"- {x}" for x in ans.limitations)))

    with st.expander("Key figures and where each came from", expanded=False):
        figs = pd.DataFrame([{"Figure": f.label, "Value": ans.ledger.fmt(f.id), "Unit": f.unit, "Source": f.source, "ID": f.id}
                             for f in ans.ledger.figures()])
        st.dataframe(figs, hide_index=True, use_container_width=True)

    with st.expander("Supporting data", expanded=False):
        shown = False
        for r in ans.results:
            tables = dict(r.tables)
            if r.tool == "generate_qbr_metrics":
                tables = {"quarters": tables.get("quarters"), **{f"{k}.{n}": t for k, part in r.facts["parts"].items()
                                                                  for n, t in part.tables.items()}}
            for name, df in tables.items():
                if df is not None and len(df):
                    st.caption(f"{r.tool} - {name}")
                    st.dataframe(df, hide_index=True, use_container_width=True)
                    shown = True
        if not shown:
            st.write("No supporting tables for this answer.")

    with st.expander("How this answer was produced"):
        st.markdown(f"- **Intent:** `{ans.intent}` (rule-based routing)\n- **Mode:** {ans.mode}\n"
                    f"- **Total time:** {ans.duration_ms:.0f} ms")
        if ans.trace:
            st.caption("Agent trace: each step was chosen from the results of the earlier ones; skipped steps show why.")
            st.dataframe(pd.DataFrame([{"Step": s.n, "Tool": s.tool, "Arguments": s.arguments, "Why": s.reason,
                                        "Status": s.status, "Time (ms)": round(s.duration_ms, 1)} for s in ans.trace]),
                         hide_index=True, use_container_width=True)
        else:
            st.dataframe(pd.DataFrame([{"Tool": r.tool, "Status": r.status, "Time (ms)": round(r.duration_ms, 1)}
                                       for r in ans.results]), hide_index=True)
