# Jimeng Canvas production backend

## Installation and authorization

Installed on macOS arm64 using `curl -fsSL https://jimeng.jianying.com/canvas-cli | bash`.
Verified binary: `~/.local/bin/dreamina-canvas`, version **1.0.1**, commit **83aeb67**.
Official Skill: `~/.agents/skills/dreamina-canvas-cli/SKILL.md`.
The existing `dreamina` installation and login are preserved. Blender is deferred.

Canvas has separate authorization. Run `dreamina-canvas auth login`, open its
returned link in your logged-in Jimeng browser, and follow the returned
`auth wait` command. Then run `python -m modules.assets doctor`.
The initial authorization challenge expired; account verification and model
discovery remain pending. No media has been generated or credits spent.
Credentials belong to native CLI storage (macOS Keychain); never copy them into
project config or logs. Confirm the intended account in `auth account` and CN
production region in `auth status` before proceeding.

## Reviewed batches

```bash
python -m modules.assets doctor
python -m modules.assets prepare data/production/VIDEO/shot_list.json
# Review every quote, totalMaxCredits and canvas_url before approving:
python -m modules.assets generate VIDEO --credit-ceiling APPROVED_INTEGER
python -m modules.assets status VIDEO
python -m modules.assets resume VIDEO
```

Use `prepare ... --shot 0` for a single pilot within a valid 4–7-shot document.
The pilot should request five seconds. Select a canonical fast Seedance model
from the live catalog with `--video-model` or pin `assets.jimeng.video_model`
in `config/system.toml`; likewise select an image model for mixed batches.
An ambiguous model or unsupported resolution, ratio, mode, count, prompt length,
or duration stops preparation. Videos default to 9:16, 720p, one result; duration
rounds upward within model limits. The live catalog is the authority.

Preparation saves a canvas and typed nodes, then obtains quotes without running
them. Open the returned canvas URL to review the drafts. A quote is not spend
approval. `generate --credit-ceiling` is the explicit operator approval command.
The ceiling covers the entire batch, including amounts reserved by earlier
attempts. Each shot is capped through a native confirmation token. At most one
generation is active across this production directory.

## Recovery and credit accounting

`assets/jimeng_jobs.json` is an atomic, private local journal, separate from the
frozen contracts and the US-dollar ledger. It stores account identity, CLI
version, canvas/node/update/submission/resource identifiers, generation settings,
quotes, approved ceiling, per-shot credit reservations and verified checksums.
Reservations are conservative maximum credit commitments, **not settled charges**.
Native confirmation/authentication tokens are never stored in it or logged.

Submission identifiers are saved before submitting. Accepted, running, unknown,
failed, succeeded and downloaded are distinct states. `status` only reads remote
state. `resume` waits for existing identifiers and retries downloads; it never
submits generation. To start remaining unsubmitted shots, review the remaining
quote and use `generate` with the original batch ceiling. An uncertain operation
blocks subsequent submissions, even if its record cannot be found. Resolve it
in the original canvas; do not automatically retry generation.

A valid manual replacement can satisfy a failed/rejected/invalid shot and allow
the unsubmitted remainder to proceed. The original submission and conservative
credit reservation remain recorded. Removing that replacement restores the
review requirement; it does not turn the original attempt into a fresh job.

Prompt/settings changes require an explicit new video ID. Repeated preparation
reuses the original canvas and nodes. Valid local assets are reused at zero
generation cost. Downloaded outputs use `shot-NN.jimeng.*`; resource ownership,
checksum, actual media kind, resolution and requested duration are checked.

## Manual import and explicit stock substitution

```bash
python -m modules.assets queue path/to/shot_list.json
python -m modules.assets collect VIDEO
python -m modules.assets collect VIDEO --fallback stock
```

Drop files into `data/production/VIDEO/assets/` using `shot-00.mp4`, etc.
Untagged files are manual; `.jimeng.` and `.stock.` identify provenance.
An empty folder reports missing shots without emitting an invalid empty manifest.
No fallback stock is fetched unless explicitly requested. Images cannot satisfy
video shots, and videos must cover the shot's requested length.

## Validation and live gates

Offline boundary tests cover missing CLI/login, account changes, malformed
responses, unsupported parameters, excess credit quotes, partial acceptance,
lost submission responses, restart, download failure, local reuse, provenance,
media mismatches and missing assets. No tests use Jimeng or paid APIs.

Live sequence: verify account/catalog → prepare and quote one five-second shot
→ obtain explicit spend approval → generate/download/inspect → separately quote
and approve a complete 4–7-shot set → validate assembly handoff and local QC.
Publishing remains a separate gate.

Sources: [Canvas CLI guide](https://bytedance.larkoffice.com/wiki/QO66wGahSiakEHkJbxIcNBtDnAc),
[official installer](https://jimeng.jianying.com/canvas-cli), installed CLI schema
and bundled Skill. The supplied `/canvas-cli/install.sh` redirects to a web page.
