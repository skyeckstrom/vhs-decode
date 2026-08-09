"""Tests that JSONDumper streams field records instead of rewriting the file.

JSONDumper's writer thread used to keep the serialized JSON of every field in a
list and rewrite the whole of .tbc.json from that list on every dump. That had
two costs: the list was never trimmed, so the thread's memory grew with the
length of the capture (~300 bytes per field on NTSC, ~130 MB across a three-hour
tape), and rewriting a file that ends up over 100 MB every 500 fields made write
volume grow with the square of the capture length.

Records are now appended once, where the previous dump left off, and only the
closing bracket and the trailing metadata are rewritten each time. "fields"
moved to the front of the object so the array can be extended in place; the
metadata after it carries numberOfSequentialFields, which grows a digit at a
time and so cannot sit at a fixed offset ahead of the array.

These drive JSONDumper against a stub decoder. Constructing a real LDdecode needs
an RF source and a populated DemodCache, which is far more scaffolding than the
"serialize what you are handed, write it to a file" contract under test.
"""

import json
import os
import threading
import time
import tracemalloc

import pytest

from lddecode.utils import FieldInfo, JSONDumper


class _StubLDD:
    """Stands in for LDdecode: supplies the metadata dict and the field queue.

    The real FieldInfo is used rather than a fake one because its read()-drains
    semantics are half of what is being tested -- fields handed over across
    several dumps have to end up in one correctly separated array.
    """

    def __init__(self, verboseVITS=False):
        self.fieldinfo = FieldInfo()
        self.verboseVITS = verboseVITS

    def build_json(self):
        return {
            "pcmAudioParameters": {"bits": 16, "sampleRate": 44100},
            "videoParameters": {"numberOfSequentialFields": len(self.fieldinfo)},
        }


def _field(seq):
    """A field record shaped like a real one (see LDdecode.build_json)."""
    return {
        "seqNo": seq,
        "isFirstField": seq % 2 == 0,
        "syncConf": 100,
        "diskLoc": seq * 1.5,
        "fileLoc": seq * 1234567,
        "vitsMetrics": {"wSNR": 32.5 + (seq % 7), "bPSNR": 41.0},
    }


def _expected(meta, fields, verbose):
    """The .tbc.json format, written out plainly.

    Deliberately not a copy of the implementation: it is the format the output
    has to match, built the most obvious way.
    """
    indent = 4 if verbose else None
    linebreak = "\n" if verbose else ""
    separators = None if verbose else (",", ":")
    sep = "," + linebreak

    def dump(obj):
        return json.dumps(obj, allow_nan=False, indent=indent, separators=separators)

    out = "{" + linebreak + '"fields":[' + linebreak
    out += sep.join(dump(f) for f in fields)
    out += linebreak + "]"
    for k, v in meta.items():
        out += sep + dump(k) + ":" + dump(v)
    out += linebreak + "}" + "\n"
    return out


def _run(tmp_path, batches, verbose=False):
    """Feed `batches` (lists of fields) through a dumper and return the output."""
    os.makedirs(tmp_path, exist_ok=True)
    outname = os.path.join(tmp_path, "capture")
    ldd = _StubLDD(verboseVITS=verbose)
    dumper = JSONDumper(ldd, outname)

    for batch in batches:
        for f in batch:
            ldd.fieldinfo.append(f)
        dumper.write()

    dumper.close()  # flushes whatever the throttled write()s left pending
    with open(outname + ".tbc.json") as fh:
        return fh.read(), ldd


@pytest.mark.parametrize("verbose", [False, True], ids=["compact", "verboseVITS"])
def test_output_format(tmp_path, verbose):
    """The written file matches the format exactly, in both output modes."""
    fields = [_field(i) for i in range(50)]
    got, ldd = _run(tmp_path, [fields[:20], fields[20:35], fields[35:]], verbose)

    assert got == _expected(ldd.build_json(), fields, verbose)


def test_records_from_separate_dumps_are_separated(tmp_path):
    """Records accumulated over many small dumps form one valid array.

    The separator between two records now straddles a dump boundary -- it is
    written when the *next* record arrives rather than when the whole list is
    re-joined -- so this is the case most likely to regress into ',,' or a
    missing comma.
    """
    fields = [_field(i) for i in range(40)]
    got, _ = _run(tmp_path, [[f] for f in fields])  # one field per dump

    assert [f["seqNo"] for f in json.loads(got)["fields"]] == list(range(40))


def test_empty_dumps_do_not_emit_separators(tmp_path):
    """A dump with no new fields must not leave a stray comma behind."""
    got, _ = _run(tmp_path, [[], [_field(0)], [], [_field(1)], []])

    assert [f["seqNo"] for f in json.loads(got)["fields"]] == [0, 1]


def test_no_fields_at_all(tmp_path):
    """A decode that produces nothing still writes a parseable file."""
    got, _ = _run(tmp_path, [[]])

    assert json.loads(got)["fields"] == []


def test_each_dump_leaves_a_complete_file(tmp_path):
    """Every dump closes the array and re-appends the metadata, not just the last.

    An interrupted decode has to leave usable metadata for the fields it did
    manage to write, which is the property the periodic rewrite exists for. The
    array is extended in place now, so this checks the tail really is rewritten
    each time rather than only at close().

    Note this samples *between* dumps, once the writer has settled. A reader
    looking at the file while a dump is in progress can catch a partial write --
    the previous implementation replaced the file atomically and could not. See
    the commit message.
    """
    os.makedirs(tmp_path, exist_ok=True)
    outname = os.path.join(tmp_path, "capture")
    ldd = _StubLDD()
    dumper = JSONDumper(ldd, outname)

    for seq in range(30):
        ldd.fieldinfo.append(_field(seq))
        dumper.write()

        # write() is a no-op while a dump is in flight, so wait for the file to
        # catch up to what has been handed over rather than assuming one landed.
        doc = _await_fields(dumper, outname, seq + 1)
        assert doc["videoParameters"]["numberOfSequentialFields"] == len(doc["fields"])

    dumper.close()


def _await_fields(dumper, outname, expected, timeout=60):
    """Wait until the output lists `expected` fields, and return it parsed."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        dumper.write()
        try:
            with open(outname + ".tbc.json") as fh:
                doc = json.load(fh)
            if len(doc["fields"]) == expected:
                return doc
            last = f"saw {len(doc['fields'])} fields"
        except FileNotFoundError:
            last = "file not created yet"
        except ValueError as err:
            last = f"unparseable mid-dump: {err}"
        time.sleep(0.01)
    pytest.fail(f"writer never reached {expected} fields ({last})")


def test_shrinking_metadata_does_not_leave_trailing_junk(tmp_path):
    """The file is truncated when a later dump writes a shorter tail.

    numberOfSequentialFields is written after the array, so its width grows as
    the decode runs -- but a caller whose metadata shrinks (or a final dump with
    fewer members) must not leave the tail of the previous, longer write behind.
    """
    os.makedirs(tmp_path, exist_ok=True)
    outname = os.path.join(tmp_path, "capture")

    class Shrinking(_StubLDD):
        def build_json(self):
            # A large metadata block first, then a small one.
            if len(self.fieldinfo) < 10:
                return {"padding": "x" * 500, "n": len(self.fieldinfo)}
            return {"n": len(self.fieldinfo)}

    ldd = Shrinking()
    dumper = JSONDumper(ldd, outname)
    for seq in range(5):
        ldd.fieldinfo.append(_field(seq))
    dumper.write()
    for seq in range(5, 20):
        ldd.fieldinfo.append(_field(seq))
    dumper.close()

    with open(outname + ".tbc.json") as fh:
        raw = fh.read()

    doc = json.loads(raw)  # would raise on leftover bytes past the closing brace
    assert "padding" not in doc
    assert doc["n"] == 20


def test_no_temporary_files_left_behind(tmp_path):
    """Only the output file exists -- no .tmp and no spool."""
    _run(tmp_path, [[_field(i) for i in range(10)]])

    assert sorted(os.listdir(tmp_path)) == ["capture.tbc.json"]


class _SynthQueue:
    """Hands _consume one batch of fields at a time, then the stop sentinel.

    _consume only ever calls get(), so the batches can be synthesized on demand
    instead of queued up front. Queuing them would mean the test itself was
    holding every record while trying to measure what the writer holds.
    """

    def __init__(self, total, batch=500):
        self.total = total
        self.batch = batch
        self.sent = 0

    def get(self):
        if self.sent >= self.total:
            return None

        start, self.sent = self.sent, min(self.sent + self.batch, self.total)
        meta = {"videoParameters": {"numberOfSequentialFields": self.sent}}
        return meta, [_field(seq) for seq in range(start, self.sent)]


def _writer_peak(n, tmp_path):
    """Peak memory _consume holds while writing `n` fields."""
    os.makedirs(tmp_path, exist_ok=True)
    outname = os.path.join(tmp_path, "capture")

    tracemalloc.start()
    tracemalloc.reset_peak()
    JSONDumper._consume(_SynthQueue(n), threading.Event(), outname, False)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    return peak


def test_writer_memory_does_not_grow_with_field_count(tmp_path):
    """What the writer holds must not scale with the number of fields.

    The old implementation kept every serialized record for the life of the
    decode, so its peak tracked the payload; streaming holds only the batch
    being written. The bound is a fraction of the payload rather than a fixed
    number of bytes, so the test says "does not scale" instead of encoding
    today's constant overhead.

    _consume is driven directly rather than through a thread: it is a plain
    loop over queue.get(), so calling it synchronously makes the measurement
    deterministic and keeps the writer the only thing allocating.
    """
    small, large = 2000, 40000
    payload_growth = sum(
        len(json.dumps(_field(i), separators=(",", ":"))) for i in range(small, large)
    )

    growth = _writer_peak(large, tmp_path / "large") - _writer_peak(
        small, tmp_path / "small"
    )

    assert growth < payload_growth / 4, (
        f"writer peak grew by {growth} bytes for {large - small} more fields "
        f"({payload_growth} bytes of records); it should not scale with field count"
    )


class _CountingFile:
    """Wraps the output file and totals everything written through it."""

    def __init__(self, fh, total):
        self._fh = fh
        self._total = total

    def write(self, data):
        self._total[0] += len(data)
        return self._fh.write(data)

    def __getattr__(self, name):
        return getattr(self._fh, name)


def _bytes_written(n, tmp_path, monkeypatch):
    """Total bytes the writer puts through its file object for `n` fields."""
    os.makedirs(tmp_path, exist_ok=True)
    outname = os.path.join(tmp_path, "capture")
    total = [0]

    # lddecode.utils uses the builtin open(); setting one on the module shadows
    # it for that module only, and monkeypatch removes it afterwards.
    real_open = open
    monkeypatch.setattr(
        "lddecode.utils.open",
        lambda *a, **kw: _CountingFile(real_open(*a, **kw), total),
        raising=False,
    )

    ldd = _StubLDD()
    dumper = JSONDumper(ldd, outname)
    for i in range(0, n, 100):
        for seq in range(i, min(i + 100, n)):
            ldd.fieldinfo.append(_field(seq))
        dumper.write()
    dumper.close()

    return total[0]


def test_bytes_written_do_not_grow_quadratically(tmp_path, monkeypatch):
    """Doubling the field count must not quadruple the bytes written.

    This is the other half of the regression. Rewriting the whole file on every
    dump made total write volume grow with the square of the capture length;
    appending makes it linear. Counting what goes through the file object keeps
    this independent of filesystem accounting.

    The bound is loose because the tail is rewritten every dump, so the total is
    linear plus a small constant per dump -- nowhere near the 4x that squaring
    would give.
    """
    small = _bytes_written(2000, tmp_path / "small", monkeypatch)
    large = _bytes_written(4000, tmp_path / "large", monkeypatch)

    ratio = large / small
    assert ratio < 3, (
        f"writes grew {ratio:.1f}x for 2x the fields "
        f"({small} -> {large} bytes); expected roughly linear"
    )
