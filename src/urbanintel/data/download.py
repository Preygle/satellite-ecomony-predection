from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = "urbanintel/0.1 (academic urban growth research)"
CHUNK = 1 << 20  # 1 MiB


class DownloadError(RuntimeError):
    pass


def fetch(
    url: str,
    dest: Path,
    *,
    user_agent: str = DEFAULT_UA,
    timeout: int = 120,
    force: bool = False,
    expected_min_bytes: int = 1024,
) -> Path:
    """Download `url` to `dest`, skipping if already present.

    Downloads to a `.part` file and renames on success, so an interrupted
    run never leaves a truncated file that a later run would treat as cached.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        if dest.stat().st_size >= expected_min_bytes:
            log.info("cached: %s", dest.name)
            return dest
        log.warning("cached file too small, refetching: %s", dest.name)

    part = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": user_agent}

    log.info("downloading %s", url)
    try:
        with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            got = 0
            with part.open("wb") as fh:
                for chunk in r.iter_content(CHUNK):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = 100.0 * got / total
                        print(f"\r    {dest.name}: {got/1e6:7.1f}/{total/1e6:.1f} MB ({pct:5.1f}%)",
                              end="", flush=True)
            if total:
                print()
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"failed to download {url}: {exc}") from exc

    if part.stat().st_size < expected_min_bytes:
        size = part.stat().st_size
        part.unlink(missing_ok=True)
        raise DownloadError(f"downloaded file implausibly small ({size} B): {url}")

    part.replace(dest)
    return dest


def head_ok(url: str, *, user_agent: str = DEFAULT_UA, timeout: int = 30) -> bool:
    """True if `url` exists and is fetchable (uses a 1-byte range GET).

    A plain HEAD is unreliable on some of these servers; a ranged GET is not.
    """
    try:
        r = requests.get(
            url, headers={"User-Agent": user_agent, "Range": "bytes=0-0"}, timeout=timeout
        )
        return r.status_code in (200, 206)
    except requests.RequestException:
        return False


def unzip_one(archive: Path, pattern: str, dest_dir: Path, *, force: bool = False) -> Path:
    """Extract the single member of `archive` whose name ends with `pattern`.

    Raises if zero or more than one member matches, so a change in the
    upstream packaging surfaces immediately rather than silently picking
    the wrong file.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(pattern.lower())]
        if not members:
            raise DownloadError(
                f"no member ending in {pattern!r} in {archive.name}; "
                f"contents: {zf.namelist()[:10]}"
            )
        if len(members) > 1:
            raise DownloadError(f"ambiguous: {len(members)} members match {pattern!r} in {archive.name}")

        member = members[0]
        out = dest_dir / Path(member).name
        if out.exists() and not force:
            return out
        with zf.open(member) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return out
