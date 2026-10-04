"""A field rejected for being too short must not move the sync prediction on.

compute_linelocs() rejects a field whose line 0 falls too late in the block to fit, and
the next attempt reads the same field again from just before line 0. Where the vsync
pulses cannot be read, the field is placed only by predicting it from the previous one.
If the rejected field's own sync is left behind as "the previous field", that prediction
lands a whole field further on -- again too late to fit -- and every attempt after that
skips one field without writing anything.
"""

import logging

import numpy as np
import pytest

import lddecode.core as ldd
import vhsdecode.field as vfield
import vhsdecode.process as process
from vhsdecode.field import FieldNTSCVideo8, Pulse

# The sync state a field leaves on rf for the next one to predict from.
SYNC_STATE = (
    "prev_first_hsync_readloc",
    "prev_first_hsync_loc",
    "prev_first_hsync_diff",
    "prev_first_field",
    "prev_progressive_field",
)


class _Accepted(Exception):
    """Raised once compute_linelocs() goes on to process a field."""


class _SyncUntilAccepted:
    """The real sync module, except that processing a field stops the test there."""

    def __getattr__(self, name):
        return getattr(_real_sync, name)

    def valid_pulses_to_linelocs(self, *args, **kwargs):
        raise _Accepted()


_real_sync = vfield.sync


@pytest.fixture
def rf(monkeypatch):
    ldd.logger = logging.getLogger("test")
    monkeypatch.setattr(vfield, "sync", _SyncUntilAccepted())
    return process.VHSRFDecode(inputfreq=40, system="NTSC", tape_format="VIDEO8")


def _attempt(rf, readloc, readlen):
    """One compute_linelocs() on a block of hsync pulses with no readable vsync.

    Returns None if the field was processed, else the offset to resume from.
    """
    linelen = float(rf.linelen)
    field = FieldNTSCVideo8(rf, {"input": np.zeros(readlen), "video": {}}, readloc=readloc)
    first = int(np.ceil(readloc / linelen))
    last = int((readloc + readlen) // linelen)
    hsyncs = [
        (0, Pulse(int(k * linelen - readloc), 200, 0, 0, 0), True)
        for k in range(first, last)
    ]
    field.get_pulses = lambda do_level_detect=False: hsyncs
    field.refinepulses = lambda: hsyncs
    field.computeLineLen = lambda validpulses: linelen

    try:
        _, _, offset = field.compute_linelocs()
    except _Accepted:
        return None
    return offset


def _last_field_used(rf, first_hsync_loc):
    rf.prev_first_hsync_readloc = 0
    rf.prev_first_hsync_loc = first_hsync_loc
    rf.prev_first_hsync_diff = 0
    rf.prev_first_field = 1
    rf.prev_progressive_field = 0


def test_short_field_is_read_again_rather_than_skipped(rf):
    """After a short field, the very next attempt decodes it."""
    linelen = float(rf.linelen)
    readlen = int((rf.linelen * 350) // 16384) * 16384
    first_hsync = 30 * linelen
    _last_field_used(rf, first_hsync)

    # Start the next read so that the next field begins ~125 lines in: too late to fit.
    readloc = int(first_hsync + 262 * linelen - 125 * linelen)

    for attempt in range(1, 21):
        offset = _attempt(rf, readloc, readlen)
        if offset is None:
            break
        readloc += int(offset)

    assert attempt == 2, "the decode skipped fields instead of reading the short one again"


def test_short_field_leaves_the_previous_sync_state(rf):
    """Rejecting a short field restores exactly what the last used field left."""
    linelen = float(rf.linelen)
    readlen = int((rf.linelen * 350) // 16384) * 16384
    first_hsync = 30 * linelen
    _last_field_used(rf, first_hsync)
    before = {name: getattr(rf, name) for name in SYNC_STATE}

    offset = _attempt(rf, int(first_hsync + 262 * linelen - 125 * linelen), readlen)

    assert offset is not None  # rejected as short
    assert {name: getattr(rf, name) for name in SYNC_STATE} == before
