# Manual publish checklist (M9 Lane 1, default)

Channel identity (once, before first post):
- [ ] Name/avatar/description consistent with the niche — this channel is
      not a generalist dump
- [ ] No claims of being a human creator; keep the account niche-clean

Per video:
- [ ] QC passed (`python -m modules.assemble qc <final.mp4>`) and operator
      watched it: subtitles synced, hook shot first, voice over BGM clear
- [ ] Upload to YouTube as Short (9:16 is auto-detected)
- [ ] Title/caption/hashtags from `python -m modules.publish meta ...`
- [ ] Cadence: ≤ 2 posts/day/channel — `record` enforces it and blocks
- [ ] After publish: `python -m modules.publish record <video_id>
      --youtube-id <ID> --idea <idea_id> --format <fmt> --niche <niche>`
      — the readback pipeline depends on this file existing
