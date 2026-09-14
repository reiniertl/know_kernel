"""Fetch real abstracts for arXiv papers with short/fake text via OpenAlex.
OpenAlex indexes arXiv papers well and has generous rate limits.
"""
import json, sqlite3, time, urllib.request, urllib.error, urllib.parse, re, sys

DB_PATH = "data/master.db"
RATE_LIMIT = 0.5
BATCH_SIZE = 25
USER_AGENT = "know_kernel/0.1 (mailto:reiniertl@gmail.com)"


def extract_arxiv_id(url):
    if not url:
        return None
    m = re.search(r'(\d{4}\.\d{4,5})', url)
    if m:
        return m.group(1)
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


def fetch_openalex_arxiv(arxiv_id):
    """Fetch from OpenAlex using arXiv ID directly."""
    # OpenAlex indexes arXiv papers and can look them up
    url = f"https://api.openalex.org/works?filter=ids.openalex:https://openalex.org/works/arxiv:{arxiv_id}&per_page=1"
    # Fallback: search by DOI pattern
    doi_url = f"https://api.openalex.org/works/doi:10.48550/arXiv.{arxiv_id}"

    for attempt_url in [doi_url]:
        try:
            req = urllib.request.Request(attempt_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                return reconstruct_abstract(data.get("abstract_inverted_index"))
        except Exception:
            pass
    return None


def fetch_openalex_title(title):
    """Fallback: search by title."""
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(title[:200])}&per_page=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
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

    rows = conn.execute("""
        SELECT ev.id, json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.url')
        FROM nodes s
        JOIN edges se ON se.kind='sourced-from' AND se.target_id=s.id
        JOIN nodes ev ON ev.id=se.source_id AND ev.kind='Evidence'
        WHERE s.kind='Source'
        AND json_extract(s.attrs, '$.venue') LIKE 'arXiv%'
        AND (json_extract(ev.attrs, '$.text') IS NULL OR length(json_extract(ev.attrs, '$.text')) < 800)
        ORDER BY json_extract(s.attrs, '$.published_date') DESC
    """).fetchall()

    total = len(rows)
    print(f"ArXiv papers needing real abstracts: {total}", flush=True)

    updated = 0
    failed = 0

    for i, (ev_id, title, url) in enumerate(rows):
        arxiv_id = extract_arxiv_id(url)
        abstract = None

        # Try OpenAlex DOI lookup first
        if arxiv_id:
            abstract = fetch_openalex_arxiv(arxiv_id)
            time.sleep(RATE_LIMIT)

        # Fallback: title search
        if not abstract and title:
            abstract = fetch_openalex_title(title)
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
