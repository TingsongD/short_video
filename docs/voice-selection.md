# Voice audition — pick ONE channel voice (M7)

Audition 3 ElevenLabs voices on the same 20s script, blind-listen, pick one.
Pin the winner in `config/system.toml` → `[voice].voice_id`.

| Candidate | voice_id | Notes |
|---|---|---|
| A — warm narrator (e.g. "Adam"-class deep male) | | |
| B — bright explainer (fast, high clarity) | | |
| C — calm storyteller (mystery/history lean) | | |

Script for audition: use `tests/fixtures/contracts/shot_list.sample.json`
`voice_text` — it's already TTS-clean.

Checklist:
- [ ] 3 samples generated (mp3, mp3_44100_128)
- [ ] Blind listen vs Edge TTS baseline — ElevenLabs clearly preferred (G7)
- [ ] Winner pinned in system.toml; characters used logged to cost ledger
- [ ] `voice_id` set → `python -m modules.voice` unblocked
