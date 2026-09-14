# M2 Idea Grill — module report

**Built:** `prompts.py` (generate + judge, rubric ported structure-only from
vendored scoring-rubric.md), `generate.py` (cluster → candidates, batch mode),
`score.py` (hard-reject rules + temp-0 LLM judge, raw output kept for audit),
`gate.py` (hook ≥7 & virality ≥6 thresholds → pass/kill), `__main__.py` CLI.
Shared `modules/common/llm.py` (LLMClient + FakeLLM + parse_json).

**Decisions (schema-faithful):**
- Hard-reject order: viewer → payoff → hook → numbers → structure. Each
  fixture candidate dies by its intended rule.
- "No repayable hook" = hype-marker patterns or <3 words — payoff-overlap was
  too fragile (would misattribute cand-reject-number).
- Killed ideas are still judged (audit trail for G2's human review) and
  padded to 3 bullets so output is always schema-valid; a pass candidate
  lacking bullets after judge repair dies with "incomplete idea structure".
- Judge also returns `three_bullets` — repairs candidates that omit them
  (fixture shape) before the structure check.

**Tests (16, green):** 5 fixture reject cases, threshold boundaries
(6.9✗/7.0✓, 5.9✗/6.0✓), exactly-3-bullets on passes, legible kill reasons,
temp-0 determinism, schema round-trip, generate parsing/capping.

**Gate G2 self-check:** unit criteria pass. Live kill-rate/audit deferred —
needs LLM key + real G1 report.

**Risks:** judge drift (mitigated by temp-0 + raw logs); hype list may need
tuning per niche; unconfirmed clusters are still expanded (more spend —
revisit if G2 yield is poor).
