# Validation Gates — Sign-off Log

Each gate per BUILD_PLAN.md §3. Status: ✅ signed / ⬜ pending / ❌ failed.
Live gates (G1, G5–G10) additionally require human key/spend approval (Wave 3).

| Gate | Module | Status | Evidence | Signed by | Date |
|---|---|---|---|---|---|
| **G0** | M0 Foundations | ✅ **SIGNED** | `make test` green (folders, config, secrets shape, schema round-trips); `uv run python cli.py --help` runs in vendor/MoneyPrinterTurbo; no key-shaped strings in tracked files; vendor pins in docs/vendor-pins.md | coordinator (Wave 0) | 2026-09-14 |
| G1 | M1 Niche Radar | ⬜ pending | unit criteria met 2026-09-14: schema-valid report from fixture scan, quota counter caps search calls + degrades to channel-only, breakout flag at 5x/2x/14d. Live scan still needed | — | — |
| G2 | M2 Idea Grill | ⬜ pending | unit criteria met 2026-09-14: 4 hard-reject rules fire correctly, thresholds at exact boundaries, temp-0 determinism, schema-valid output, raw judge output logged. Live audit (≥30% kill, ≥8/10 agreement) pending real LLM | — | — |
| G3 | M3 Format Library | ⬜ pending | unit criteria met 2026-09-14: CRUD + stable IDs, extract validates + no-copy guard (>0.6 Jaccard rejected), match = exactly 1 default + labeled alt, promote/retire at exact thresholds. library.json seeded offline with 10 pattern entries (2026-09-14 patch); radar-extracted refresh pending G1 + LLM | — | — |
| G4 | M4 Hook Bank | ⬜ pending | unit criteria met 2026-09-14: bank.json schema-valid, selector matches niche+type w/ niche fallback, attribution preserved, LookupError on empty niche. Bank topped up to 5/niche: 12 curated + 18 labeled `original-pattern` (2026-09-14 patch); authentic viralhooks.org curation per docs/hook-curation.md still pending | — | — |
| G5 | M5 Script Engine | ⬜ pending | unit criteria met 2026-09-14: 60-110w bound enforced, hook verbatim first sentence, 4-7 shots w/ durations tracking voice est, idx0 forced video, per-shot Pexels fallback, schema-valid shot_list. Human approval of 5 scripts pending LLM | — | — |
| G6 | M6 Asset Pipeline | ⬜ pending | unit criteria met 2026-09-14: intake validates (≥720px, ≥3s, rejects bad/zero-byte), filename→shot_idx mapping + provenance tags, manifest schema-valid w/ missing_shots, Pexels fallback mocked, selector map parses. Lane B real drop + Lane A smoke pending | — | — |
| G7 | M7 Voice | ⬜ pending | unit criteria met 2026-09-14: request payload (voice_id/model/text) verified, text re-cleaned before send, 15-60s ffprobe gate (20s ok / 8s rejected). Real generation + blind listen pending keys | — | — |
| G8 | M8 Assembly | ⬜ pending | unit criteria met 2026-09-14: mpt_task maps manifest->MPT fields (local source, assets/ rel paths, word_by_word subs, 9:16), batch ≤100 validated, QC checks res/audio/duration/size + frame extract. Real MPT run + operator watch pending | — | — |
| G9 | M9 Publishing | ⬜ pending | unit criteria met 2026-09-14: metadata bounded (≤100 title, ≤15 deduped tags, CTA enforced), record schema-valid + dupes rejected, cadence blocks 3rd daily post. Real publish pending | — | — |
| G10 | M10 Readback | ⬜ pending | unit criteria met 2026-09-14: tz-safe 48h/7d/28d scheduling, win=2x median & AVD>=70%, readback schema-valid, verdict feeds M3 promote/retire, weekly summary emitter. Live pulls pending keys | — | — |
| G11 | M11 Orchestration | ⬜ pending | unit criteria met 2026-09-14: `run.sh produce/readback/weekly/approve/cron-line`; cost ledger appends + hard-stops at weekly cap before the call; approval gate blocks unapproved spend (token/env/TTY); stages run in order, first failure stops + logs run record. Live weekly cron fire pending `install-cron` | — | — |
| G12 | M12 E2E | ⬜ pending | unit criteria met 2026-09-14: `test_e2e_dry.py` M1→M8 fixtures schema-valid in order; `test_failure_drills.py` — 8 drills each fail loudly at the right gate; per-stage `duration_s` in run records; `docs/e2e-report.md` template ready. Real published video, ≤30 min human time, cost in cap, 48h readback still pending | — | — |

## G0 evidence detail (2026-09-14)

### Canvas integration addendum (2026-09-14)

G6 offline coverage now includes the official Canvas subprocess protocol,
preflight model/parameter checks, quote ceilings, ambiguous submission recovery,
download retries, media-kind matching and explicit stock fallback. Full suite:
208 passed in 15.20s. Canvas CLI 1.0.1 installed; separate authorization expired.
Account/catalog checks, quoted pilot and full live asset set remain pending.
No credits spent; G6 remains unsigned. See `docs/jimeng-canvas-cli.md`.

G8 addendum: actual FFmpeg tests verify ordered video/still preparation, narration
timing, insufficient footage and cache reuse. MPT subprocess tests verify result
JSON, task failures and copying the returned vendor output instead of accepting
stale finals. The local MPT launcher disables auto-upload and selects Whisper for
custom-audio subtitles. Its `--help` smoke test passed. Full rendered MPT workflow
and operator review remain pending; G8 remains unsigned.

Native MPT follow-up: a schema-valid batch with local fixture media rendered
successfully. The returned file under `storage/tasks/6c3b445e-10a6-4f16-8523-d274609e550c/`
was copied into `data/production/v-mpt-local-smoke/final-1.mp4`; QC passed for
1080×1920, audio and eight-second narration timing. Evidence is in that production
folder's `assembly_result.json` and `qc_report.json`. Subtitles were disabled;
this does not sign off the full subtitle or Jimeng workflow.

G11 integration: quoted Canvas batches now pause before spending, resume reuses
saved script/narration/finals, credit reservations remain separate from USD,
manual replacement does not replay rejected generation, and production defaults
to a QC review stop. Offline integration tests cover these paths and verify
returned final retrieval. No publishing or paid generation has occurred.
Full offline suite: **225 passed in 24.76s**. Frozen schemas/fixtures unchanged.
G6/G8/G12 remain pending their live account, generation, subtitle and review steps.

2026-09-15 recheck: 225 tests passed in 25.60s. Fresh local MPT fixture assembly
passed resolution/audio/duration QC (1080×1920, 8.07 seconds); subtitles disabled.
Canvas login remains pending. Isolated Hypit 0.1.8 installation and one-shot
HypiHub source check passed; its plan/doctor identify missing credentials.
No paid generation occurred. These checks do not sign G6/G7/G8/G12. See
`docs/setup-test-guide.md` and `data/production/setup-test-evidence.json`.

Authorization follow-up: both OAuth flows completed. Canvas account/catalog
checks and one saved five-second Seedance fast quote passed (30 Jimeng credits).
Node ID and native stderr protocol regressions fixed; **229 tests passed in
23.81s**. HypiHub's requested Seedance fast capability passes preflight and its
authenticated rates estimate 142.6 credits / US$0.713 for the matching shot.
Both spends remain unapproved. The user's Chrome canvas editor reports
`draft_reader_too_old`; CLI save/read/quote succeed. G6/G8/G12 remain unsigned.

Approved pilot follow-up (2026-09-15): the user approved both single-shot tests.
Jimeng generated and downloaded one five-second 720×1280 video under a native
30-credit ceiling. Checksum, full FFmpeg decode and M6 intake passed; sampled
frames show steam and camera motion. The manifest records Jimeng provenance and
correctly retains missing shots 1–3. Wait timeout and download failure recovered
using the original submission, without regeneration. New timeout regression
coverage passes; full offline suite **230 passed in 24.40s**.

HypiHub's one matching build failed with HTTP 402 `insufficient_credits` during
submission, with zero outputs. Its receipt is retained; no top-up or repeat
generation occurred. The quoted estimate remains separate from Jimeng credits;
settled charges were not independently verified. Evidence is in
`data/production/setup-test-evidence.json` and the two pilot directories.
G6/G8/G12 remain unsigned pending full asset coverage, real narration/subtitles,
assembly and human review. No publishing took place.

Hypit local editing follow-up (2026-09-15): the global Hypit Skill and local
runtime are installed. The existing Jimeng coffee clip rendered successfully
with two timed titles and original audio: five seconds, 1080×1920, 30 fps, AAC.
Full decode and existing assembly QC pass using the authored five-second timeline
as the duration reference; this is not real narration verification. Encoded frame
review shows both titles and motion; the user's Chrome Studio plays to the final
frame. Listening and creative acceptance remain for the user.

The initial local render failed on Hypit 0.1.8's missing capture-child package
resolution. A version-checked project bootstrap now loads the native resolvers;
an offline child-process import regression passes. The repaired render reused
the existing normalized clip and planned three local requests, zero hosted calls.
No additional generation spend. Full suite: **231 passed in 25.48s**. Evidence:
`data/production/v-jimeng-hypit-pilot/pilot_qc.json`, local build receipts,
`data/production/setup-test-evidence.json`; instructions in
`docs/jimeng-hypit-workflow.md`. G6/G8/G12 remain unsigned for full asset coverage,
narration, speech-aligned captions and operator acceptance.

G7 setup follow-up (2026-09-15): ElevenLabs credential saved privately. Account,
voice list and model discovery return HTTP 200; 30 voices and `eleven_v3` are
listed. No audio generation performed. Voice choice, actual synthesis permissions,
duration validation and blind listening remain pending; G7 stays unsigned.
Sanitized evidence: `data/production/elevenlabs-setup/verification.json`.

Credential-loader follow-up (2026-09-15): root `.env` support and Git exclusions
added following the user's selected credential location. Regression coverage
verifies source precedence, working TOML fallback, path isolation, literal values
and errors that omit credential contents. Full suite **239 passed in 26.22s**.
The new `.env` was empty on disk; Google route/auth/model access and TTS/music
generation remain unverified. Existing ElevenLabs credentials still load.
G7/G8/G12 remain unsigned. See `docs/audio-providers.md`.

- Folder tree per plan: `data/{radar,grill,formats,hooks,production,published,analytics,costs}`, `modules/`, `schemas/`, `tests/fixtures/`, `vendor/`, `config/`, `logs/`, `docs/`
- Vendored: ai-marketing-skills @ `bc84dbc`, MoneyPrinterTurbo v1.3.7 @ `cf5a3ae` (uv sync --frozen, Python 3.11)
- Contracts frozen: 9 schemas × 9 valid fixtures + 1 negative fixture, all round-trip via jsonschema
- Media fixtures generated with ffmpeg (312 KB total): good/bad/zero-byte video, image, 20s/8s voice
- CLI smoke test: `cli.py --help` OK (sources: pexels/pixabay/coverr/volcengine_seedance/ofox/metaso_minimax/openai_image/local confirmed)
