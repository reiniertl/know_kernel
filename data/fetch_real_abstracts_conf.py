"""Re-fetch ALL conference paper abstracts from OpenAlex.
Replaces short summaries with real abstracts.
Only updates papers that don't already have a real abstract (>= 500 chars).

OpenAlex: free, generous rate limits with polite pool (mailto: in User-Agent).
"""
import json, sqlite3, time, urllib.request, urllib.error, urllib.parse, re, sys

DB_PATH = "data/master.db"
RATE_LIMIT = 0.5
BATCH_SIZE = 25
USER_AGENT = "know_kernel/0.1 (mailto:reiniertl@gmail.com)"


def extract_doi(url):
    if not url:
        return None
    m = re.search(r'(10\.\d{4,}/[^\s]+)', url)
    if m:
        return m.group(1).rstrip('.')
    return None


def reconstruct_abstract(inverted_index):
    if not inverted_index:
        return None
    positions = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    if not positions:
        return None
    return ' '.join(positions[k] for k in sorted(positions))


def fetch_openalex(doi=None, title=None):
    """Fetch abstract from OpenAlex by DOI or title search."""
    if doi:
        url = f"https://api.openalex.org/works/doi:{doi}"
    elif title:
        url = f"https://api.openalex.org/works?search={urllib.parse.quote(title[:200])}&per_page=1"
    else:
        return None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if doi:
                return reconstruct_abstract(data.get("abstract_inverted_index"))
            else:
                results = data.get("results", [])
                if results:
                    return reconstruct_abstract(results[0].get("abstract_inverted_index"))
    except Exception:
        pass
    return None


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    # Get ALL conference papers that need real abstracts
    rows = conn.execute("""
        SELECT ev.id, json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.url'),
               length(json_extract(ev.attrs, '$.text')) as current_len
        FROM nodes s
        JOIN edges se ON se.kind='sourced-from' AND se.target_id=s.id
        JOIN nodes ev ON ev.id=se.source_id AND ev.kind='Evidence'
        WHERE s.kind='Source'
        AND json_extract(s.attrs, '$.venue') NOT LIKE 'arXiv%'
        AND json_extract(s.attrs, '$.venue') != ''
        AND (json_extract(ev.attrs, '$.text') IS NULL
             OR length(json_extract(ev.attrs, '$.text')) < 500)
        ORDER BY json_extract(s.attrs, '$.venue'), json_extract(s.attrs, '$.title')
    """).fetchall()

    total = len(rows)
    print(f"Conference papers needing abstracts: {total}", flush=True)

    updated = 0
    failed = 0

    for i, (ev_id, title, url, current_len) in enumerate(rows):
        doi = extract_doi(url)
        abstract = None

        if doi:
            abstract = fetch_openalex(doi=doi)
            time.sleep(RATE_LIMIT)

        if not abstract and title:
            abstract = fetch_openalex(title=title)
            time.sleep(RATE_LIMIT)

        if abstract and len(abstract) > 200:
            attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id=?", (ev_id,)).fetchone()[0])
            attrs["text"] = abstract
            conn.execute("UPDATE nodes SET attrs=? WHERE id=?", (json.dumps(attrs), ev_id))
            updated += 1
            safe = title[:50].encode('ascii', 'replace').decode() if title else "?"
            print(f"[{i+1}/{total}] OK ({len(abstract)}ch) {safe}", flush=True)
        else:
            failed += 1
            safe = title[:50].encode('ascii', 'replace').decode() if title else "?"
            print(f"[{i+1}/{total}] MISS {safe}", flush=True)

        if updated > 0 and updated % BATCH_SIZE == 0:
            conn.commit()
            print(f"--- Committed {updated}/{i+1} ({failed} missed) ---", flush=True)

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"\nDone: {updated} fetched, {failed} missed out of {total}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
