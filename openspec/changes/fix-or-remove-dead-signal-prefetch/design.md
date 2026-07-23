## Context

The call target never existed on deepear's DatabaseManager (repo-wide grep: single call site). The cache dict, getter, timing stat, and report line formed a fully dead chain.

## Goals / Non-Goals

**Goals:** remove the dead chain; identical observable behavior.
**Non-Goals:** implementing a real DeepEar prefetch (if ever wanted, it needs a real DatabaseManager API and its own change).

## Decisions

Remove rather than fix: no consumer exists for the would-be data, and deepear intelligence flows through the deepear_intelligence analyst at signal-collection time instead.

## Risks / Trade-offs

- None: the removed getter had zero callers; the report line printed a constant 0.00s.
