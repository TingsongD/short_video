# Vendored Dependencies — Pinned Versions

`vendor/` is gitignored. Re-create with:

```bash
cd vendor
git clone --depth 1 https://github.com/ericosiu/ai-marketing-skills.git
git clone --depth 1 --branch v1.3.7 https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo && uv python install 3.11 && uv sync --frozen
```

| Repo | Version | Commit | Purpose |
|---|---|---|---|
| ericosiu/ai-marketing-skills | main @ 2026-09-14 | `bc84dbc0c3e453fe9b0c1c7a5f95d8da223289c6` | M1 radar base (`yt-competitive-analysis`), M2 grill (`shortform-idea-grill`), M3 formats (`shortform-format-library`) |
| harry0703/MoneyPrinterTurbo | v1.3.7 | `cf5a3aedad1741d012152d355aa909d224fc4557` | M8 assembly engine (CLI batch mode, local materials, 9:16) |

Skills actually used from ai-marketing-skills: `yt-competitive-analysis/`, `shortform-idea-grill/`,
`shortform-format-library/`. Rest of the repo is reference only.
