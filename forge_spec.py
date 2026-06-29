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
3. Wrap any division in IFERROR(...,0) to avoid #DIV/0!.
4. Cross-sheet references: quote sheet names with spaces ('Sales Log'!$A$2:$A$101) and set "link": true.
5. Fix the row count in cross-sheet ranges to the sheet's "rows" (e.g. rows:100 -> $2:$101).
6. Labels must be specific to the niche (real categories, not "Item 1").
7. Provide a Dashboard with 6-9 KPIs and one bar chart referencing a summary sheet.
8. Keep it genuinely useful for the stated niche and buyer.
"""

def generate_spec(niche, template_type):
    body = json.dumps({
        "model": MODEL, "max_tokens": 4096,
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
