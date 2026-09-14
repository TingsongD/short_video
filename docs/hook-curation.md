# Hook Bank — weekly curation checklist (~15 min)

`data/hooks/bank.json` feeds M4. Keep it fresh; stale hooks produce stale openings.

1. Open viralhooks.org; filter by each seed niche in `config/niches.toml`.
2. Add 2–3 new hooks per active niche. Required per entry: `id`
   (`hook-<niche3>-<seq>`), `text`, `niche`, `hook_type`
   (spoken|caption|onscreen), `source_url` (the actual page), `added_at`.
3. Prefer hooks that promise a repayable payoff — the grill will kill ideas
   whose hook can't be repaid anyway.
4. Remove hooks repeatedly attached to losing readbacks (check M10 verdicts).
5. Run `make test` — `test_hook_bank` validates the file against the frozen
   schema before you commit.

Seed entries shipped with Wave 1 are placeholder phrasing — replace them as
real viralhooks.org picks accumulate.
