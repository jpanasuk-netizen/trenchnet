
from pathlib import Path
p = Path("out/assets/interactive.js")
t = p.read_text(encoding="utf-8")
needle = 'Unpriceable trades are excluded'
if "coverage_by" in t and "Top token coverage" in t:
    print("already patched")
else:
    # Expand btCoverage block to include pool + per-token note
    old = """    if ($(\"btCoverage\")) {
      $(\"btCoverage\").textContent =
        `Server coverage ${fmt(cov.coverage_pct, 2)}% of copy sims priceable ` +
        `(${cov.n_priced || 0}/${cov.n_copies || 0}). Sources: ${JSON.stringify(cov.price_sources || {})}. ` +
        `Unpriceable trades are excluded — never filled with invented prices.`;
    }"""
    new = """    if ($(\"btCoverage\")) {
      const cb = (bt.coverage_by || {});
      const tok = (cb.tokens || []).slice(0, 5).map(x =>
        (x.token_mint || \"\").slice(0, 6) + \"… \" + fmt(x.coverage_pct, 1) + \"%\" + (x.has_pool_series ? \" pool\" : \"\")
      ).join(\"; \");
      const pool = D().pool_coverage || {};
      const poolNote = pool.ok ? (`pool mints ok=${(pool.ok||[]).length||pool.ok} failed=${(pool.failed||[]).length||0}`) :
        (typeof pool.ok === \"number\" ? `pool ok=${pool.ok} failed=${pool.failed||0}` :
        `pool ok=${(pool.ok||[]).length} failed=${(pool.failed||[]).length}`);
      $(\"btCoverage\").innerHTML =
        `Server coverage <b>${fmt(cov.coverage_pct, 2)}%</b> priceable ` +
        `(${cov.n_priced || 0}/${cov.n_copies || 0}). Sources: ${JSON.stringify(cov.price_sources || {})}. ` +
        `${poolNote}. Unpriceable excluded — never invented. ` +
        (tok ? `<div class=\"muted\">Top token coverage @60s: ${tok}</div>` : \"\");
    }"""
    if old not in t:
        # try without special dash
        old2 = old.replace("—", "-").replace("–", "-")
        if old2 in t:
            t = t.replace(old2, new)
        else:
            # fuzzy: find function start
            i = t.find('if ($("btCoverage"))')
            if i < 0:
                raise SystemExit("btCoverage block missing")
            j = t.find("}", i)
            # find closing of if - crude: next blank line after textContent
            k = t.find("Unpriceable", i)
            k2 = t.find(";", k)
            k3 = t.find("\n", k2)
            # replace from i to after the if block's closing }
            # locate matching
            end = t.find("\n    }", i)
            end = t.find("\n", end + 1)
            t = t[:i] + new + t[end:]
            print("fuzzy patched")
    else:
        t = t.replace(old, new)
        print("exact patched")
    p.write_text(t, encoding="utf-8")
print("done")
