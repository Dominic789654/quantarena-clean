"""Chart-fence sanitizer -- extract-report-agent-pure-chart-and-structured-report-functions (Phase 4 step 26).

`sanitize_json_chart_blocks` is `ReportAgent._sanitize_json_chart_blocks`'s body
(docs/refactor_program_plan.md, step 26) moved verbatim out of
`deepear/src/agents/report_agent.py`, including its nested `find_json_end`
helper. `grep -n "self\\." ` restricted to the original staticmethod's body
finds zero matches -- the method never read or wrote any `ReportAgent`
instance/class state, so this move needed no parameter-threading at all: the
signature is unchanged except for the removed `@staticmethod` decorator and
the leading-underscore-free name.

The two-phase repair strategy -- Phase 0's line-by-line fence-variant
normalization (rejoining with `"\\n".join`, which drops a trailing newline
after the final line, a quirk pinned by
`tests/test_report_agent_characterization.py::TestCleanMarkdownAndSanitize::
test_sanitize_leaves_well_formed_block_unchanged`) and Phase 1's
balanced-brace JSON-end detection used to insert a missing closing fence --
move character-for-character.

Monkeypatch audit (ground rule 2): `git grep -n
"sanitize_json_chart_blocks"` across `tests/`, `deepear/`, `backtest/`,
`deepfund/`, `shared/` finds only: the method definition and one internal
call site (`self._sanitize_json_chart_blocks(...)` inside `generate_report`)
in `deepear/src/agents/report_agent.py`, and three direct calls
(`ReportAgent._sanitize_json_chart_blocks(text)`) in
`tests/test_report_agent_characterization.py`. No literal
`monkeypatch.setattr("...")` string path and no class-attribute patch of the
name exists anywhere in the repo today. `ReportAgent` keeps a real
`_sanitize_json_chart_blocks` staticmethod (a one-line delegator to this
module's `sanitize_json_chart_blocks`, not a bare attribute alias) so a
future `monkeypatch.setattr(ReportAgent, "_sanitize_json_chart_blocks", ...)`
class-attribute patch would still intercept the internal
`self._sanitize_json_chart_blocks(...)` call site.
"""

from __future__ import annotations

from typing import Optional


def sanitize_json_chart_blocks(text: str) -> str:
    """Best-effort repair for malformed json-chart fenced blocks.

    Common failure mode: model outputs an opening ```json-chart but forgets to close it.
    That causes downstream chart processing to miss it and swallows the rest of the report.

    Strategy:
    - For each opening fence, locate the first JSON object and close the fence right after
      the JSON object (balanced braces, ignoring braces inside strings).
    - If a closing fence already exists after the JSON object, leave as-is.
    """

    if not text:
        return text

    # Phase 0: Normalize malformed json-chart fences.
    # We only touch fences in/around json-chart blocks to avoid modifying other markdown.
    if "json-chart" in text:
        lines = text.splitlines()
        out_lines: list[str] = []
        in_chart = False
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not in_chart:
                # Opening fence variants
                if stripped in ("```json-chart", "``json-chart", "``` json-chart", "`` json-chart"):
                    out_lines.append("```json-chart")
                    in_chart = True
                    i += 1
                    continue

                # Variant: opening fence on its own line, language on next line.
                #   ```
                #   json-chart
                #   { ... }
                if stripped in ("```", "``") and i + 1 < len(lines) and lines[i + 1].strip() == "json-chart":
                    out_lines.append("```json-chart")
                    in_chart = True
                    i += 2
                    continue

                # Variant: opening fence appears at end of a content line.
                #   ...：   ```
                #   json-chart
                if stripped.endswith("```") and not stripped.startswith("```"):
                    if i + 1 < len(lines) and lines[i + 1].strip() == "json-chart":
                        prefix = line[: line.rfind("```")].rstrip()
                        if prefix:
                            out_lines.append(prefix)
                        out_lines.append("```json-chart")
                        in_chart = True
                        i += 2
                        continue

            else:
                # Closing fence variants
                if stripped in ("```", "``"):
                    out_lines.append("```")
                    in_chart = False
                    i += 1
                    continue

                # Variant: closing fence appears on the same line after JSON.
                #   { ... } ```
                if "```" in line:
                    pos = line.find("```")
                    before = line[:pos].rstrip()
                    after = line[pos + 3 :].strip()
                    if before:
                        out_lines.append(before)
                    out_lines.append("```")
                    in_chart = False
                    if after:
                        out_lines.append(after)
                    i += 1
                    continue

            out_lines.append(line)
            i += 1

        text = "\n".join(out_lines)

    def find_json_end(s: str, start_idx: int) -> Optional[int]:
        # find first '{'
        i = s.find('{', start_idx)
        if i == -1:
            return None
        depth = 0
        in_str = False
        escape = False
        quote = '"'
        for j in range(i, len(s)):
            ch = s[j]
            if in_str:
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == quote:
                    in_str = False
                continue

            if ch == '"' or ch == "'":
                in_str = True
                quote = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return j
        return None

    # Phase 1: Repair missing closing fences for properly-opened blocks.
    if "```json-chart" not in text:
        return text

    out = []
    i = 0
    needle = "```json-chart"
    while True:
        idx = text.find(needle, i)
        if idx == -1:
            out.append(text[i:])
            break

        # append preceding text
        out.append(text[i:idx])

        # keep the opening fence line
        fence_line_end = text.find("\n", idx)
        if fence_line_end == -1:
            out.append(text[idx:])
            break
        fence_line_end += 1
        out.append(text[idx:fence_line_end])

        # attempt to find end of JSON object
        json_end = find_json_end(text, fence_line_end)
        if json_end is None:
            # cannot repair; keep rest and stop
            out.append(text[fence_line_end:])
            break

        # include JSON object (up to closing brace)
        out.append(text[fence_line_end:json_end + 1])

        # check if there's already a closing fence soon after
        after_json = text[json_end + 1:]
        closing_idx = after_json.find("```")
        opening_idx2 = after_json.find(needle)

        if closing_idx != -1 and (opening_idx2 == -1 or closing_idx < opening_idx2):
            # existing closing fence; keep everything up to it as-is
            out.append(after_json[:closing_idx + 3])
            i = json_end + 1 + closing_idx + 3
            continue

        # missing closing fence: insert one
        out.append("\n```\n")
        i = json_end + 1

    return "".join(out)
