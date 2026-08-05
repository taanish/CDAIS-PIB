#!/usr/bin/env python3
"""
PIB archive enumerator.

Walks relid space against archive2/PrintRelease.aspx, parses each release, and
writes provenance (Layer 1) + release records (Layer 2) into SQLite.

Stdlib only. Python 3.9 compatible. Serial, single keep-alive connection —
measured to sustain ~14 req/s, well above the 10 req/s ceiling we target.

Resumable: any relid already present in fetch_log is skipped, so an interrupted
run is restarted by re-issuing the identical command.

  python3 crawl.py --db corpus.db --limit 2000            # dry run
  python3 crawl.py --db corpus.db                          # full archive
"""

import argparse
import hashlib
import html as htmllib
import http.client
import json
import os
import re
import signal
import sqlite3
import statistics
import sys
import time
from collections import deque
from datetime import datetime, timezone

HOST = "archive.pib.gov.in"
PATH = "/archive2/PrintRelease.aspx?relid=%d"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

DEFAULT_HI = 292729          # 05-Aug-2026, verified live
DEFAULT_LO = 1

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
for _m, _i in list(MONTHS.items()):
    MONTHS[_m[:3]] = _i

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
QRUN = re.compile(r"\?{3,}")
# Date and time are matched independently: a malformed timestamp (e.g. the
# single-digit minute in "12-January-2004 19:0 IST") must not cost us the date.
DATE_RE = re.compile(r"(\d{1,2})-([A-Za-z]+)[-,\s]+(\d{4})", re.I)
TIME_RE = re.compile(r"(\d{1,2}):(\d{1,2})\s*IST", re.I)
IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
BREAK_RE = re.compile(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", re.I)


# ----------------------------------------------------------------- parsing --

def _text(fragment):
    """HTML fragment -> plain text, preserving block structure as newlines."""
    s = SCRIPT_RE.sub(" ", fragment)
    s = BREAK_RE.sub("\n", s)
    s = TAG_RE.sub(" ", s)
    s = htmllib.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _slice_div(page, div_id):
    """Return the inner HTML of <div id="..."> up to a sensible terminator."""
    anchor = page.find('id="%s"' % div_id)
    if anchor == -1:
        return None
    gt = page.find(">", anchor)
    if gt == -1:
        return None
    rest = page[gt + 1:]
    if div_id == "condiv":
        # Body runs to the end of the form; nested divs make regex unreliable.
        end = rest.find("</form>")
        return rest if end == -1 else rest[:end]
    end = rest.find("</div>")
    return rest if end == -1 else rest[:end]


def parse_release(page):
    """Parse a PrintRelease.aspx page. Returns (record, warnings)."""
    warn = []
    rec = {}

    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    rec["title"] = re.sub(r"\s+", " ", htmllib.unescape(m.group(1))).strip() if m else None
    # Some releases (mostly 2010-era) ship an empty <title>; recovered below
    # from the centred heading or the body's first line, once those are parsed.

    # --- header block: ministry + timestamp
    hdr = _slice_div(page, "thd1")
    rec["ministry_raw"] = None
    rec["release_date"] = None
    rec["release_time"] = None
    if hdr is None:
        warn.append("no_thd1")
    else:
        hdr_text = _text(hdr)
        d = DATE_RE.search(hdr_text)
        if d:
            day, mon, year = d.group(1), d.group(2).lower(), d.group(3)
            mi = MONTHS.get(mon) or MONTHS.get(mon[:3])
            if mi:
                rec["release_date"] = "%s-%02d-%02d" % (year, mi, int(day))
            else:
                warn.append("bad_month:" + mon[:20])
        else:
            warn.append("no_date")
        t = TIME_RE.search(hdr_text)
        if t:
            rec["release_time"] = "%02d:%02d" % (int(t.group(1)), int(t.group(2)))

        # Ministry = last <br>-separated line once the timestamp span and the
        # two fixed masthead lines are removed.
        stripped = re.sub(r"<span.*?</span>", "", hdr, flags=re.S | re.I)
        lines = []
        for chunk in re.split(r"<br\s*/?>", stripped, flags=re.I):
            t = re.sub(r"\s+", " ", htmllib.unescape(TAG_RE.sub("", chunk))).strip()
            if (t and "Press Information Bureau" not in t
                    and t.lower() != "government of india"):
                lines.append(t)
        if lines:
            rec["ministry_raw"] = lines[-1]
        else:
            warn.append("no_ministry")

    # --- content block: optional centred heading, then body
    body_html = _slice_div(page, "condiv")
    rec["heading"] = None
    if body_html is None:
        warn.append("no_condiv")
        rec["body_text"] = ""
    else:
        head = re.match(r"\s*<div[^>]*text-align:\s*center[^>]*>(.*?)</div>(.*)",
                        body_html, re.S | re.I)
        if head:
            rec["heading"] = _text(head.group(1)) or None
            body_html = head.group(2)
        rec["body_text"] = _text(body_html)
        rec["image_urls"] = [u for u in IMG_RE.findall(body_html)]

    body = rec.get("body_text") or ""
    rec.setdefault("image_urls", [])
    rec["image_count"] = len(rec["image_urls"])
    rec["char_count"] = len(body)
    rec["word_count"] = len(body.split())
    rec["has_devanagari"] = 1 if DEVANAGARI.search(body) else 0
    qchars = sum(len(x) for x in QRUN.findall(body))
    rec["mojibake_ratio"] = (qchars / len(body)) if body else 0.0

    if not body:
        warn.append("empty_body")

    # Recover a missing <title> from the heading, then the body's first line.
    # The warning records which fallback fired so provenance stays auditable.
    if not rec["title"]:
        if rec.get("heading"):
            rec["title"] = rec["heading"].split("\n")[0].strip()[:400]
            warn.append("title_from_heading")
        elif body:
            rec["title"] = body.split("\n")[0].strip()[:400]
            warn.append("title_from_body")
        else:
            warn.append("no_title")

    # Structural failure -> failed. A genuinely absent field -> partial.
    # A successful fallback is benign: status stays ok, warning is retained.
    BENIGN = {"title_from_heading", "title_from_body"}
    status = "ok"
    if "no_condiv" in warn or "no_thd1" in warn:
        status = "failed"
    elif set(warn) - BENIGN:
        status = "partial"
    return rec, status, warn


# ------------------------------------------------------------- rate control --

class Governor:
    """Serial pacer: starts slow, ramps once proven, backs off on trouble."""

    def __init__(self, start=5.0, top=10.0, ramp_after_sec=3600.0, floor=1.0,
                 backoff_floor_sec=0.4):
        self.rate = float(start)
        self.top = float(top)
        self.floor = float(floor)
        self.ramp_after = float(ramp_after_sec)
        # Backing off needs BOTH a relative jump and an absolute floor. With a
        # ~30ms baseline, 3x alone is 90ms — reachable by ordinary jitter, which
        # would cascade the rate down for no reason.
        self.backoff_floor = float(backoff_floor_sec)
        self.clean_since = time.monotonic()
        self.lat = deque(maxlen=200)
        self.baseline = None
        self._last = 0.0
        self.events = []

    def pace(self):
        gap = 1.0 / self.rate
        dt = time.monotonic() - self._last
        if dt < gap:
            time.sleep(gap - dt)
        self._last = time.monotonic()

    def ok(self, elapsed):
        self.lat.append(elapsed)
        if self.baseline is None and len(self.lat) >= 40:
            self.baseline = statistics.median(self.lat)
        if self.baseline and len(self.lat) >= 40:
            recent = statistics.median(list(self.lat)[-40:])
            trigger = max(3.0 * self.baseline, self.backoff_floor)
            if recent > trigger and self.rate > self.floor:
                self.rate = max(self.floor, self.rate / 2.0)
                self.clean_since = time.monotonic()
                self._log("backoff-latency %.1f req/s (recent %.0fms vs base %.0fms)"
                          % (self.rate, recent * 1000, self.baseline * 1000))
                return
        if (self.rate < self.top
                and time.monotonic() - self.clean_since >= self.ramp_after):
            self.rate = min(self.top, self.rate * 2.0)
            self.clean_since = time.monotonic()
            self._log("ramp -> %.1f req/s" % self.rate)

    def trouble(self, why):
        self.clean_since = time.monotonic()
        if self.rate > self.floor:
            self.rate = max(self.floor, self.rate / 2.0)
            self._log("backoff-%s -> %.1f req/s" % (why, self.rate))

    def _log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.events.append("%s %s" % (stamp, msg))
        print("  [gov] %s %s" % (stamp, msg), flush=True)


# ------------------------------------------------------------------ fetcher --

class Fetcher:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.conn = None
        self._connect()

    def _connect(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.conn = http.client.HTTPSConnection(HOST, timeout=self.timeout)

    def get(self, relid, retries=4):
        last = None
        for attempt in range(retries):
            t0 = time.time()
            try:
                self.conn.request("GET", PATH % relid,
                                  headers={"User-Agent": UA,
                                           "Connection": "keep-alive",
                                           "Accept": "text/html,*/*"})
                resp = self.conn.getresponse()
                body = resp.read()
                return resp.status, body, time.time() - t0, None
            except Exception as exc:            # noqa: BLE001 - retry anything transport-level
                last = "%s: %s" % (type(exc).__name__, exc)
                self._connect()
                if attempt < retries - 1:
                    time.sleep(min(30.0, 2.0 ** attempt))
        return None, b"", 0.0, last


# -------------------------------------------------------------------- store --

INS_FETCH = """INSERT OR REPLACE INTO fetch_log
 (relid,url,http_status,fetched_at,elapsed_ms,byte_size,content_sha256,
  parse_status,parse_warnings) VALUES (?,?,?,?,?,?,?,?,?)"""

INS_REL = """INSERT OR REPLACE INTO releases
 (relid,title,heading,ministry_raw,release_date,release_time,body_text,
  word_count,char_count,image_count,image_urls,has_devanagari,mojibake_ratio)
 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def open_db(path, schema_path):
    fresh = not os.path.exists(path)
    con = sqlite3.connect(path, timeout=60)
    if fresh or schema_path:
        with open(schema_path, "r", encoding="utf-8") as fh:
            con.executescript(fh.read())
    con.commit()
    return con


def done_set(con):
    return set(r[0] for r in con.execute("SELECT relid FROM fetch_log"))


# --------------------------------------------------------------------- main --

STOP = {"flag": False}


def _sigterm(_signo, _frame):
    STOP["flag"] = True
    print("\n  [!] stop requested — finishing current batch and committing…", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--schema", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"))
    ap.add_argument("--hi", type=int, default=DEFAULT_HI)
    ap.add_argument("--lo", type=int, default=DEFAULT_LO)
    ap.add_argument("--limit", type=int, default=0, help="stop after N fetches (0 = no limit)")
    ap.add_argument("--rate", type=float, default=5.0)
    ap.add_argument("--max-rate", type=float, default=10.0)
    ap.add_argument("--ramp-after-sec", type=float, default=3600.0)
    ap.add_argument("--ascending", action="store_true", help="oldest first (default: newest first)")
    ap.add_argument("--commit-every", type=int, default=200)
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    con = open_db(args.db, args.schema)
    seen = done_set(con)
    order = range(args.lo, args.hi + 1) if args.ascending else range(args.hi, args.lo - 1, -1)
    queue = [r for r in order if r not in seen]
    if args.limit:
        queue = queue[:args.limit]

    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    con.execute("INSERT INTO crawl_sessions (session_id,started_at,range_lo,range_hi) "
                "VALUES (?,?,?,?)",
                (session_id, datetime.now(timezone.utc).isoformat(), args.lo, args.hi))
    con.commit()

    print("db=%s  already have %d  queued %d  order=%s  rate %.1f->%.1f req/s"
          % (args.db, len(seen), len(queue),
             "asc" if args.ascending else "desc", args.rate, args.max_rate), flush=True)
    if not queue:
        print("nothing to do.")
        return 0

    gov = Governor(args.rate, args.max_rate, args.ramp_after_sec)
    fetcher = Fetcher()
    n = ok = absent = failed = errored = 0
    t_start = time.time()
    pending = 0

    for relid in queue:
        if STOP["flag"]:
            break
        gov.pace()
        status, body, elapsed, err = fetcher.get(relid)
        n += 1
        now = datetime.now(timezone.utc).isoformat()
        url = "https://%s%s" % (HOST, PATH % relid)

        if status is None:
            errored += 1
            gov.trouble("transport")
            con.execute(INS_FETCH, (relid, url, None, now, 0, 0, None, "failed",
                                    json.dumps(["transport", err or ""])))
        elif status == 302:
            absent += 1
            gov.ok(elapsed)
            con.execute(INS_FETCH, (relid, url, status, now, int(elapsed * 1000),
                                    len(body), None, "absent", "[]"))
        elif status != 200:
            errored += 1
            gov.trouble("http%d" % status)
            con.execute(INS_FETCH, (relid, url, status, now, int(elapsed * 1000),
                                    len(body), None, "failed",
                                    json.dumps(["http_%d" % status])))
        else:
            gov.ok(elapsed)
            page = body.decode("utf-8", "replace")
            rec, pstatus, warn = parse_release(page)
            sha = hashlib.sha256(body).hexdigest()
            con.execute(INS_FETCH, (relid, url, status, now, int(elapsed * 1000),
                                    len(body), sha, pstatus, json.dumps(warn)))
            if pstatus != "failed":
                ok += 1
                con.execute(INS_REL, (
                    relid, rec["title"], rec["heading"], rec["ministry_raw"],
                    rec["release_date"], rec["release_time"], rec["body_text"],
                    rec["word_count"], rec["char_count"], rec["image_count"],
                    json.dumps(rec["image_urls"]), rec["has_devanagari"],
                    rec["mojibake_ratio"]))
            else:
                failed += 1

        pending += 1
        if pending >= args.commit_every:
            con.commit()
            pending = 0
            rate = n / max(1e-9, time.time() - t_start)
            eta = (len(queue) - n) / max(1e-9, rate)
            print("  %7d/%d  ok=%d absent=%d parsefail=%d err=%d  %.1f req/s  eta %.1fh"
                  % (n, len(queue), ok, absent, failed, errored, rate, eta / 3600.0),
                  flush=True)

    con.commit()
    con.execute("UPDATE crawl_sessions SET finished_at=?,attempted=?,ok=?,absent=?,"
                "failed=?,notes=? WHERE session_id=?",
                (datetime.now(timezone.utc).isoformat(), n, ok, absent,
                 failed + errored, json.dumps(gov.events[-50:]), session_id))
    con.commit()

    elapsed_h = (time.time() - t_start) / 3600.0
    print("\ndone: attempted=%d ok=%d absent=%d parse_failed=%d transport_err=%d "
          "in %.2fh (%.1f req/s avg)"
          % (n, ok, absent, failed, errored, elapsed_h,
             n / max(1e-9, time.time() - t_start)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
