"""Citation/bibliography manager -- extract-report-agent-citation-manager (Phase 4 step 27).

`make_cite_key`, `build_bibliography`, `render_references_section`,
`inject_references`, `normalize_citations`, and `clean_markdown` are
`ReportAgent._make_cite_key`, `ReportAgent._build_bibliography`,
`ReportAgent._render_references_section`, `ReportAgent._inject_references`,
`ReportAgent._normalize_citations`, and `ReportAgent._clean_markdown`'s
bodies (docs/refactor_program_plan.md, step 27) moved verbatim out of
`deepear/src/agents/report_agent.py`.

`grep -n "self\\."` restricted to five of the six original method bodies
(`_make_cite_key`, `_render_references_section`, `_inject_references`,
`_normalize_citations`, `_clean_markdown`) finds zero matches -- none of them
read or wrote any `ReportAgent` instance/class state, so those five moved with
no parameter-threading at all (only the leading underscore and, where
present, the `@staticmethod` decorator were dropped). `_build_bibliography`
is the one exception: its body reads `self._make_cite_key(...)` (now just a
direct call to this module's own `make_cite_key`, since both live in the same
module) and `self.db.lookup_reference_by_url(url)`. Per ground rule 6, that
second read is threaded through as an explicit required keyword-only `db`
parameter (`build_bibliography(signals, *, db)`) rather than being read off an
instance -- there is nothing else `self.`-shaped in the body.

`_normalize_citations`'s nested `repl_legacy`/`repl_key`/`repl_loose_key`
closures move character-for-character, including the Phase 0 bug-fix history
recorded in
`openspec/changes/archive/2026-07-23-fix-report-agent-citation-normalize-args/`:
the function has always required all three of `report_md`, `signal_to_keys`,
and `key_to_num` (`TypeError` otherwise), and that requirement is unchanged
here -- this move introduces no new default and does not touch the fixed
call site in `report_agent.py`'s `generate_report`.

Monkeypatch audit (ground rule 2): `git grep -n
"_make_cite_key\\|_build_bibliography\\|_render_references_section\\|
_inject_references\\|_normalize_citations\\|_clean_markdown" tests/ deepear/
backtest/ deepfund/ shared/` finds: the six method definitions and their
internal `self.`/`self._`-qualified call sites inside
`deepear/src/agents/report_agent.py`'s `generate_report`/`_incremental_edit`;
`tests/test_report_agent_citations.py` and
`tests/test_report_agent_characterization.py` both call
`ReportAgent._make_cite_key(url=..., title=..., source_name=...)` directly on
the *class* (not an instance) at module import time to derive deterministic
cite keys for their fixtures; `tests/test_report_agent_characterization.py`
also calls `harness.agent._clean_markdown(text)` directly on an *instance*.
No test calls `_build_bibliography`, `_render_references_section`,
`_inject_references`, or `_normalize_citations` directly -- they are only
exercised indirectly through a real `generate_report` run. No literal
`monkeypatch.setattr("...")` string path and no class-attribute patch of any
of the six names exists anywhere in the repo today. `ReportAgent` keeps all
six as real attributes of their original binding kind (staticmethod for
`_make_cite_key`/`_render_references_section`/`_inject_references`/
`_normalize_citations`; bound instance methods for `_build_bibliography`/
`_clean_markdown`, since `_build_bibliography` needs `self.db` and
`_clean_markdown` is called as `self._clean_markdown(...)` throughout) --
each a one-line delegator, not a bare attribute alias, so
`ReportAgent._make_cite_key(url=..., ...)`-style class-level calls and any
future class-/instance-attribute monkeypatch of any of the six names keep
working exactly as before.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List


def make_cite_key(url: str, title: str = "", source_name: str = "") -> str:
    basis = (url or "").strip() or f"{(title or '').strip()}|{(source_name or '').strip()}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]
    return f"SF-{digest}"


def build_bibliography(signals: List[Any], *, db: Any) -> "tuple[list[Dict[str, Any]], Dict[int, list[str]]]":
    """Build stable bibliography entries and per-signal cite key mapping.

    Args:
        signals: signals to scan for source citations.
        db: the `DatabaseManager`-like collaborator used to look up canonical
            reference metadata by URL (`db.lookup_reference_by_url(url)`) --
            corresponds to the original method's `self.db`.

    Returns:
        bib_entries: ordered unique entries: [{key,url,title,source,publish_time}]
        signal_to_keys: {signal_index(1-based): [key1,key2,...]}
    """
    bib_by_key: Dict[str, Dict[str, Any]] = {}
    signal_to_keys: Dict[int, list[str]] = {}

    for sig_idx, signal in enumerate(signals, 1):
        source_items: list[Dict[str, Any]] = []

        if hasattr(signal, "sources") and getattr(signal, "sources"):
            source_items = list(getattr(signal, "sources") or [])
        elif isinstance(signal, dict) and signal.get("sources"):
            # analyzed_signals are dicts; their sources are nested under the `sources` key
            src_list = signal.get("sources")
            if isinstance(src_list, list) and src_list:
                source_items = list(src_list)
        elif isinstance(signal, dict):
            # Treat raw signals as single-source entries
            if signal.get("url") or signal.get("title"):
                source_items = [
                    {
                        "title": signal.get("title"),
                        "url": signal.get("url"),
                        "source_name": signal.get("source") or signal.get("source_name"),
                        "publish_time": signal.get("publish_time"),
                    }
                ]

        if not source_items:
            continue

        for src in source_items:
            url = (src.get("url") or "").strip()
            title = (src.get("title") or "").strip()
            source_name = (src.get("source_name") or src.get("source") or "").strip()
            publish_time = (src.get("publish_time") or "").strip() if isinstance(src.get("publish_time"), str) else src.get("publish_time")

            key = make_cite_key(url=url, title=title, source_name=source_name)
            signal_to_keys.setdefault(sig_idx, [])
            if key not in signal_to_keys[sig_idx]:
                signal_to_keys[sig_idx].append(key)

            if key in bib_by_key:
                continue

            # Prefer canonical metadata from DB when possible
            enriched = db.lookup_reference_by_url(url) if url else None
            bib_by_key[key] = {
                "key": key,
                "url": url or (enriched.get("url") if enriched else ""),
                "title": (enriched.get("title") if enriched else None) or title or "（无标题）",
                "source": (enriched.get("source") if enriched else None) or source_name or "（未知来源）",
                "publish_time": (enriched.get("publish_time") if enriched else None) or publish_time or "",
            }

    return list(bib_by_key.values()), signal_to_keys


def render_references_section(bib_entries: list[Dict[str, Any]], key_to_num: Dict[str, int]) -> str:
    lines = ["## 参考文献", ""]
    if not bib_entries:
        lines.append("（无）")
        return "\n".join(lines).strip() + "\n"

    for entry in bib_entries:
        key = entry.get("key")
        num = key_to_num.get(key) if key else None
        title = entry.get("title") or "（无标题）"
        source = entry.get("source") or "（未知来源）"
        url = entry.get("url") or ""
        publish_time = entry.get("publish_time") or ""
        suffix = ""
        if publish_time:
            suffix = f"，{publish_time}"
        label = f"[{num}]" if isinstance(num, int) else "[?]"
        if url:
            lines.append(f"<a id=\"ref-{key}\"></a>{label} {title} ({source}{suffix}), {url}")
        else:
            lines.append(f"<a id=\"ref-{key}\"></a>{label} {title} ({source}{suffix})")

    return "\n".join(lines).strip() + "\n"


def inject_references(report_md: str, references_md: str) -> str:
    # Replace existing references section, if any
    pattern = re.compile(r"(?ms)^##\s*参考文献\s*$.*?(?=^##\s|\Z)")
    if pattern.search(report_md or ""):
        return pattern.sub(references_md.strip() + "\n\n", report_md).strip()

    # Otherwise append at end
    return (report_md or "").rstrip() + "\n\n" + references_md.strip() + "\n"


def normalize_citations(report_md: str, signal_to_keys: Dict[int, list[str]], key_to_num: Dict[str, int]) -> str:
    text = report_md or ""

    # Convert legacy [[n]] to the first available cite key for that signal.
    def repl_legacy(match: re.Match) -> str:
        idx = int(match.group(1))
        keys = signal_to_keys.get(idx) or []
        if not keys:
            return match.group(0)
        key = keys[0]
        num = key_to_num.get(key)
        label = f"[{num}]" if isinstance(num, int) else "[?]"
        return f"{label}(#ref-{key})"

    text = re.sub(r"\[\[(\d+)\]\]", repl_legacy, text)

    # Convert cite keys to numbered display while keeping stable anchor: [@KEY] -> [N](#ref-KEY)
    def repl_key(match: re.Match) -> str:
        key = match.group("key")
        num = key_to_num.get(key)
        label = f"[{num}]" if isinstance(num, int) else "[?]"
        return f"{label}(#ref-{key})"

    text = re.sub(r"\[@(?P<key>[A-Za-z0-9][A-Za-z0-9:_\-]{0,64})\](?!\()", repl_key, text)

    # Convert loose cite markers like: （@SF-xxxxxxxx） / (@SF-xxxxxxxx)
    # These sometimes appear when the model forgets the bracket form.
    def repl_loose_key(match: re.Match) -> str:
        lparen = match.group("lparen")
        rparen = match.group("rparen")
        key = match.group("key")
        num = key_to_num.get(key)
        label = f"[{num}]" if isinstance(num, int) else "[?]"
        return f"{lparen}{label}(#ref-{key}){rparen}"

    text = re.sub(
        r"(?P<lparen>[\(\（])\s*@(?P<key>SF-[0-9a-fA-F]{8})\s*(?P<rparen>[\)\）])",
        repl_loose_key,
        text,
    )

    return text


def clean_markdown(text: str) -> str:
    """Helper to remove markdown code fences"""
    text = text.strip()
    if text.startswith("```markdown"):
        text = text[len("```markdown"):].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text
