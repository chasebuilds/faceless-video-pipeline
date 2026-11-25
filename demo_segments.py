"""Run the footage selection on three made-up clips and show what it picks.

No media and no network: clips are described by duration and hard-cut times,
exactly what segments.py works from. Usage: python demo_segments.py [seed]
"""

import sys

from segments import Clip, crosses_cut, is_contiguous, pick_segments, segment_count

CLIPS = [
    # A long clip that is spliced from several locations: longest clean run is 21 s.
    Clip("rooftops_long", 95.0, cuts=[18.0, 39.0, 57.0, 74.0]),
    # Shorter, but one continuous 52 s take after a cut at 6 s.
    Clip("alley_run", 60.0, cuts=[6.0, 58.0]),
    # No cuts at all.
    Clip("stairwell", 44.0),
]
NARRATION_S = 31.0


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"narration {NARRATION_S:.0f} s -> {segment_count(NARRATION_S)} segments of 8 s, seed {seed}")
    for c in CLIPS:
        lo, hi = c.longest_clean_run()
        print(f"  {c!r:38} longest clean run {lo:5.1f}-{hi:5.1f} s ({hi - lo:4.1f} s)")
    segs = pick_segments(CLIPS, NARRATION_S, seed=seed)
    clip = next(c for c in CLIPS if c.name == segs[0][0])
    print(f"picked {clip.name}:")
    for name, start, length in segs:
        print(f"  {name} {start:6.2f} -> {start + length:6.2f} s")
    print(f"contiguous: {is_contiguous(segs)}   segments crossing a hard cut: {crosses_cut(clip, segs)}")
    again = pick_segments(CLIPS, NARRATION_S, seed=seed)
    print(f"same seed gives the same footage (preview == final render): {again == segs}")


if __name__ == "__main__":
    main()
