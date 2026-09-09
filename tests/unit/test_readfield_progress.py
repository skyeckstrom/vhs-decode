"""Tests that readfield() keeps moving forward through a damaged section.

readfield() loops until a field decodes, resuming each failed attempt at the
offset that attempt handed back. compute_linelocs() has a path that hands back
a single line -- max(line0loc - meanlinelen * 20, self.inlinelen) -- and the
offset is a deterministic function of the data, so where a line of skip is not
enough to clear the damage the next attempt fails for the same reason. The
decode then crawls a line at a time, starting a decode thread for each attempt,
with nothing reaching the output file.

The decodefield() stub below stands in for that, and for the hunting the
decoder does legitimately on damaged tape, which fails just as often but covers
ground while it does.
"""

import logging
import types

import pytest

import lddecode.core as ldd
from vhsdecode.process import VHSDecode


LINELEN = 2542  # input samples per line, NTSC VHS sampled at 40 MHz
OUTPUT_LINES = 263  # (SysParams["frame_lines"] // 2) + 1
FIELD = LINELEN * OUTPUT_LINES

# compute_linelocs() returns this where it cannot place the start of a field.
HUNT_SKIP = LINELEN * 100

# Long enough that a line-at-a-time crawl cannot cross it inside the attempt
# budget, short enough that skipping a field at a time crosses it easily.
DAMAGE_LEN = FIELD * 40
ATTEMPT_BUDGET = 500


@pytest.fixture(autouse=True)
def _logger():
    if getattr(ldd, "logger", None) is None:
        ldd.logger = logging.getLogger("test")


class _RanAway(Exception):
    """More decode attempts than a loop that terminates could need."""


def _decoded_field():
    """A field that processed cleanly, stubbed down to what readfield() reads."""
    return types.SimpleNamespace(
        valid=True,
        needrerun=False,
        isFirstField=True,
        sync_confidence=0,
        downscale=lambda **kwargs: (None, None, None),
    )


class _Decoder:
    """Only the attributes VHSDecode.readfield() reaches for.

    Data before ``damage_len`` decodes to nothing; from there on every field
    decodes. fname_out is None so readfield() returns before the metadata and
    writeout half, which is not what is under test here.
    """

    def __init__(self, damage_len=DAMAGE_LEN, damage_skip=LINELEN):
        self.damage_len = damage_len
        self.damage_skip = damage_skip
        self.starts = []

        self.fieldstack = []
        self.threadreturn = {}
        self.decodethread = None
        self.numthreads = 0  # decode inline, so the test stays single threaded
        self.fdoffset = 0
        self.mtf_level = 0
        self.second_decode = None
        self.fields_written = 0
        self.lastFieldWritten = None
        self.analog_audio = False
        self.useAGC = False
        self.fname_out = None
        self.output_lines = OUTPUT_LINES
        self.rf = types.SimpleNamespace(linelen=LINELEN)

    def computeMetrics(self, *args, **kwargs):
        return {}

    def decodefield(
        self, start, mtf_level, prevfield=None, initphase=False, redo=False, rv=None
    ):
        """Damaged data yields an invalid field asking to resume damage_skip on."""
        if len(self.starts) >= ATTEMPT_BUDGET:
            raise _RanAway(
                "%d decode attempts and still at sample %d" % (len(self.starts), start)
            )
        self.starts.append(start)

        if start < self.damage_len:
            field, offset = types.SimpleNamespace(valid=False), self.damage_skip
        else:
            field, offset = _decoded_field(), FIELD

        rv["field"], rv["offset"] = field, offset
        return field, offset


def test_damage_is_skipped_over_rather_than_crawled_through():
    """The whole point: a section that never decodes must not stall the decode."""
    decoder = _Decoder()

    field = VHSDecode.readfield(decoder)

    assert field.valid
    assert decoder.fdoffset >= DAMAGE_LEN
    # A line-at-a-time crawl would need DAMAGE_LEN // LINELEN attempts, which is
    # well past the budget; skipping a field at a time needs a few dozen.
    assert len(decoder.starts) < ATTEMPT_BUDGET


def test_a_field_that_decodes_is_left_alone():
    """No damage, so the guard must not touch the offset or the attempt count."""
    decoder = _Decoder(damage_len=0)

    field = VHSDecode.readfield(decoder)

    assert field.valid
    # The field itself, then the speculative decode of the one after it.
    assert decoder.starts == [0, FIELD]
    # Advanced by exactly what decodefield() asked for, nothing added.
    assert decoder.fdoffset == FIELD


def test_a_short_run_of_bad_fields_uses_the_decoder_s_own_offsets():
    """Recovering on its own must not be cut short by the guard.

    Four lines of damage, so the decoder finds its way out long before any
    attempt limit. Every attempt has to land exactly where it asked to, a line
    on from the last -- not on some skip imposed from outside.
    """
    decoder = _Decoder(damage_len=LINELEN * 4)

    field = VHSDecode.readfield(decoder)

    assert field.valid
    assert decoder.starts == [
        0,
        LINELEN,
        LINELEN * 2,
        LINELEN * 3,
        LINELEN * 4,
        LINELEN * 4 + FIELD,
    ]
    assert decoder.fdoffset == LINELEN * 4 + FIELD


def test_a_hunt_that_covers_ground_is_left_to_run():
    """Failing over and over is how the decoder hunts, and must stay untouched.

    compute_linelocs() asks for 100 lines when it cannot place the start of a
    field. That fails as often as the crawl does, but each attempt covers real
    tape, so it is the decoder working -- not a stall. Every attempt has to land
    exactly 100 lines on from the last, with nothing rounded up to a field.
    """
    decoder = _Decoder(damage_len=FIELD * 30, damage_skip=HUNT_SKIP)

    field = VHSDecode.readfield(decoder)

    assert field.valid
    hunting = decoder.starts[:-1]
    assert len(hunting) > 60  # well past any window of attempts
    assert hunting == [HUNT_SKIP * n for n in range(len(hunting))]
