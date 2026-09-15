# Test the current setup, then HypiHub

Checked on 2026-09-15. Start with the local check, then one Jimeng generation,
then the matching HypiHub generation. Each live generation needs its own reviewed
cost. Hypit is the editing/runtime tool; HypiHub is its hosted generation service.

## Current results

| Check | Result |
| --- | --- |
| Offline suite | 229 passed in 23.81 seconds after live-protocol fixes |
| Fresh MoneyPrinterTurbo render | Passed: 1080×1920, 8.07 seconds, audio present |
| Smoke-test content | Synthetic fixture media, subtitles disabled; not a finished creative video |
| Jimeng Canvas CLI | 1.0.1 authorized; account/catalog verified; five-second pilot quoted at 30 Jimeng credits |
| Real script/narration | LLM and ElevenLabs keys missing; channel voice not selected |
| Hypit executable | 0.1.8 installed in `vendor/hypit-runtime`, isolated from production |
| HypiHub draft | Valid source; one five-second, 720p, 9:16 Seedance fast request |
| HypiHub readiness | Authorized; pilot preflight passes; estimated 142.6 credits / US$0.713 from authenticated rates |
| Paid work | No generation submitted or credits spent in this test |

The diagnostic evidence is saved in `data/production/setup-test-evidence.json`.
Both generation approvals are still pending. Chrome is the user's selected
browser. Its Canvas editor reports `draft_reader_too_old` despite one refresh;
the CLI successfully saved, read and quoted the draft.

## 1. Repeat the current local test

Open a terminal in this project:

```bash
cd '/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube'
make test
.venv/bin/python -m modules.assemble run data/production/v-mpt-local-smoke/batch.json
.venv/bin/python -m modules.assemble qc data/production/v-mpt-local-smoke/final-1.mp4 --voice-s 8
open data/production/v-mpt-local-smoke/final-1.mp4
```

Expected: all tests pass, the renderer exits successfully, and QC reports a pass.
The video shows test patterns and includes synthetic audio. This checks the real
renderer and output retrieval. It does not check narration quality, subtitles,
live generation, research, or publishing. Re-running replaces this smoke-test final.

## 2. Test Jimeng generation

### Connect the intended account

Complete the authorization page already opened/provided in the conversation.
An active login wait can finish that same challenge. If the challenge has expired,
start a fresh login and use its newly returned URL and device code:

```bash
dreamina-canvas auth status
dreamina-canvas auth login
dreamina-canvas auth wait --device-code DEVICE_CODE_FROM_LOGIN --timeout 10m
dreamina-canvas auth account
.venv/bin/python -m modules.assets doctor
```

Do not start another login while one is still pending. Expected: logged in to
the intended account, region `cn`, environment `prod`, and video/image model
discovery succeeds. Browser login alone does not authorize Canvas.

If the browser says “授权失败 / 无法加载授权请求，请重试” (authorization
failed / unable to load the request), check the challenge's `expiresAt` and the
CLI wait result first. On 2026-09-15 the request expired at 10:19 Vancouver time,
before the 10:27 browser attempt; the CLI confirmed `cli.login_expired`. Start
one fresh login after expiry, use its new page promptly, and keep its matching
wait running. Refreshing an expired page does not renew the request. Do not
clear the working dreamina login or use `--force` for an expired challenge.

### Prepare one shot and read the quote

The existing test script has four shots. Prepare only shot 0, a five-second
coffee cup with rising steam:

```bash
.venv/bin/python -m modules.assets prepare data/production/v-jimeng-cli-pilot/shot_list.json --shot 0 --video-model seedance_2.0_fast_vip
```

This saves a draft and obtains a quote; it does not generate. Open the returned
canvas URL and review the prompt, model, duration, resolution, each quote and
`totalMaxCredits`. If automatic model selection is ambiguous, repeat preparation
with `--video-model` and the exact suitable model returned by doctor.

### Generate only after approving the displayed ceiling

Replace `APPROVED_INTEGER` with the actual reviewed credit ceiling:

```bash
.venv/bin/python -m modules.assets generate v-jimeng-cli-pilot --credit-ceiling APPROVED_INTEGER
.venv/bin/python -m modules.assets status v-jimeng-cli-pilot
.venv/bin/python -m modules.assets resume v-jimeng-cli-pilot
```

Use status/resume while an existing generation is pending. They do not submit
new work. Inspect `data/production/v-jimeng-cli-pilot/assets/shot-00.jimeng.*`.
Expected: a readable portrait video at least five seconds long, minimum dimension
720 pixels, smooth camera motion and visible steam, with no unwanted text/logos.

Passing this pilot validates one selected shot only. It does not establish full
four-shot coverage. Use a new video ID when expanding to the full batch: the
prepared selection is part of this adapter's saved generation identity. Reuse
the accepted clip where appropriate and quote only missing assets.

## 3. Test the matching shot through HypiHub

The executable, project and source files are already prepared. In a new terminal:

```bash
cd '/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube'
HYPIT_TEST_CLI="$PWD/vendor/hypit-runtime/node_modules/.bin/hypit"
cd data/production/v-hypihub-pilot
"$HYPIT_TEST_CLI" --version
"$HYPIT_TEST_CLI" auth status hypihub.default
```

The active sign-in launched from this conversation can finish in the browser.
If no login is pending and the account is still unconfigured, run:

```bash
"$HYPIT_TEST_CLI" auth login hypihub.default
```

Keep that terminal open until it reports success. Confirm the intended account
in the browser. Hypit stores credentials through its native macOS Keychain flow;
no key needs to be pasted into chat or the project.

### Verify access and inspect the exact work and price

```bash
"$HYPIT_TEST_CLI" doctor --endpoint hypihub.default --json
"$HYPIT_TEST_CLI" plan pilot.svrun --json
"$HYPIT_TEST_CLI" pricing pilot.svrun --json
```

Expected: authentication and the requested capability are usable, preflight
passes, exactly one provider request, five seconds,
720p, 9:16, no generated audio, and the intended HypiHub account/model is usable.
The current profile selects only HypiHub and limits it to one concurrent request.
It does not prepare Chrome, WhisperX or other local rendering services.

The authenticated check on 2026-09-15 found two unavailable unrelated routes
(Grok 1.5 Preview and Mimo voice clone) in the profile-wide doctor audit. Neither
is requested by this pilot. Its Seedance fast preflight passes and authenticated
pricing succeeds. Do not confuse unrelated capability warnings with an expired
login; errors affecting Seedance or authentication would block this test.

For this exact 720p prompt-only request, the authenticated rate is **28.52
HypiHub credits/second**, so five seconds is estimated at **142.6 credits**, or
**US$0.713** using the returned 200 credits/USD conversion. This is an estimate,
not a server-enforced ceiling or a record of a charge. Refresh pricing before
submission; keep HypiHub and Jimeng credit accounting separate.

Review the authenticated pricing document and the account's balance/plan before
authorizing the single clip. `pricing` provides rates, not a guaranteed total.
Hypit has no native credit-ceiling flag equivalent to our Canvas adapter. Do not
start a build if its applicable cost cannot be established. A subscription/top-up
is a separate purchase decision; neither has been made here.

### Submit once, after spend approval

```bash
"$HYPIT_TEST_CLI" runtime up --endpoint hypihub.default
"$HYPIT_TEST_CLI" build pilot.svrun --json > submission.json
```

Record the build ID returned in `submission.json`. Every `build` invocation is
a new execution attempt. If submission is interrupted, inspect `builds`, status
and receipts before doing anything else; do not repeat build as a polling command.

```bash
"$HYPIT_TEST_CLI" status BUILD_ID --watch --max-wait-ms 45000
"$HYPIT_TEST_CLI" inspect BUILD_ID
mkdir -p output
"$HYPIT_TEST_CLI" get BUILD_ID --output pilot.video --to output/shot-00.mp4
open output/shot-00.mp4
```

Wait for successful completion before export. `get` refuses an existing target;
choose a fresh output path when exporting a different result. Check the raw clip:

```bash
ffprobe -v error -show_entries stream=codec_type,width,height -show_entries format=duration,size -of json output/shot-00.mp4
```

Expected: portrait framing, both dimensions at least 720 pixels, duration close
to five seconds, a nonempty playable MP4, and the intended coffee-cup motion.
Audio was disabled, so its absence is expected. Compare with Jimeng for prompt
adherence, motion, completion time, recovery and actual charged cost. This is an
asset test; our final-video QC expects 1080×1920 with narration and should not be
applied unchanged to a silent 720p source clip.

## 4. Finish the full workflow after the single-shot comparison

- Supply the script LLM configuration and ElevenLabs key in the existing ignored
  `config/secrets.toml`, and select `[voice].voice_id` in `config/system.toml`.
  The remaining live-system credentials are YouTube Data API, optional Pexels
  for stock fallback, and the publishing/analytics OAuth account. The single-shot
  tests above do not need them.
- Prepare/approve a full 4–7-shot set under a new video ID, reusing accepted media.
  Use the saved script to avoid a new LLM call when possible.
- Generate one approved real narration, verify its measured duration, and check
  footage coverage before assembly. Validate the actual subtitle font/model setup.
- Render with subtitles enabled, watch the hook/order/captions/audio and run QC.
  Stop for review before publishing. See [production resume](production-resume.md).

Testing Hypit's local editor/rendering is a separate comparison: use the same
accepted clips/narration in a short composition with captions and one callout.
That rendering runtime has not been prepared or tested by this generation-only setup.

Sources: [Hypit installation](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/skills/hypit/references/environment/distribution.md),
[HypiHub provider](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/provider-hypihub/README.md),
[build and recovery commands](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/run.md),
[public pricing](https://hypit.ai/commercial/pricing/).
