"""Download PDFs for research-type Source nodes in the knowledge graph.

ALG-KK-INGEST-PDF-DOWNLOAD: resolves landing-page URLs to direct PDF URLs,
downloads to data/pdfs/{source_id}.pdf, updates Source attrs with local_pdf_path.
INV-KK-INGEST-PDF-ATTR: every Source with local_pdf_path has pdf_downloaded_at.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

RESEARCH_TYPES = ("paper", "preprint", "conference-paper", "conference-proceedings")

SKIP_DOMAINS = ("kernel.org", "lpc.events", "sigops.org", "paper.lingyunyang.com")

USER_AGENT = "know_kernel-pdf-downloader/1.0 (research; https://github.com/reiniertl/know_kernel)"

REQUEST_DELAY = 1.0


def resolve_pdf_url(url: str) -> str | None:
    if not url:
        return None
    if url.endswith(".pdf"):
        return url
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/") + ".pdf"
    if "dl.acm.org/doi/" in url and "/pdf/" not in url:
        return url.replace("dl.acm.org/doi/", "dl.acm.org/doi/pdf/")
    for domain in SKIP_DOMAINS:
        if domain in url:
            return None
    return None


def query_research_sources(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ",".join("?" for _ in RESEARCH_TYPES)
    rows = conn.execute(
        f"SELECT id, attrs FROM nodes WHERE kind = 'Source' "
        f"AND json_extract(attrs, '$.source_type') IN ({placeholders})",
        RESEARCH_TYPES,
    ).fetchall()
    sources = []
    for row in rows:
        attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
        sources.append({"id": row[0], "attrs": attrs})
    return sources


def download_pdf(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  FAILED: {e}")
        if dest.exists():
            dest.unlink()
        return False


def update_source_attrs(conn: sqlite3.Connection, source_id: str, pdf_path: str):
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return
    attrs = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
    attrs["local_pdf_path"] = pdf_path
    attrs["pdf_downloaded_at"] = date.today().isoformat()
    conn.execute(
        "UPDATE nodes SET attrs = ? WHERE id = ?",
        (json.dumps(attrs, ensure_ascii=False), source_id),
    )


def main():
    parser = argparse.ArgumentParser(description="Download research PDFs")
    parser.add_argument("--db", default="data/master.db", help="Database path")
    parser.add_argument("--out-dir", default="data/pdfs", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without downloading")
    parser.add_argument("--skip-existing", action="store_true", help="Skip already-downloaded PDFs")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    sources = query_research_sources(conn)
    print(f"Found {len(sources)} research sources")

    downloaded, skipped, failed, manual = 0, 0, 0, []
    seen_urls: dict[str, str] = {}

    for src in sources:
        source_id = src["id"]
        url = src["attrs"].get("url", "")
        source_type = src["attrs"].get("source_type", "")
        title = src["attrs"].get("title", source_id)
        dest = out_dir / f"{source_id}.pdf"

        pdf_url = resolve_pdf_url(url)

        if pdf_url is None:
            reason = "no PDF URL resolvable"
            for domain in SKIP_DOMAINS:
                if domain in url:
                    reason = f"skip ({domain})"
                    break
            print(f"  SKIP  {source_id}: {reason}")
            skipped += 1
            manual.append({"id": source_id, "title": title, "url": url, "reason": reason})
            continue

        if args.skip_existing and dest.exists():
            print(f"  EXISTS {source_id}: {dest}")
            skipped += 1
            continue

        if pdf_url in seen_urls:
            original_id = seen_urls[pdf_url]
            original_dest = out_dir / f"{original_id}.pdf"
            if args.dry_run:
                print(f"  DRY   {source_id}: copy from {original_id} (dedup)")
            elif original_dest.exists():
                shutil.copy2(original_dest, dest)
                update_source_attrs(conn, source_id, str(dest))
                print(f"  COPY  {source_id}: dedup from {original_id}")
                downloaded += 1
            continue

        seen_urls[pdf_url] = source_id

        if args.dry_run:
            print(f"  DRY   {source_id}: {pdf_url}")
            downloaded += 1
            continue

        print(f"  GET   {source_id}: {pdf_url}")
        if download_pdf(pdf_url, dest):
            update_source_attrs(conn, source_id, str(dest))
            downloaded += 1
        else:
            failed += 1

        time.sleep(REQUEST_DELAY)

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\nSummary: {downloaded} downloaded, {skipped} skipped, {failed} failed")
    if manual:
        print(f"\nManual download needed ({len(manual)}):")
        for m in manual:
            print(f"  {m['id']}: {m['title']}")
            print(f"    URL: {m['url']}")
            print(f"    Reason: {m['reason']}")


if __name__ == "__main__":
    main()
