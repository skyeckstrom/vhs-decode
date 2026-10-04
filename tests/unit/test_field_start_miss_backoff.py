"""Crossing a long stretch with no field to find must not take days.

When compute_linelocs() cannot find the start of a field it drops it and steps on 100
lines. Across unrecorded tape -- the rest of a cassette after the recording ends -- every
attempt misses, so at 100 lines a time the decoder crosses it at a few percent of real
time and writes nothing. After a run of misses the step grows, up to the 100 ms used when
no sync pulses are found at all, and the first field found sets it back.
"""

import logging

import numpy as np
import pytest

import lddecode.core as ldd
import vhsdecode.process as process
from vhsdecode.field import FieldNTSCVideo8


@pytest.fixture
def rf():
    ldd.logger = logging.getLogger("test")
    return process.VHSRFDecode(inputfreq=40, system="NTSC", tape_format="VIDEO8")


def _step(rf, found):
    """One compute_linelocs(); `found` decides whether the field's start is found.

    A found field is placed late in the block so it is rejected as short, which
    returns before anything else in the field has to be real.
    """
    readlen = int((rf.linelen * 350) // 16384) * 16384
    field = FieldNTSCVideo8(rf, {"input": np.zeros(readlen), "video": {}})
    line0loc = readlen - 100 * rf.linelen
    first_hsync = (line0loc + 10 * rf.linelen) if found else None
    field.validpulses = []
    field.isFirstField = True
    field._try_get_pulses = lambda do_level_detect: (
        line0loc, first_hsync, 10, float(rf.linelen), None
    )
    _, _, offset = field.compute_linelocs()
    return offset


def test_misses_step_100_lines_then_grow_to_100ms(rf):
    steps = [_step(rf, found=False) for _ in range(20)]
    hundred_lines = rf.linelen * 100
    hundred_ms = int(rf.freq_hz / 10)

    assert steps[:10] == [hundred_lines] * 10
    assert steps[10:13] == [hundred_lines * 2, hundred_lines * 4, hundred_lines * 8]
    assert max(steps) == hundred_ms
    assert steps[-1] == hundred_ms


def test_finding_a_field_resets_the_step(rf):
    for _ in range(20):
        _step(rf, found=False)

    _step(rf, found=True)

    assert _step(rf, found=False) == rf.linelen * 100
