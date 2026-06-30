"""
forge_batch.py — stamp out a whole catalog in one run.

Reads catalog.json (list of {niche, template}), and for each:
  1. forge_spec.generate_spec()         -> JSON spec   (LLM, your key)
  2. forge_build.build()                -> .xlsx       (deterministic)
  3. recalc + error scan                -> QA gate     (rejects any file with errors)
  4. libreoffice xlsx -> PDF            -> Etsy preview
  5. listing.txt                        -> title + tags + description (LLM)

    python forge_batch.py catalog.json
"""
import os, sys, json, subprocess
import forge_spec, forge_build

# Windows consoles default to cp1252; the status glyphs printed below (✓/✗/—) would
# raise UnicodeEncodeError and abort the whole batch on the first rejected file.
# Force UTF-8 so a rejection just prints and the run continues to the next item.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT = "catalog"

def recalc_ok(path):
    r = subprocess.run([sys.executable, "scripts/recalc.py", path, "60"],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]).get("total_errors", 1) == 0
    except Exception:
        return False

def make_pdf(xlsx, outdir):
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                    "--outdir", outdir, xlsx], capture_output=True)

def listing_copy(niche, template, title):
    prompt = (f"Write an Etsy listing for a spreadsheet template.\n"
              f"Niche: {niche}. Template: {template}.\n"
              f"Return JSON: {{\"title\": <=140 chars SEO title, "
              f"\"tags\": [13 etsy tags <=20 chars], \"description\": 120-word description}}.")
    body = json.dumps({"model": forge_spec.MODEL, "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}]}).encode()
    import urllib.request
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json",
                 "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"})
    data = json.loads(urllib.request.urlopen(req).read())
    return "".join(b["text"] for b in data["content"] if b["type"] == "text")

def slug(s):
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")

def main(catalog_file):
    os.makedirs(OUT, exist_ok=True)
    items = json.load(open(catalog_file))
    for it in items:
        name = slug(it["template"])
        print(f"\n=== {it['template']} ({it['niche']}) ===")
        spec = forge_spec.generate_spec(it["niche"], it["template"])
        xlsx = os.path.join(OUT, name + ".xlsx")
        forge_build.build(spec, xlsx)
        if not recalc_ok(xlsx):
            print("  ✗ REJECTED — formula errors. Skipping listing.")
            continue
        print("  ✓ clean")
        make_pdf(xlsx, OUT)
        open(os.path.join(OUT, name + "_listing.txt"), "w").write(
            listing_copy(it["niche"], it["template"], spec["title"]))
    print("\nCatalog ready in ./" + OUT)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "catalog.json")
