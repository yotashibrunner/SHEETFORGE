# SheetForge — private template forge

A tool **you** run to stamp out a catalog of clean, sell-worthy spreadsheet
templates. Not a SaaS. No customer-facing app, no proxy, no API key to protect —
it runs on your machine with your key and outputs finished `.xlsx` files you list
on Etsy / Gumroad / your own store.

## The one idea that fixes v1
v1 let the LLM emit cells and formulas → broken refs, dead charts, 1-star reviews.

This version splits the job:

| Step | Who | Output |
|------|-----|--------|
| 1. Write the **spec** | LLM (`forge_spec.py`) | JSON: tabs, columns, formula *patterns*, copy |
| 2. **Render** the workbook | code (`forge_build.py`) | clean `.xlsx` — formulas built by code |
| 3. **QA gate** | LibreOffice recalc | rejects any file with `#REF!/#DIV0!/...` |
| 4. Preview + listing | LibreOffice + LLM | PDF preview, Etsy title/tags/description |

Formulas come from code, so they can't break. The LLM only supplies labels,
structure, and formula *patterns* — never raw cells.

## Requirements
- **Python deps:** `pip install -r requirements.txt` (requests, pytrends, anthropic, openpyxl).
- **LibreOffice** — required for the QA gate (`scripts/recalc.py` recalculates formulas
  headlessly) and the PDF previews. `soffice` must be on your `PATH`.
  - Install: `winget install --id TheDocumentFoundation.LibreOffice` (Windows),
    `brew install --cask libreoffice` (macOS), or your distro's `libreoffice` package.
  - Windows note: the installer does **not** add `soffice` to `PATH`. Either prepend
    `C:\Program Files\LibreOffice\program` to `PATH`, or point `recalc.py` straight at it
    with `setx SOFFICE_BIN "C:\Program Files\LibreOffice\program\soffice.exe"`.
  - Without LibreOffice the QA gate fails closed (`total_errors: -1`) and rejects every
    build — by design, so nothing ships unverified.
- **`ANTHROPIC_API_KEY`** — your key, in the environment (used by the spec + listing steps).

## Launch (no command line)
- **`SheetForge.cmd`** — double-click for a menu-driven console launcher.
- **`SheetForge.exe`** — a windowed app (buttons + live log + API-key field). Build it
  once with `.\build_exe.ps1` (PyInstaller), then double-click the resulting
  `SheetForge.exe`. Keep it in this folder — it drives the project's venv Python and
  still needs LibreOffice installed (see Requirements). Drop an `icon.ico` in the root
  before building to give it a custom icon.

## Run
```bash
export ANTHROPIC_API_KEY=sk-ant-...

# one template
python forge_spec.py "DIY mechanics" "Vehicle Maintenance Log"
python forge_build.py specs/vehicle_maintenance_log.json maintenance.xlsx
python scripts/recalc.py maintenance.xlsx        # must report total_errors: 0

# whole catalog (spec -> build -> QA -> PDF -> listing copy)
python forge_batch.py catalog.json               # -> ./catalog/
```

## Files
- `forge_build.py` — deterministic spec → xlsx renderer (the core). Embedded demo spec included.
- `forge_spec.py` — LLM writes the JSON spec. The `CONTRACT` string is the schema + hard rules.
- `forge_batch.py` — niche list → finished catalog (xlsx + PDF + listing.txt), with the QA gate.
- `catalog.json` — starter niche/template pairs in your verticals.
- `scripts/recalc.py` — LibreOffice formula recalculation + error scan (the QA gate).

## Strategy notes
- Sell **vertical** niches you own (reseller, farm, mechanic, POD) — generic budget
  templates have ~10,000 competitors; these have few and command higher prices.
- Hand-open the first file in each niche before listing. The QA gate catches broken
  formulas; only your eye catches "is this actually useful and worth $12."
- One spec → many variants (year, currency, color) = more SKUs from one build.
```
