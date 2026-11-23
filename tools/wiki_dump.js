// Refreshes data/raw/wiki_items.tsv from travellersrest.wiki.gg.
//
// How to run: open any travellersrest.wiki.gg page in a browser, open the
// developer console (F12 → Console), paste this whole file, press Enter.
// It reads every article's source through the wiki's API (read-only), takes
// the `| id = N` field of each item infobox, and downloads tr_item_ids.txt.
// Save that file over data/raw/wiki_items.tsv, then run `trtool build-db`.
//
// Output: one line per item, tab-separated: id, page title, infobox type.
const out = {};
let c = {};
do {
  const p = new URLSearchParams({
    action: 'query', format: 'json', generator: 'allpages', gapnamespace: '0',
    gaplimit: '50', gapfilterredir: 'nonredirects',
    prop: 'revisions', rvprop: 'content', rvslots: 'main', ...c,
  });
  const j = await fetch('/api.php?' + p).then(r => r.json());
  for (const pg of Object.values(j.query?.pages || {})) {
    const t = pg.revisions?.[0]?.slots?.main?.['*'] || '';
    const re = /\{\{\s*Infobox\s+([^\n|]+)([\s\S]*?)\n\s*\}\}/g;
    let m;
    while ((m = re.exec(t))) {
      const i = m[2].match(/\|\s*id\s*=\s*(\d+)/);
      if (i && !out[i[1]]) out[i[1]] = pg.title + '\t' + m[1].trim();
    }
  }
  c = j.continue ? { gapcontinue: j.continue.gapcontinue, continue: j.continue.continue } : null;
} while (c);
const a = document.createElement('a');
a.href = URL.createObjectURL(new Blob(
  [Object.entries(out).map(e => e.join('\t')).join('\n')], { type: 'text/plain' }));
a.download = 'tr_item_ids.txt';
a.click();
'saved ' + Object.keys(out).length;
