#!/usr/bin/env python3
"""Parallel chunked downloader for HuggingFace.

HF throttles each connection to roughly 1 MB/s on this link while general
bandwidth is ~8 MB/s. The `hf` CLI's --max-workers only parallelises across
files, so a single 21 GiB safetensors still trickles (~23 h for the H3 set).
Splitting one file into ranged chunks reaches ~7 MiB/s (~7x).

Stdlib only. Resumes from existing .parts files.

Usage:
    pget.py <url> <output-path> [-c 8] [--size BYTES]
"""

import argparse
import concurrent.futures
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "pget/1.0"}
_lock = threading.Lock()
_done = 0


def auth_headers():
    """Base headers, plus the HF token when present (needed for gated repos)."""
    h = dict(UA)
    tok = pathlib.Path.home() / ".cache/huggingface/token"
    try:
        if tok.exists():
            t = tok.read_text().strip()
            if t:
                h["Authorization"] = f"Bearer {t}"
    except OSError:
        pass
    return h


def head_size(url):
    req = urllib.request.Request(url, headers=auth_headers(), method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        n = r.headers.get("Content-Length")
        if n is None:
            raise RuntimeError("no Content-Length; pass --size")
        return int(n)


def fetch_range(url, start, end, dest, attempt=0):
    """Download [start, end] into dest, resuming and retrying with backoff."""
    global _done
    have = dest.stat().st_size if dest.exists() else 0
    want = end - start + 1
    if have >= want:
        with _lock:
            _done += have
        return have
    headers = auth_headers()
    headers["Range"] = f"bytes={start + have}-{end}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "ab") as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
                with _lock:
                    _done += len(block)
        return dest.stat().st_size
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if attempt >= 8:
            raise RuntimeError(f"chunk {start}-{end} failed: {e}") from e
        time.sleep(min(2 ** attempt, 30))
        return fetch_range(url, start, end, dest, attempt + 1)


def main():
    global _done
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("output")
    p.add_argument("-c", "--connections", type=int, default=8)
    p.add_argument("--size", type=int)
    args = p.parse_args()

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    total = args.size or head_size(args.url)

    # A file is only "done" if it matches the expected size. Checking mere
    # existence accepted a partially-written file as complete, which silently
    # corrupted a 19.5 GiB weight and made the downloader skip it forever.
    if out.exists():
        got = out.stat().st_size
        if got == total:
            print(f"already complete: {out} ({got} bytes)")
            return
        print(f"incomplete: {out} ({got}/{total} bytes) -- re-fetching the remainder")
        out.unlink()

    partdir = out.with_suffix(out.suffix + ".parts")
    partdir.mkdir(exist_ok=True)

    n = max(1, min(args.connections, 16))
    chunk = (total + n - 1) // n
    ranges = [(i * chunk, min((i + 1) * chunk - 1, total - 1)) for i in range(n)]
    ranges = [r for r in ranges if r[0] <= r[1]]

    for i, (s, e) in enumerate(ranges):
        f = partdir / f"{i:03d}"
        if f.exists():
            _done += min(f.stat().st_size, e - s + 1)

    print(f"{total / 2**30:.2f} GiB -> {out} ({len(ranges)} chunks)", flush=True)
    stop = threading.Event()

    def report():
        last = _done
        while not stop.wait(15):
            with _lock:
                cur = _done
            rate = (cur - last) / 15
            last = cur
            pct = 100 * cur / total if total else 0
            eta = (total - cur) / rate / 60 if rate > 0 else 0
            print(f"  {pct:5.1f}%  {cur / 2**30:6.2f}/{total / 2**30:.2f} GiB  "
                  f"{rate / 2**20:5.2f} MiB/s  eta {eta:5.1f} min", flush=True)

    t = threading.Thread(target=report, daemon=True)
    t.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ranges)) as ex:
            futs = [ex.submit(fetch_range, args.url, s, e, partdir / f"{i:03d}")
                    for i, (s, e) in enumerate(ranges)]
            for f in concurrent.futures.as_completed(futs):
                f.result()
    finally:
        stop.set()

    # Stitch into a temp name and rename only once the size checks out, so an
    # interrupted run can never leave a partial file that looks like a finished
    # one (which is what silently corrupted fl2va before).
    tmp = out.with_suffix(out.suffix + ".stitching")
    with open(tmp, "wb") as dst:
        for i in range(len(ranges)):
            with open(partdir / f"{i:03d}", "rb") as src:
                while True:
                    b = src.read(1 << 22)
                    if not b:
                        break
                    dst.write(b)

    got = tmp.stat().st_size
    if got != total:
        tmp.unlink(missing_ok=True)
        sys.exit(f"SIZE MISMATCH: {got} != {total} (chunks kept for retry)")
    tmp.replace(out)
    for f in partdir.iterdir():
        f.unlink()
    partdir.rmdir()
    print(f"done: {out} ({got / 2**30:.2f} GiB)", flush=True)


if __name__ == "__main__":
    main()
