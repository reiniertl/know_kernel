"""Fetch real abstracts for the 60 arXiv papers that have short/missing text.
arXiv API: 3s rate limit. ~60 papers * 3s = ~3 minutes.
"""
import json, sqlite3, time, urllib.request, urllib.error, urllib.parse, re, sys, xml.etree.ElementTree as ET

DB_PATH = "data/master.db"
ARXIV_API = "http://export.arxiv.org/api/query"
RATE_LIMIT = 3.0
BATCH_SIZE = 25

def extract_arxiv_id(url):
    if not url:
        return None
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
    if m:
        return m.group(1)
    m = re.search(r'(\d{4}\.\d{4,5})', url)
    if m:
        return m.group(1)
    return None

def fetch_arxiv_abstract(arxiv_id):
    url = f"{ARXIV_API}?id_list={arxiv_id}&max_results=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "know_kernel/0.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode()
            root = ET.fromstring(xml_data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            if entries:
                summary = entries[0].find("atom:summary", ns)
                if summary is not None and summary.text:
                    abstract = summary.text.strip()
                    abstract = re.sub(r'\s+', ' ', abstract)
                    return abstract
    except Exception as e:
        print(f"    ERR: {e}", flush=True)
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
        if not arxiv_id:
            failed += 1
            safe = title[:50].encode('ascii', 'replace').decode() if title else "?"
            print(f"[{i+1}/{total}] NO_ID {safe}", flush=True)
            continue

        abstract = fetch_arxiv_abstract(arxiv_id)
        time.sleep(RATE_LIMIT)

        if abstract and len(abstract) > 100:
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

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"\nDone: {updated} fetched, {failed} failed out of {total}", flush=True)
    conn.close()

if __name__ == "__main__":
    main()
