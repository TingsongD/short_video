# Using Jimeng and SuperGrok with Hypit

Checked 2026-09-15 against installed Hypit 0.1.8 and current upstream docs.
The user confirmed their Grok plan is SuperGrok.

## Conclusion

Use the working official Jimeng Canvas CLI to generate assets on the existing
Jimeng account, then import its verified files into local Hypit compositions.
A custom Hypit Provider can later call that same CLI through our existing M6
adapter. A reverse-engineered Jimeng API is unnecessary for this path.

SuperGrok video through a local gateway is a plausible second route, but has not
been verified on this account. Hypit's hosted HypiHub account cannot inherit
Jimeng or Grok credits by receiving their credentials. BYOK chooses another
compatible Provider in the local runtime.

## What is verified locally

- Canvas CLI 1.0.1 generated the approved five-second, 720×1280 pilot on the
  existing Jimeng account under a 30-credit ceiling. Download, checksum, media
  intake and full decode passed. See `setup-test-guide.md` and the private
  `data/production/v-jimeng-cli-pilot/pilot_qc.json`.
- HypiHub's separate account had zero credits and rejected its pilot with HTTP
  402 `insufficient_credits`. This does not block local Hypit media imports.
- Official Grok CLI 1.0.30 is installed. A read-only `grok models` succeeded,
  reporting a grok.com login and models `grok-4.6` and `grok-4.5`. That is evidence
  of account/model access, not a video-generation test or proof of video limits.
- No new generation, gateway installation, credential export or funding occurred
  during this review. Local Hypit rendering remains untested.

## Hypit integration boundary

[Hypit's provider guide](https://hypit.ai/guide/providers/) explicitly supports
project-owned Providers. A credential supplies authorization; the Provider must
implement the service's actual protocol. The installed distribution includes
HypiHub and local Providers, without a ready-made Jimeng Canvas or direct xAI
subscription Provider.

The installed HypiHub adapter submits to `/v1/videos`, polls `/v1/jobs/{id}` and
collects `/v1/jobs/{id}/assets`. It also uses HypiHub-specific model names,
catalogue fields, uploads and pricing. The
[official xAI video API](https://docs.x.ai/developers/model-capabilities/video/generation)
instead submits to `/v1/videos/generations` and polls `/v1/videos/{request_id}`.
An OpenAI-compatible chat endpoint is insufficient to make these video protocols
interchangeable.

### Jimeng

Immediate workflow: existing M6 Canvas generation → validated local MP4 →
Hypit `media:Video` input → local composition/rendering → existing QC.
The [media package](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/media/README.md)
supports source media declarations without paid generation.

For generation inside Hypit, implement a Provider around the existing M6
adapter. Preserve reviewed quotes, native credit ceilings, durable submission
IDs, one active generation and resume without re-submission. A new Hypit Build
must not automatically create a second Canvas generation. This is an integration
design, not an implemented Provider.

The [jimeng-free-api-all project](https://github.com/zhizinan1997/jimeng-free-api-all)
documents a reverse API using account session credentials. It adds another
web-protocol dependency while our official CLI path already works. Its name
does not establish that paid generation is free or unlimited.

### SuperGrok

The [current official FAQ](https://docs.x.ai/grok/faq#usage--limits) describes a
shared subscription allowance and lists API among the usage categories. Avoid
the blanket claim that subscriptions can never power programmatic access.
The [official CLI authentication guide](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md)
documents browser/OAuth login separately from developer API keys. Actual access
and billing depend on the selected route and account entitlement.

[Grok2API](https://github.com/chenyme/grok2api) documents both subscription OAuth
and web-session routes, including `grok-imagine-video-1.5` for Super/paid Build
accounts. This is the gateway maintainer's compatibility claim, not first-party
support or a result verified on this user's account.

If evaluated, use a separate OAuth authorization owned by the local gateway and
pin its subscription route. Its documentation warns against sharing rotating
Build credentials with another active client. Discover available video models
and quota before a reviewed one-shot test; do not silently switch to developer
API billing or HypiHub when the subscription route fails.

A Hypit Provider would map submit/status/download operations and persist job
receipts. Model identity needs care: installed Hypit exposes standard Grok video
(6–30 seconds) and **1.5 preview** (1–15 seconds). Stable **1.5** must not be
silently labelled as preview; add its model definition if needed. These are
Hypit package interfaces, not proof of the account's live limits.

## Recommended order

1. Prove Hypit composition using the already downloaded Jimeng pilot, with only
   local endpoints selected. This consumes no further generation credits.
2. Add a Canvas Provider only if generation inside Hypit is useful enough to
   justify its extra recovery and approval integration.
3. Evaluate SuperGrok OAuth video separately, beginning with account/catalogue
   checks. Review its exact requested model and quota impact before one new test.

No HypiHub top-up is required for the Jimeng/local-render workflow.
