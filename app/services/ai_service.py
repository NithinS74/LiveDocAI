"""
AI Analysis Pipeline — Gemini 2.5 Flash
─────────────────────────────────────────
Graph:
  [analyze_behavior] → [detect_drift] → [generate_docs] → END

Switched from Ollama/llama3.2 to Gemini 2.5 Flash.
Falls back to Ollama if Gemini key not configured.
"""

import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END
from app.config import get_settings
from app.models.api_log import APILog

logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────────────────────────────────────────
#  LLM factory — returns Gemini if key set, else Ollama
# ─────────────────────────────────────────────────────────────

def get_llm(use_gemini: bool = False):
    """
    Returns LLM instance.

    Priority:
      1. Groq (llama-3.3-70b) — 14,400 req/day, 30 req/min, very fast
      2. Gemini 2.5 Flash     — fallback if no Groq key
    """
    # ── Groq (primary) ───────────────────────────────────────
    if settings.grok_api_key:
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.grok_api_key,
            temperature=0.2,
        )

    # ── Gemini (fallback) ─────────────────────────────────────
    if settings.gemini_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = settings.gemini_model if use_gemini else "gemini-2.0-flash"
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.gemini_api_key,
            temperature=0.2,
        )

    raise RuntimeError(
        "No AI API key found. Add GROK_API_KEY or GEMINI_API_KEY to .env"
    )


async def _invoke(llm, prompt: str) -> str:
    """Unified invoke — handles both ChatGoogleGenerativeAI and OllamaLLM."""
    result = await llm.ainvoke(prompt)
    # ChatGoogleGenerativeAI returns AIMessage, OllamaLLM returns string
    if hasattr(result, 'content'):
        return result.content
    return str(result)


# ─────────────────────────────────────────────────────────────
#  Shared state
# ─────────────────────────────────────────────────────────────

class AnalysisState(TypedDict):
    endpoint_method:   str
    endpoint_path:     str
    logs:              List[Dict[str, Any]]
    behavior_summary:  str
    drift_detected:    bool
    drift_description: Optional[str]
    documentation:     str
    edge_cases:        List[str]
    examples:          List[Dict[str, Any]]
    error:             Optional[str]


# ─────────────────────────────────────────────────────────────
#  Node 1 — Analyze behavior
# ─────────────────────────────────────────────────────────────

async def analyze_behavior(state: AnalysisState) -> AnalysisState:
    try:
        llm = get_llm()
        log_lines = "\n".join([
            f"{l['method']} {l['path']} → {l['status_code']} ({l.get('latency_ms','?')}ms)"
            for l in state["logs"][:30]
        ])

        prompt = f"""Analyze these API logs for endpoint: {state['endpoint_method']} {state['endpoint_path']}

Logs:
{log_lines}

Write a concise 3-5 sentence summary covering:
1. What this endpoint does based on observed behavior
2. Typical response patterns and status codes
3. Any notable patterns or concerns

Summary:"""

        state["behavior_summary"] = (await _invoke(llm, prompt)).strip()
        logger.info(f"[AI] Behavior analysis done for {state['endpoint_path']}")

    except Exception as e:
        logger.error(f"[AI] analyze_behavior error: {e}")
        state["behavior_summary"] = "Behavior analysis unavailable."
        state["error"] = str(e)

    return state


# ─────────────────────────────────────────────────────────────
#  Node 2 — Detect drift
# ─────────────────────────────────────────────────────────────

async def detect_drift(state: AnalysisState) -> AnalysisState:
    try:
        logs = state["logs"]
        if not logs:
            state["drift_detected"] = False
            return state

        statuses  = [l.get("status_code", 200) for l in logs]
        latencies = [l.get("latency_ms", 0) for l in logs if l.get("latency_ms")]
        error_rate = sum(1 for s in statuses if s >= 400) / len(statuses)

        signals = []
        if error_rate > 0.1:
            signals.append(f"High error rate ({error_rate:.0%})")
        if latencies:
            avg = sum(latencies) / len(latencies)
            mx  = max(latencies)
            if mx > avg * 4:
                signals.append(f"Latency spikes: avg={avg:.0f}ms max={mx:.0f}ms")

        llm = get_llm()
        sample = [l.get("response_body", "")[:300] for l in logs[:5] if l.get("response_body")]

        prompt = f"""Analyze this API endpoint for behavioral drift.

Endpoint: {state['endpoint_method']} {state['endpoint_path']}
Observed behavior: {state['behavior_summary']}
Sample responses: {json.dumps(sample)}
Issues found: {signals or 'None'}

Reply with EXACTLY this format:
DRIFT_DETECTED: YES or NO
DESCRIPTION: one sentence if YES, else None"""

        reply = (await _invoke(llm, prompt)).strip()
        ai_drift = "DRIFT_DETECTED: YES" in reply.upper()

        if "DESCRIPTION:" in reply:
            desc = reply.split("DESCRIPTION:", 1)[-1].strip()
            if desc.lower() not in ("none", ""):
                signals.append(desc)

        state["drift_detected"]    = ai_drift or len(signals) > 0
        state["drift_description"] = " | ".join(signals) if signals else None

    except Exception as e:
        logger.error(f"[AI] detect_drift error: {e}")
        state["drift_detected"]    = False
        state["drift_description"] = None

    return state


# ─────────────────────────────────────────────────────────────
#  Node 3 — Generate docs
# ─────────────────────────────────────────────────────────────

async def generate_docs(state: AnalysisState) -> AnalysisState:
    try:
        llm = get_llm()

        prompt = f"""Generate API documentation for this endpoint.

Endpoint: {state['endpoint_method']} {state['endpoint_path']}
Observed behavior: {state['behavior_summary']}

Return ONLY valid JSON (no markdown fences):
{{
  "documentation": "markdown description of the endpoint",
  "edge_cases": ["edge case 1", "edge case 2"],
  "examples": [
    {{
      "description": "Successful request",
      "request":  {{"method": "GET", "path": "/example", "body": null}},
      "response": {{"status": 200, "body": "{{}}"}}
    }}
  ]
}}"""

        raw = (await _invoke(llm, prompt)).strip()

        # Strip markdown fences if present
        if "```" in raw:
            lines = raw.split("\n")
            raw = "\n".join(l for l in lines if not l.strip().startswith("```"))

        try:
            parsed = json.loads(raw)
            state["documentation"] = parsed.get("documentation", state["behavior_summary"])
            state["edge_cases"]    = parsed.get("edge_cases", [])
            state["examples"]      = parsed.get("examples", [])
        except json.JSONDecodeError:
            state["documentation"] = state.get("behavior_summary", "")
            state["edge_cases"]    = []
            state["examples"]      = []

    except Exception as e:
        logger.error(f"[AI] generate_docs error: {e}")
        state["documentation"] = state.get("behavior_summary", "")
        state["edge_cases"]    = []
        state["examples"]      = []

    return state


# ─────────────────────────────────────────────────────────────
#  Build graph
# ─────────────────────────────────────────────────────────────

def _build_graph():
    g = StateGraph(AnalysisState)
    g.add_node("analyze_behavior", analyze_behavior)
    g.add_node("detect_drift",     detect_drift)
    g.add_node("generate_docs",    generate_docs)
    g.set_entry_point("analyze_behavior")
    g.add_edge("analyze_behavior", "detect_drift")
    g.add_edge("detect_drift",     "generate_docs")
    g.add_edge("generate_docs",    END)
    return g.compile()


_graph = _build_graph()


# ─────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────

async def run_analysis(method: str, path: str, logs: List[APILog]) -> AnalysisState:
    log_dicts = [
        {
            "method":        lg.method,
            "path":          lg.path,
            "status_code":   lg.status_code,
            "latency_ms":    lg.latency_ms,
            "request_body":  lg.request_body,
            "response_body": lg.response_body,
        }
        for lg in logs
    ]

    initial: AnalysisState = {
        "endpoint_method":  method,
        "endpoint_path":    path,
        "logs":             log_dicts,
        "behavior_summary": "",
        "drift_detected":   False,
        "drift_description": None,
        "documentation":    "",
        "edge_cases":       [],
        "examples":         [],
        "error":            None,
    }

    return await _graph.ainvoke(initial)


# Keep _llm export for compatibility
def _llm():
    return get_llm(use_gemini=False)
