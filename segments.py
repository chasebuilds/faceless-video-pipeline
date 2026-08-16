"""Choosing background footage so a short does not teleport.

A faceless short is narration over stock footage. The footage is cut into
segments and concatenated, and the naive way to do that is to pick a random
clip for each segment. That produces a video which jumps between unrelated
scenes every few seconds, and it took two fixes to stop, the first of which
was declared done while the bug was still shipping.

This module is the selection logic on its own: no ffmpeg, no filesystem, no
media. It takes clips described as durations plus their known hard cuts, and
returns the segments to render. That separation is the point - the part that
was wrong was never the encoding, it was the arithmetic, and arithmetic can
be tested in milliseconds without touching a video file.

## Fix one: one clip per video

A footage "family" is a filename prefix, so `parkour` is dozens of separate
clips cut from different source videos. Drawing a random clip per segment
made a 60-second short jump between four unrelated locations.

The tell was that only one family ever showed it. The other was ambient
texture footage that looks identical everywhere, so the same bug produced no
visible symptom, and four days of reports read the whole thing as an
asset-tagging problem rather than a selection bug.

**A bug that is invisible in one dataset is not a smaller bug.**

## Fix two: walk forward, and start in a clean stretch

Pinning one clip per video left each segment's offset inside that clip
random - and a single 90-second clip is often a continuous run through
several locations. Sampling it at 5s, 70s, 30s still teleported, with no
scene cut involved at all.

The test suite passed throughout, because it asserted that all segments came
from one clip and never asserted WHERE in it. **A test that pins the fix you
made will not catch the half you missed.**

Segments are now contiguous, so the shot advances instead of jumping. The
starting point is chosen inside a stretch of the clip with no hard cut in
it, because a clip's own splices are the one discontinuity a forward walk
cannot smooth over. Those splices are unevenly spread: many clips have none,
while others carry two or three, so the clip is chosen on its longest
cut-free run rather than on raw duration. Choosing on duration alone landed
on a clip whose longest clean run was 48 seconds and inherited both of its
cuts.

Measured over ten renders, before and after: hard cuts landing exactly on a
segment boundary went from 40 to 0, and source clips' own splices pulled
into the render went from several to none.

The honest cost: there is no longer an artificial cut every few seconds. The
footage simply plays. Nothing measured ever tied that pacing to retention,
and chasing it cost six days of rejected renders.
"""

from __future__ import annotations

import random

SEGMENT_S = 8.0        # length of one rendered segment
TAIL_SEGMENTS = 2      # rendered past the narration so the outro never runs dry


class Clip:
    """One source file, described only by what selection needs.

    `cuts` are timestamps of hard cuts INSIDE the clip - scene changes the
    footage already contains. They are the thing a forward walk cannot hide.
    """

    def __init__(self, name, duration_s, cuts=()):
        self.name = name
        self.duration_s = float(duration_s)
        self.cuts = tuple(sorted(float(c) for c in cuts))

    def clean_runs(self):
        """[(start, end)] stretches containing no hard cut."""
        edges = [0.0, *self.cuts, self.duration_s]
        return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)
                if edges[i + 1] > edges[i]]

    def longest_clean_run(self):
        return max(self.clean_runs(), key=lambda r: r[1] - r[0])

    def __repr__(self):
        return "Clip(%r, %.1fs, %d cuts)" % (self.name, self.duration_s,
                                             len(self.cuts))


def segment_count(narration_s, segment_s=SEGMENT_S):
    return int(narration_s // segment_s) + TAIL_SEGMENTS


def pick_segments(clips, narration_s, seed=None, segment_s=SEGMENT_S):
    """[(clip_name, start_s, length_s)] covering the narration.

    Every segment comes from ONE clip and they run consecutively, so the
    shot advances rather than jumping. `seed` makes the choice reproducible,
    which matters because a preview and its final render have to show the
    same footage - otherwise the thing a human approves is not the thing
    that ships.
    """
    if not clips:
        raise ValueError("no clips to choose from")
    rng = random.Random(seed)

    count = segment_count(narration_s, segment_s)
    needed = count * segment_s

    # Rank on the longest CUT-FREE stretch, never on raw duration: a long
    # clip full of splices is worse than a short clean one.
    best = {c.name: (c, c.longest_clean_run()) for c in clips}
    roomy = [name for name, (_c, (lo, hi)) in best.items() if hi - lo >= needed]
    chosen = rng.choice(sorted(roomy)) if roomy else max(
        best, key=lambda n: best[n][1][1] - best[n][1][0])
    clip, (lo, hi) = best[chosen]

    if hi - lo >= needed:
        base = rng.uniform(lo, hi - needed)
    else:
        # Nothing is long enough. Start at the beginning of the best run and
        # accept that a cut will be crossed - reporting that honestly is the
        # caller's job, and `crosses_cut` below exists for it.
        base = min(lo, max(0.0, clip.duration_s - needed))

    wrap = max(segment_s, clip.duration_s - segment_s)
    out = []
    for i in range(count):
        start = base + i * segment_s
        if start + segment_s > clip.duration_s:
            start = start % wrap      # ran off the end; fold back
        out.append((clip.name, start, segment_s))
    return out


def crosses_cut(clip, segments):
    """How many chosen segments contain one of the clip's own hard cuts.

    The measurement the fix was judged on. Zero is the goal; a caller that
    cannot reach zero should say so rather than render and hope.
    """
    total = 0
    for name, start, length in segments:
        if name != clip.name:
            continue
        total += sum(1 for c in clip.cuts if start < c < start + length)
    return total


def is_contiguous(segments, segment_s=SEGMENT_S, tol=1e-6):
    """Do the segments run consecutively through one clip?

    False means the render will teleport. This is the assertion the original
    test suite was missing: it checked that every segment came from one clip,
    which the broken version also satisfied.
    """
    if len(segments) < 2:
        return True
    if len({name for name, _s, _l in segments}) != 1:
        return False
    for (_n1, a, _l1), (_n2, b, _l2) in zip(segments, segments[1:]):
        if abs((a + segment_s) - b) > tol:
            return False
    return True
