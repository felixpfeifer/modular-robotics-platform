"""Read-only MCAP summary: topics, message counts and duration without a third-party reader.

MCAP files written by the recorder carry a summary section (schemas, channels and
statistics) near the end of the file. Only that tail is read, so inspecting a
multi-gigabyte episode is cheap. Files without a summary index are reported as such
rather than scanned.
"""

import struct
from pathlib import Path

MAGIC = b"\x89MCAP0\r\n"
OP_SCHEMA, OP_CHANNEL, OP_FOOTER, OP_STATISTICS = 0x03, 0x04, 0x02, 0x0B
FOOTER_RECORD = 1 + 8 + 20  # opcode + length + (u64, u64, u32)
MAX_SUMMARY = 16 * 1024 * 1024


class McapError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise McapError("Truncated MCAP record.")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def unpack(self, fmt):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))

    def string(self):
        (length,) = self.unpack("I")
        return self.take(length).decode("utf-8", "replace")

    def string_map(self):
        (length,) = self.unpack("I")
        inner = _Reader(self.take(length))
        result = {}
        while inner.pos < len(inner.data):
            key = inner.string()
            result[key] = inner.string()
        return result


def summarize(path):
    """Return {topics, message_count, start_ns, end_ns, duration_s, has_summary, size_bytes}."""
    path = Path(path)
    size = path.stat().st_size
    result = {
        "size_bytes": size,
        "has_summary": False,
        "message_count": None,
        "start_ns": None,
        "end_ns": None,
        "duration_s": None,
        "topics": [],
    }
    tail = len(MAGIC) + FOOTER_RECORD
    if size < len(MAGIC) + tail:
        raise McapError("File is too small to be an MCAP recording.")
    with path.open("rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise McapError("File does not start with the MCAP magic bytes.")
        source.seek(size - tail)
        footer = source.read(tail)
        if footer[-len(MAGIC) :] != MAGIC:
            raise McapError("MCAP file is incomplete (no closing magic); the recorder may not have finished.")
        opcode, length = struct.unpack("<BQ", footer[:9])
        if opcode != OP_FOOTER or length != 20:
            raise McapError("MCAP footer is malformed.")
        summary_start, _offsets, _crc = struct.unpack("<QQI", footer[9:29])
        if not summary_start:
            return result
        summary_length = size - tail - summary_start
        if not 0 <= summary_length <= MAX_SUMMARY or summary_start < len(MAGIC):
            raise McapError("MCAP summary section is out of range.")
        source.seek(summary_start)
        summary = source.read(summary_length)
    schemas, channels, stats = {}, {}, None
    reader = _Reader(summary)
    while reader.pos < len(summary):
        opcode, length = reader.unpack("BQ")
        body = _Reader(reader.take(length))
        if opcode == OP_SCHEMA:
            ident, name, _encoding = body.unpack("H")[0], body.string(), body.string()
            schemas[ident] = name
        elif opcode == OP_CHANNEL:
            ident, schema_id = body.unpack("HH")
            channels[ident] = {
                "topic": body.string(),
                "message_encoding": body.string(),
                "schema_id": schema_id,
            }
        elif opcode == OP_STATISTICS:
            count, _schemas, _channels, _attach, _meta, _chunks, start, end = body.unpack("QHIIIIQQ")
            (map_length,) = body.unpack("I")
            counts, inner = {}, _Reader(body.take(map_length))
            while inner.pos < len(inner.data):
                channel, messages = inner.unpack("HQ")
                counts[channel] = messages
            stats = {"count": count, "start": start, "end": end, "counts": counts}
    result["has_summary"] = True
    topics = []
    for ident, channel in channels.items():
        messages = (stats or {}).get("counts", {}).get(ident)
        topics.append(
            {
                "topic": channel["topic"],
                "type": schemas.get(channel["schema_id"], ""),
                "encoding": channel["message_encoding"],
                "messages": messages,
            }
        )
    topics.sort(key=lambda item: item["topic"])
    result["topics"] = topics
    if stats:
        result["message_count"] = stats["count"]
        if stats["count"]:
            result["start_ns"], result["end_ns"] = stats["start"], stats["end"]
            result["duration_s"] = round((stats["end"] - stats["start"]) / 1e9, 3)
    return result
