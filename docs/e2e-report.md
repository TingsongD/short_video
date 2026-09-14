# E2E Report — first real video through the full loop (G12)

Filled during the live run. Gate G12 criteria (BUILD_PLAN.md §3 M12):

- [ ] real 1080×1920 video with synced subtitles published on test channel
- [ ] total human time ≤ 30 min
- [ ] variable cost within cap ($0.30/video testing target, $25/week hard cap)
- [ ] 48h readback present

## Run

| Field | Value |
|---|---|
| date | _pending live run_ |
| idea_id | |
| video_id | |
| yt url | |
| run record | `logs/runs/…` |

## Stage timings (from run record `duration_s`)

| Stage | Seconds | Notes |
|---|---|---|
| hook | | |
| script | | LLM call |
| assets | | Lane B manual drop time counted in human time |
| voice | | ElevenLabs call |
| assemble | | MoneyPrinterTurbo |
| qc | | |
| publish | | approval gate + upload |
| **total** | | |

## Human time log

| Step | Minutes |
|---|---|
| approve idea after grill | |
| approve spend (`run.sh approve spend`) | |
| Jimeng Lane B asset generation + drop | |
| publish approval | |
| review | |
| **total** | |

## Cost (from `data/costs/ledger.json`)

| Service | Units | Cost |
|---|---|---|
| llm | | |
| elevenlabs | | |
| **total** | | |

## 48h readback

_pending `run.sh readback` after publish + 48h_

| views | AVD% | CTR | verdict |
|---|---|---|---|

## Failure drills status (offline — see tests/test_failure_drills.py)

- [x] dead LLM → fails at `script`
- [x] dead TTS → fails at `voice`
- [x] empty Jimeng Lane B → fails at `assets`
- [x] no finals from MPT → fails at `assemble`
- [x] bad QC video → fails at `qc`
- [x] publish unapproved → fails at `publish`
- [x] killed idea → refused before stage 1
- [x] dead YT quota → weekly fails at `radar`

## Batch go/no-go

_pending — do NOT start batch production until this report is complete and reviewed_
