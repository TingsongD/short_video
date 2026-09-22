# Flash-cut qualification matrix

Updated 2026-09-22. Qualification is specific to a route, model, payload,
profile, input mode and expiry. A successful run or a single source does not
promote a route globally.

| Component / route | Bound version or model | Current status | Scope and evidence | Remaining limit |
| --- | --- | --- | --- | --- |
| Dense visual helper | `PE-Core-S16-384`; source `3e352c…`; checkpoint `ccc834…`; CPU FP32 | **locally qualified** | Every decoded position; restart-safe 256-frame chunks; 27 helper tests and retained synthetic benchmark | Embeddings prove resemblance, not identity; MPS unqualified |
| Audio measurement | `audio_events.v1`, 48 kHz | **locally qualified** | Silence, weak/clear rhythm, antiphase, buildup, chunk seams and offsets covered offline | Events remain measurements; unreliable rhythm is valid |
| AV fusion | `av_fusion.v1` | **locally qualified** | Two-frame event, continuous footage, callback, quiet boundaries and AV disagreement covered offline | No semantic scene/drop claim from signal alone |
| Selected source media | `selected_media.v2` in future `flashcut_policy.v3` | **locally qualified; live payload unqualified** | Original-dimension JPEG evidence, at-most-1280-pixel clock-verified MP4 windows/overview, hard 14 MiB overview limit; three unpaid full-source quotes passed, including 1,869/1,869 frames and 10 initial bounded Gemini requests for the rapid seed | Compression changes picture pixels; exact frames remain indexed by source PTS/hash; live Gemini acceptance is separate |
| Jev advisory | `jev-1.13.0`, `optional_evidence.v1`, text only | **shadow only; active unqualified** | Exact AVv run/source acceptance scope through `2026-09-22T23:59:59Z`; three historical responses retained all 78 optional candidates | Only 1/9 labeled cases; no reduction or net benefit; dated price expires |
| Gemini flash-cut understanding | `gemini-3.8-flash`, `flashcut_understanding.v1`, future `flashcut_analysis_plan.v2` | **single-run legacy acceptance; v3 media unqualified live** | Exact AVv run/source binding through `2026-09-22T23:59:59Z`; future JPEG/proxy/window requests fit the local route limits on three retained seeds | Not globally or multi-seed qualified; fresh pricing/auth and live payload acceptance required |
| Final temporal QC | `flashcut_temporal_qc.v1` in `flashcut_policy.v2` | **qualified offline for future runs** | All decoded output PTS, final-speech phrase schedule and required brief-interval occupancy; real A/B/C/D Hypit path passed | No semantic identity, pixel OCR or lip-sync claim; v1 history unchanged |
| Native semantic authoring | `@factory/aligned-speech`; `hypit_primary.v1` | **locally qualified** | Real local native Hypit A/B/C/D render path passed with one frozen premix and no extra alignment call | Local qualification is not a provider-quality guarantee |
| FFmpeg render fallback | current `ffmpeg_fast` path | **locally qualified** | Existing actual fixture renders verify frame/audio/provenance agreement | Not used to claim Hypit semantic parity beyond tested fixtures |
| Vertex text-to-video | saved configured model, `text` input | **live-qualified until 2026-10-18** | Dated capability/operation evidence in `data/factory/qualification/` | Provider latency/quality remains variable; normal quote/authority required |
| Vertex image-reference video | `reference_to_video`, `image_ref` | **implemented offline; disabled** | Variant-specific anchors, hashes, provenance, invalidation and mock route checks exist | Requires separately authorized live qualification; no text-only fallback |
| ElevenLabs narration | `eleven_v3` | **live-qualified until 2026-10-18** | Saved qualification evidence; bounded speech repair and final alignment checks | Credits remain separately bounded; no invented USD conversion |
| Generated music | `music_v1` | **live-qualified until 2026-10-18** | Saved quote/operation evidence | Separate credit authorization required when used |
| Drive delivery | configured Drive account/destination | **live-qualified until 2026-10-18** | Verified historical deliveries and saved qualification evidence | Exact revision/file/checksum reconciliation remains mandatory |
| `flashcut_hypit.v1` profile | new runs save `flashcut_policy.v3`; v1/v2 records retain their exact policies | **deployed locally; offline-qualified only** | Complete backend 1,573 passed/7 helper skips; separate helper 27 passed; frontend 73 passed/build; actual local Hypit/FFmpeg 16 passed/no skips; three full-source unpaid preflights; idle rollout and protected-state checks passed | Gemini v3 media and multi-seed quality remain unqualified live. Fresh pricing and authority are required; this is not unattended production readiness. |

## Labeled offline case map

| Required case | Authoritative offline evidence |
| --- | --- |
| Rapid cuts / two-frame event | `tests/helper/test_flashcut_benchmark_matrix.py`; retained physical two-frame benchmark in `scripts/flashcut-benchmark.py` |
| Continuous footage | Matrix test proves no invented visual change and mandatory boundary coverage |
| Repeated callback | Matrix and recurrence tests retain callback as visual resemblance only |
| Quiet setup/payoff | First/last mandatory coverage in matrix and synthetic benchmark |
| VFR timing | `tests/helper/test_flashcut_clock.py` verifies native decoded positions |
| Silence | Audio matrix reports measured silence without fabricated rhythm |
| Weak rhythm | Audio matrix retains `rhythm_unreliable` and no beat grid |
| Clear beats | Audio matrix detects repeated stable onset candidates at the labeled period |
| Audiovisual disagreement | Fusion matrix preserves both timestamps and makes no scene/drop claim |

The fixture matrix qualifies the deterministic local measurement path. It does
not qualify Jev active filtering or broad Gemini/video-generation quality. See
[Jev shadow benchmark](JEV-SHADOW-BENCHMARK-2026-09-22.md) and the
[live-only acceptance checklist](FLASHCUT-LIVE-ONLY-ACCEPTANCE.md) before any
further paid acceptance work. That checklist is not spending authorization.
