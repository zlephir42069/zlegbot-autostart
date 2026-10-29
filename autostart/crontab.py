"""Marker-delimited crontab blocks.

The markers are full lines::

    # BEGIN autostart:<marker>
    ...entries...
    # END autostart:<marker>

A second apply with the same lines does not rewrite the crontab. Text outside
the block is preserved. An unclosed marker aborts without writing.
"""

from __future__ import annotations

from autostart.errors import CrontabError

INSTALL_MARKER = "zlegbot-autostart"


def begin_line(marker: str) -> str:
    return f"# BEGIN autostart:{marker}"


def end_line(marker: str) -> str:
    return f"# END autostart:{marker}"


def upsert(text: str, marker: str, body: list[str]) -> tuple[str, bool]:
    """Return ``(new_text, changed)``. ``changed`` is false when the block already matches."""
    lines = text.splitlines()
    ranges = _marker_ranges(lines, marker)
    skip = _indexes(ranges)
    kept = [line for index, line in enumerate(lines) if index not in skip]
    while kept and kept[-1] == "":
        kept.pop()
    block = [begin_line(marker), *body, end_line(marker)]
    new_lines = kept + [""] + block if kept else block
    new_text = "\n".join(new_lines) + "\n"
    current = text if text.endswith("\n") or text == "" else text + "\n"
    return new_text, new_text != current


def remove_block(text: str, marker: str) -> tuple[str, bool]:
    """Return ``(new_text, changed)``. Missing markers are not a change."""
    if text == "":
        return "", False
    lines = text.splitlines()
    ranges = _marker_ranges(lines, marker)
    if not ranges:
        return text, False
    skip = _indexes(ranges)
    kept = [line for index, line in enumerate(lines) if index not in skip]
    while kept and kept[-1] == "":
        kept.pop()
    if not kept:
        return "", True
    return "\n".join(kept) + "\n", True


def install_lines(host, marker: str, body: list[str]) -> str:
    """Merge ``body`` into the user crontab. Returns ``updated`` or ``unchanged``."""
    current = host.read_crontab()
    updated, changed = upsert(current, marker, body)
    if not changed:
        return "unchanged"
    host.write_crontab(updated)
    return "updated"


def uninstall_marker(host, marker: str) -> str:
    """Remove one marker block. Returns ``removed`` or ``unchanged``."""
    current = host.read_crontab()
    updated, changed = remove_block(current, marker)
    if not changed:
        return "unchanged"
    host.write_crontab(updated)
    return "removed"


def _marker_ranges(lines: list[str], marker: str) -> list[tuple[int, int]]:
    begin = begin_line(marker)
    end = end_line(marker)
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == begin:
            start = index
            index += 1
            while index < len(lines) and lines[index].strip() != end:
                if lines[index].strip() == begin:
                    raise CrontabError(f"nested marker {marker}")
                index += 1
            if index >= len(lines):
                raise CrontabError(f"unclosed marker {marker}")
            ranges.append((start, index))
            index += 1
            continue
        if lines[index].strip() == end:
            raise CrontabError(f"unexpected end marker {marker}")
        index += 1
    return ranges


def _indexes(ranges: list[tuple[int, int]]) -> set[int]:
    skip: set[int] = set()
    for start, end in ranges:
        skip.update(range(start, end + 1))
    return skip


def empty_means_remove(host_error_text: str) -> bool:
    """True when crontab reports that the user has nothing installed."""
    return "no crontab" in host_error_text.lower()
