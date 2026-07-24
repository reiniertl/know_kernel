"""Fetch abstracts for conference papers via Semantic Scholar API.
Conservative: 5s between requests, 5min initial cooldown, DB busy timeout.
"""
import json, sqlite3, time, urllib.request, urllib.error, urllib.parse, re, sys

DB_PATH = "data/master.db"
RATE_LIMIT = 5.0
BATCH_SIZE = 10


def extract_doi(url):
    if not url:
        return None
    m = re.search(r'(10\.\d{4,}/[^\s]+)', url)
    if m:
        return m.group(1).rstrip('.')
    return None


def s2_get(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "know_kernel/0.1"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 120 * (attempt + 1)
                print(f"    429 - waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            if e.code == 404:
                return None
            return None
        except Exception:
            return None
    return None


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    rows = conn.execute("""
        SELECT ev.id, json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.url'),
               json_extract(s.attrs, '$.venue')
        FROM nodes s
        JOIN edges se ON se.kind='sourced-from' AND se.target_id=s.id
        JOIN nodes ev ON ev.id=se.source_id AND ev.kind='Evidence'
        WHERE s.kind='Source'
        AND (json_extract(ev.attrs, '$.text') IS NULL OR length(json_extract(ev.attrs, '$.text')) < 100)
        AND json_extract(s.attrs, '$.venue') NOT LIKE 'arXiv%'
        AND json_extract(s.attrs, '$.venue') != ''
        ORDER BY json_extract(s.attrs, '$.venue'), json_extract(s.attrs, '$.title')
    """).fetchall()

    total = len(rows)
    print(f"Papers missing abstracts: {total}", flush=True)
    print("Cooldown 300s for S2 rate limit...", flush=True)
    time.sleep(300)

    updated = 0
    missed = 0

    for i, (ev_id, title, url, venue) in enumerate(rows):
        doi = extract_doi(url)
        abstract = None

        if doi:
            data = s2_get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='')}?fields=abstract")
            if data:
                abstract = data.get("abstract")
            time.sleep(RATE_LIMIT)

        if not abstract and title:
            data = s2_get(f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(title[:150])}&limit=1&fields=abstract")
            if data:
                results = data.get("data", [])
                if results:
                    abstract = results[0].get("abstract")
            time.sleep(RATE_LIMIT)

        if abstract and len(abstract) > 50:
            attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id=?", (ev_id,)).fetchone()[0])
            attrs["text"] = abstract
            conn.execute("UPDATE nodes SET attrs=? WHERE id=?", (json.dumps(attrs), ev_id))
            updated += 1
            safe = title[:50].encode('ascii', 'replace').decode() if title else "?"
            print(f"[{i+1}/{total}] OK ({len(abstract)}ch) {safe}", flush=True)
        else:
            missed += 1
            safe = title[:50].encode('ascii', 'replace').decode() if title else "?"
            print(f"[{i+1}/{total}] MISS {safe}", flush=True)

        if updated > 0 and updated % BATCH_SIZE == 0:
            conn.commit()
            print(f"--- Committed {updated}/{i+1} ({missed} missed) ---", flush=True)

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"\nDone: {updated} fetched, {missed} missed out of {total}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
