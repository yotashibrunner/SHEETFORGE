"""
forge_spec.py — the ONLY place the LLM touches the build.

It writes a structured SPEC (labels, columns, formula *patterns*, copy).
forge_build.py renders it deterministically, so formulas never break.

Run locally with your own key:
    export ANTHROPIC_API_KEY=sk-ant-...
    python forge_spec.py "reseller bookkeeping" "Monthly Profit & Loss Tracker"
"""
import os, sys, json, urllib.request

MODEL = os.environ.get("FORGE_MODEL", "claude-sonnet-4-6")

CONTRACT = r"""
You design premium spreadsheet templates sold as digital downloads.
Return ONLY valid JSON (no prose, no markdown fences) matching this schema:

{
  "title": str, "brand": "SheetForge", "accent": "<6-hex>",
  "sheets": [
    { "name": str, "rows": int, "autofilter": bool(optional),
      "hide_cols": [colLetter](optional),
      "columns": [
        { "header": str,
          "type": "input" | "formula" | "seed" | "text",
          "format": "currency"|"currency0"|"percent"|"int"|"date"|"text",
          "width": int(optional),
          "formula": "=...{row}..."   // ONLY for type=formula; use {row} for the row number
          "link": true,               // OPTIONAL: set true if the formula references ANOTHER sheet
          "values": [str,...]         // ONLY for type=seed (pre-filled labels like month names)
        }
      ]
    }
  ],
  "dashboard": {
    "title": str, "subtitle": str,
    "kpis": [ { "label": str, "format": "currency0"|"percent"|"int", "formula": "=..." } ],
    "chart": { "title": str, "sheet": str, "val_col": int, "cat_col": int, "max_row": int }
  },
  "instructions": [ str, ... ]
}

HARD RULES (non-negotiable — these are why this product doesn't get 1-star reviews):
1. Input cells the user fills = type "input". Never pre-fill them with fake numbers.
2. Every total/derived value = type "formula" with a real Excel formula using {row}.
3. Wrap EVERYTHING that can error in IFERROR — both division (IFERROR(...,0) to avoid
   #DIV/0!) and EVERY lookup, e.g. VLOOKUP/HLOOKUP/MATCH/INDEX-MATCH (IFERROR(...,"")
   for text results, IFERROR(...,0) for numeric). A template ships with blank input
   cells, so an unguarded lookup is #N/A on its very first row.
   Use IFERROR, NEVER IFNA — and use ONLY classic Excel-2007 functions. The builder
   writes formulas without the _xlfn. prefix, so post-2007 functions (IFNA, XLOOKUP,
   IFS, SWITCH, TEXTJOIN, XMATCH) are written unrecognizably and silently resolve to
   #N/A/#NAME?. Stick to IF, IFERROR, VLOOKUP, INDEX, MATCH, SUMIFS, COUNTIFS, etc.
4. Cross-sheet references: quote sheet names with spaces ('Sales Log'!$A$2:$A$101) and set "link": true.
5. Fix the row count in cross-sheet ranges to the sheet's "rows" (e.g. rows:100 -> $2:$101).
6. Labels must be specific to the niche (real categories, not "Item 1").
7. Provide a Dashboard with 6-9 KPIs and one bar chart referencing a summary sheet.
8. Keep it genuinely useful for the stated niche and buyer.
9. Reference the CORRECT source columns. Columns are lettered left-to-right (1st col
   = A, 2nd = B, 3rd = C, ...); a formula must use the ACTUAL letter of each column it
   means. A "Full Name" column = the first-name input & " " & the last-name input
   using THOSE columns' letters (e.g. =B{row}&" "&C{row}) — never an off-by-one or a
   neighbouring column. After writing each formula, re-check every cell reference
   against the column list you just defined.
10. A formula COLUMN applies ONE formula template to every row (with {row}); it cannot
    hold a different formula per row. Design summaries around that fact:
    - Heterogeneous scalar metrics (Total Members, Total Revenue, Net Profit, Avg Share
      Price, ...) go in the Dashboard KPIs — each KPI carries its own formula. Do NOT
      build a separate "Metrics"/"Summary" sheet whose single value column switches a
      giant nested-IF on the row's label: that is the only way to fake per-row formulas
      in a column, and it is unmaintainable and FORBIDDEN. Likewise never stub the
      value column with "", 0, or IFERROR("","").
    - A summary SHEET is allowed ONLY for a homogeneous per-category rollup computed by
      ONE template keyed to a seed label — e.g. a Month seed column plus, per row,
      =SUMIFS('Log'!$E$2:$E$101,'Log'!$L$2:$L$101,A{row}). Use that as the bar chart's
      source. Set its "rows" to EXACTLY the seed-label count (no padding rows).
"""

def generate_spec(niche, template_type):
    body = json.dumps({
        "model": MODEL, "max_tokens": 8192,
        "system": CONTRACT,
        "messages": [{"role": "user",
            "content": f"Niche: {niche}\nTemplate: {template_type}\n"
                       f"Design the best-selling version of this. Return JSON only."}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json",
                 "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"})
    data = json.loads(urllib.request.urlopen(req).read())
    text = "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    return json.loads(text)

if __name__ == "__main__":
    niche = sys.argv[1] if len(sys.argv) > 1 else "reseller bookkeeping"
    ttype = sys.argv[2] if len(sys.argv) > 2 else "Profit & Inventory Tracker"
    spec = generate_spec(niche, ttype)
    out = f"specs/{ttype.lower().replace(' ', '_')}.json"
    os.makedirs("specs", exist_ok=True)
    json.dump(spec, open(out, "w"), indent=2)
    print("spec ->", out)
