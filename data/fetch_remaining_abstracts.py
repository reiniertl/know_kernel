"""Fetch remaining real abstracts using multiple APIs with proper backoff.
Targets ALL papers with text < 800 chars (fake summaries).
Uses OpenAlex (primary, with cooldown) and arXiv API (for arXiv papers).
"""
import json, sqlite3, time, urllib.request, urllib.error, urllib.parse, re, sys
import xml.etree.ElementTree as ET

DB_PATH = "data/master.db"
BATCH_SIZE = 25
USER_AGENT = "know_kernel/0.1 (mailto:reiniertl@gmail.com)"


def extract_doi(url):
    if not url:
        return None
    m = re.search(r'(10\.\d{4,}/[^\s]+)', url)
    if m:
        return m.group(1).rstrip('.')
    return None


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


def fetch_openalex(doi=None, title=None, arxiv_id=None):
    """Try OpenAlex with proper 429 handling."""
    urls_to_try = []
    if doi:
        urls_to_try.append(f"https://api.openalex.org/works/doi:{doi}")
    if arxiv_id:
        urls_to_try.append(f"https://api.openalex.org/works/doi:10.48550/arXiv.{arxiv_id}")
    if title:
        urls_to_try.append(f"https://api.openalex.org/works?search={urllib.parse.quote(title[:200])}&per_page=1")

    for url in urls_to_try:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if "results" in data:
                    results = data.get("results", [])
                    if results:
                        return reconstruct_abstract(results[0].get("abstract_inverted_index"))
                else:
                    return reconstruct_abstract(data.get("abstract_inverted_index"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("    OA 429 - cooling 120s...", flush=True)
                time.sleep(120)
                return None  # skip this paper, try next
            pass
        except Exception:
            pass
    return None


def fetch_arxiv(arxiv_id):
    """Fetch from arXiv API."""
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
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
                    return re.sub(r'\s+', ' ', abstract)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("    arXiv 429 - cooling 60s...", flush=True)
            time.sleep(60)
    except Exception:
        pass
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
        AND json_extract(s.attrs, '$.source_type') IN ('paper','preprint','conference-paper','conference-proceedings')
        AND (json_extract(ev.attrs, '$.text') IS NULL OR length(json_extract(ev.attrs, '$.text')) < 800)
        ORDER BY json_extract(s.attrs, '$.published_date') DESC
    """).fetchall()

    total = len(rows)
    print(f"Papers needing real abstracts: {total}", flush=True)
    print("Waiting 180s for API cooldown...", flush=True)
    time.sleep(180)

    updated = 0
    failed = 0

    for i, (ev_id, title, url, venue) in enumerate(rows):
        doi = extract_doi(url)
        arxiv_id = extract_arxiv_id(url) if venue and 'arXiv' in venue else None
        abstract = None

        # Strategy 1: arXiv API for arXiv papers (3s rate limit)
        if arxiv_id and not abstract:
            abstract = fetch_arxiv(arxiv_id)
            time.sleep(3)

        # Strategy 2: OpenAlex (0.5s rate limit but can 429)
        if not abstract:
            abstract = fetch_openalex(doi=doi, title=title, arxiv_id=arxiv_id)
            time.sleep(1)

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
