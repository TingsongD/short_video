# Short-form outlier discovery tools

Reviewed **2026-09-18**. Scope: whether a tool can find *individual public
videos* whose `views / creator followers` (or YouTube subscribers) is unusually
high, across the main short-form platforms. Sources are official product pages,
official API documentation, and official help centres only. This is a
capability review, not a paid/live accuracy test.

## Bottom line

Use **[Virlo](https://virlo.ai/features/outliers)** as the first paid pilot for
the direct brief: it explicitly defines an outlier as views relative to the
creator's follower count, displays 50x+ videos, and natively searches
TikTok, YouTube, and Instagram. Its documented Fresh/Most Viral and time-range
views, creator/video details, tracking, exports, API, MCP, and seven-day trial
make it the clearest discovery workflow. Its gap is material: it does **not**
document organic Facebook Reels or Snapchat Spotlight coverage.

Pair it with **[Shortimize](https://www.shortimize.com/competitor-analysis-short-form-video)**
for Facebook and Snapchat *watchlists* (and for checking specific competitor
accounts on every major platform), rather than treating it as a global
views/followers-ratio search. Use **[1of10](https://1of10.com/about)** or
**[vidIQ Outliers](https://support.vidiq.com/en/articles/9660010-outliers)**
for a stronger YouTube Shorts research surface. For programmatic, custom
collection—including Chinese/emerging platforms—use the supplied
**[treg](https://treg.to/catalog)** gateway; calculate the ratio locally from
video and profile responses. **[Monid](https://monid.ai/blog/your-agent-watches-tiktok-now)**
is the best low-cost agentic route for the same two-step TikTok calculation,
but currently has less proved all-platform coverage in its public docs.

Do not use a vendor's "outlier score," engagement rate, or view velocity as a
substitute for the requested ratio. Retain it as a separate ranking signal.

## Practical comparison

| Tool | Platforms officially documented for the relevant workflow | Individual-video discovery and filters | Can implement `views / followers`? | Export / automation | Published entry price | Real query assessment |
| --- | --- | --- | --- | --- | --- | --- |
| **Virlo — recommended direct discovery** | TikTok, YouTube, Instagram; Meta **ads**, not organic Facebook, in its developer API. [Outliers](https://virlo.ai/features/outliers), [API](https://dev.virlo.ai/) | Dedicated outlier browser: Fresh Content or Most Viral/time range, 50x+ multiplier; video views/likes/comments/publishing details and creator details. Tracking additionally documents platform, niche, score, date and creator filters plus sort by score/views/recency. [Tracking](https://virlo.ai/features/tracking-center) | **Yes, directly for its 50x+ catalogue**: it says the multiplier is views versus creator follower count. Docs do not establish an arbitrary lower ratio cutoff in the UI; retrieve/export then apply our `> 2x` (or chosen) rule locally. | Excel/CSV/JSON, API, MCP and webhooks are advertised. [Pricing](https://virlo.ai/pricing) | Seven-day free trial; Starter $49/month (2,000 credits), Pro $199/month. | Best direct fit for global discovery on the three highest-value platforms. Validate availability of raw follower fields and query recall in a trial before scheduling. |
| **Shortimize — recommended Facebook/Snap complement** | Public accounts on TikTok, Instagram, YouTube, Facebook, Snapchat and X; its support article names Reels, Shorts, Facebook videos and Snapchat Snaps. [Competitor analysis](https://www.shortimize.com/competitor-analysis-short-form-video), [coverage](https://features.shortimize.com/en/help/articles/2674205-what-platforms-accounts-and-content-types-does-shortimize-support) | Add an account URL; its videos table documents platform/date/collection filters, a views threshold example, sorting, export and drill-down. Its discovery search is by context/hook across viral videos. [Tables](https://help.shortimize.com/articles/7210867-the-videos-and-accounts-tables) | **Only after collection, and follower count must be verified in the returned account data.** Official pages establish views, engagement/virality scores and audience growth, not a documented global views/follower filter or a guaranteed follower column. | API/webhooks/MCP are add-ons on Launch/Scale; Enterprise includes them. | Seven-day trial; Launch $99/month, Scale $249/month. [Pricing](https://www.shortimize.com/pricing) | Best documented way to monitor known FB/Snap competitors and identify their high-view posts; not enough evidence to call it a whole-network ratio finder. |
| **treg — recommended programmable collector** | TikTok, Instagram, YouTube, Facebook and Snapchat, plus Douyin, Kuaishou, Bilibili, RED, Lemon8, WeChat Channels and more. [Catalog](https://treg.to/catalog) | TikTok documents keyword/hashtag/trending feed and video search; Instagram documents hashtag/explore/trending Reels; Facebook documents public-page Reels; Snapchat has public-profile/Spotlight/comment endpoints. [TikTok catalog](https://treg.to/catalog/tiktok), [Instagram catalog](https://treg.to/catalog/instagram), [Facebook catalog](https://treg.to/catalog/facebook), [Snapchat catalog](https://treg.to/catalog/snapchat) | **Yes, but build it:** search videos, request creator profile, then calculate and rank. It is an endpoint gateway—not a ready-made outlier search UI. | API/CLI; pricing and schemas are inspectable before a call. Each social result is obtainable per call/row. [Official reference](https://treg.to/llms.txt) | $1 initial eligible-team credit; social endpoints shown from roughly $0.001. Pay per call/result, no subscription. | Broadest programmable route, including emerging/Chinese platforms. Use a bounded two-call enrichment plan and cache profile counts. |
| **Monid — supplied agentic TikTok route** | Official example proves TikTok; its public article says an agent can move from TikTok search to Instagram, YouTube and web scraping. It does not prove Facebook/Snapchat organic coverage. [TikTok workflow](https://monid.ai/blog/your-agent-watches-tiktok-now) | TikTok keyword search returns ranked videos with plays, likes, shares, author and on-screen hook; a second creator-history query returns followers and recent posts. | **Yes, explicitly on TikTok:** its worked method compares a video's plays to creator followers and median. This is calculated by the agent; it is not a prebuilt multi-platform dashboard filter. | API/CLI/MCP. `discover` finds candidate endpoints, `inspect` returns input schema/price, and `run` executes it. [How it works](https://monid.ai/docs/guide/how-it-works), [discover API](https://monid.ai/docs/api/discover), [inspect API](https://monid.ai/docs/api/inspect) | Pay-as-you-go (price exposed per endpoint); its TikTok example quotes $0.0015 each for search and history. [Pricing model](https://monid.ai/docs/guide/how-it-works) | A very inexpensive exploratory TikTok implementation. Inspect the exact provider response before relying on other platform coverage or bulk exports. |
| **1of10 — YouTube specialist** | YouTube, including Shorts in its extension. [About](https://1of10.com/about), [extension](https://1of10.com/chrome-extension) | Outlier Finder searches videos outperforming the channel average; filters include outlier score, views, subscriber count, niche, language, length and recency. | **Yes, via returned/viewable counts**, but its native score is video versus channel average—not the requested denominator. Filter/recalculate ratio separately. | Web/Chrome extension; no public API. | Free tier; Basic $29/month annual billing, Pro $69/month annual billing. [Pricing](https://1of10.com/pricing) | Best YouTube research UX for finding small-channel winners, but it cannot cover the non-YouTube brief. |
| **vidIQ Outliers — YouTube specialist** | YouTube, with separate Video and Shorts Outlier tabs. [Official guide](https://support.vidiq.com/en/articles/9660010-outliers) | Search/keyword research; filters for score, subscriber count, VPH, length and publishing date. Details include views, subscriber amount and channel average views. | **Yes, via details**, but again calculate `views / subscribers` ourselves; vidIQ's score is baseline performance. | Web/mobile/extension; no public ingestion API established in reviewed docs. | Free/basic lacks advanced filters; paid tiers unlock them. [Official guide](https://support.vidiq.com/en/articles/9660010-outliers) | Excellent second opinion for YouTube Shorts, especially when recency/VPH matters. |
| **Exolyt — TikTok analyst alternative** | TikTok. [Account overview](https://exolyt.com/features/account-overview) | Account/video analytics with filters and performance history; video-level investigation and exports are documented. [Video performance](https://exolyt.com/features/video-performance) | **Likely after retrieval**: follower, view and video performance history are documented, but no official one-click global views/follower cutoff was found. | CSV, Google Sheets and Airtable exports are advertised. | Trial advertised; confirm current checkout price. | A good TikTok watchlist/analysis alternative when a team needs trend history and exports over a global discovery feed. |

## Platform reality and recommended workflow

| Platform | First tool to use | Why / limitation |
| --- | --- | --- |
| YouTube Shorts | Virlo for cross-platform seed search; 1of10 or vidIQ for deeper review; official Data API for final enrichment. | YouTube's official API exposes public video stats and channel `subscriberCount` (rounded to three significant figures), so it can validate the ratio. Search can order by view count, but its `short` duration means under four minutes—not a Shorts-only guarantee. [Channel statistics](https://developers.google.com/youtube/v3/docs/channels), [search](https://developers.google.com/youtube/v3/docs/search/list) |
| TikTok | Virlo for direct 50x discovery; Monid/treg for a low-cost custom ratio scan; Exolyt for tracked creators. | TikTok's official Research API can query public videos and public account `follower_count`, but requires approved non-profit/academic research access and its search data can lag (new videos up to 48 hours; statistics up to 10 days). It is not the practical real-time commercial default. [Eligibility](https://developers.tiktok.com/docs/en/about-research-api), [video query](https://developers.tiktok.com/docs/en/research-api-specs-query-videos), [freshness limits](https://developers.tiktok.com/docs/en/research-api-faq) |
| Instagram Reels | Virlo for broad discovery; Shortimize for competitors; treg/Monid only after endpoint inspection. | Virlo explicitly covers Instagram in its outlier discovery; Shortimize tracks known Reels accounts. |
| Facebook Reels | Shortimize for known public accounts; treg for endpoint-driven collection. | Neither Virlo's organic outlier surface nor Monid's public TikTok example establishes Facebook Reels discovery. Treat Facebook as a watchlist/custom-data workflow until a live pilot proves broader search. |
| Snapchat Spotlight | Shortimize for known public accounts; treg's three Snapchat endpoints for custom collection. | Official Shortimize material covers Snapchat Snaps; treg exposes public profiles, Spotlight videos and comments. Neither document establishes a global numeric follower-ratio filter. |
| Douyin / RED / Kuaishou / Bilibili / Lemon8 / WeChat Channels | treg. | It is the only reviewed source that explicitly catalogs searchable public data across this set. The same ratio calculation and source-specific field checks apply. |

## Pilot design before committing a subscription

1. Use the **same five topics** on Virlo, Shortimize and the existing/default
   YouTube route. Download/export the raw results where permitted.
2. Preserve platform, canonical video URL/ID, creator ID, `views`, `followers`,
   publication time, observation time, tool score and raw source response.
3. Apply the strict rule locally: `views / followers > threshold` (never divide
   by zero; mark hidden/missing audience counts unknown). Keep views versus
   creator median as a separate field.
4. Manually check 20 qualifying videos in the native app: video is public and
   short-form, counts are plausible, account audience is present, and it is not
   a photo/slideshow/ad unless intentionally included. This catches stale
   profiles and product-score ambiguity.
5. Score each source on qualifying results per dollar, result freshness,
   missing denominator rate, duplicate creator rate, and export/API replay.
   Only then schedule a paid weekly scan.

The important architectural point: no reviewed tool has official evidence of a
single, reliable all-platform search with arbitrary `views / followers > N`
filter. The robust solution is **direct discovery where Virlo supports it,
plus normalized raw-data enrichment and a local ratio calculation** for every
other platform.
