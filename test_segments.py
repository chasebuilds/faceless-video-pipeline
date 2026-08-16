"""Tests for background segment selection.

Every case here is a real defect that shipped, not a hypothetical. The two
that matter most are the ones the original suite did NOT have: contiguity,
and where in the clip the walk starts.

Run:  python test_segments.py
"""

from __future__ import annotations

import unittest

from segments import (SEGMENT_S, Clip, crosses_cut, is_contiguous,
                      pick_segments, segment_count)


def clips(n=6, duration=90.0, cuts=()):
    return [Clip("clip-%02d" % i, duration, cuts) for i in range(n)]


class TestOneClipPerVideo(unittest.TestCase):
    """Fix one. Drawing a random clip per segment made a 60-second short
    jump between four unrelated locations."""

    def test_every_segment_comes_from_a_single_clip(self):
        segs = pick_segments(clips(), narration_s=60, seed=1)
        self.assertEqual(len({name for name, _s, _l in segs}), 1)

    def test_it_holds_across_many_seeds(self):
        for seed in range(40):
            segs = pick_segments(clips(), narration_s=60, seed=seed)
            self.assertEqual(len({n for n, _s, _l in segs}), 1, "seed %d" % seed)


class TestForwardWalk(unittest.TestCase):
    """Fix two, and the assertion the original suite was missing.

    Pinning one clip left each segment's offset inside it random, and a
    single 90-second clip is often a continuous run through several
    locations. The suite passed the whole time because it checked only that
    all segments shared a clip - which the broken version also did.
    """

    def test_segments_run_consecutively(self):
        segs = pick_segments(clips(), narration_s=60, seed=7)
        self.assertTrue(is_contiguous(segs), segs)

    def test_a_shuffled_walk_is_detected_as_broken(self):
        """The guard has to be able to FAIL, or it proves nothing."""
        segs = pick_segments(clips(), narration_s=60, seed=7)
        scrambled = [segs[0], segs[2], segs[1]] + list(segs[3:])
        self.assertFalse(is_contiguous(scrambled))

    def test_contiguity_holds_across_many_seeds(self):
        for seed in range(40):
            self.assertTrue(
                is_contiguous(pick_segments(clips(), narration_s=45, seed=seed)),
                "seed %d" % seed)


class TestAvoidingTheClipsOwnCuts(unittest.TestCase):
    """A clip's own splices are the one discontinuity a forward walk cannot
    smooth over, and they are unevenly spread across footage."""

    def test_a_clean_clip_is_preferred_over_a_longer_spliced_one(self):
        spliced = Clip("long-but-spliced", 200.0, cuts=[40, 80, 120, 160])
        clean = Clip("short-but-clean", 120.0, cuts=[])
        segs = pick_segments([spliced, clean], narration_s=60, seed=3)
        self.assertEqual(segs[0][0], "short-but-clean")

    def test_the_walk_does_not_cross_a_cut_when_it_does_not_have_to(self):
        clip = Clip("mixed", 200.0, cuts=[30.0, 150.0])
        segs = pick_segments([clip], narration_s=60, seed=11)
        self.assertEqual(crosses_cut(clip, segs), 0)

    def test_choosing_on_duration_alone_would_have_picked_the_wrong_clip(self):
        """The measured regression: the clip that was longest OVERALL was
        chopped into short runs by its own splices, so its longest clean
        stretch was far too short for the video, and picking it inherited
        those cuts."""
        chopped = Clip("longest-overall", 300.0,
                       cuts=[48.0, 96.0, 144.0, 192.0, 240.0])   # best run 60s
        cleaner = Clip("cleaner", 150.0, cuts=[])                # best run 150s
        self.assertEqual(max([chopped, cleaner],
                             key=lambda c: c.duration_s).name, "longest-overall")
        self.assertGreater(
            cleaner.longest_clean_run()[1] - cleaner.longest_clean_run()[0],
            chopped.longest_clean_run()[1] - chopped.longest_clean_run()[0])

        segs = pick_segments([chopped, cleaner], narration_s=80, seed=5)
        self.assertEqual(segs[0][0], "cleaner")
        self.assertEqual(crosses_cut(cleaner, segs), 0)


class TestDeterminism(unittest.TestCase):
    """A preview and its final render must show the same footage, or the
    thing a human approves is not the thing that ships."""

    def test_the_same_seed_gives_the_same_segments(self):
        a = pick_segments(clips(), narration_s=60, seed=99)
        b = pick_segments(clips(), narration_s=60, seed=99)
        self.assertEqual(a, b)

    def test_different_seeds_can_differ(self):
        seen = {tuple(pick_segments(clips(), narration_s=60, seed=s))
                for s in range(12)}
        self.assertGreater(len(seen), 1)


class TestBounds(unittest.TestCase):
    def test_enough_segments_to_outlast_the_narration(self):
        segs = pick_segments(clips(), narration_s=60, seed=1)
        self.assertGreaterEqual(len(segs) * SEGMENT_S, 60)
        self.assertEqual(len(segs), segment_count(60))

    def test_no_segment_starts_past_the_end_of_its_clip(self):
        for seed in range(40):
            for _name, start, length in pick_segments(
                    clips(duration=45.0), narration_s=60, seed=seed):
                self.assertGreaterEqual(start, 0.0)
                self.assertLessEqual(start + length, 45.0 + 1e-6,
                                     "seed %d" % seed)

    def test_footage_shorter_than_the_narration_still_returns_a_plan(self):
        """It wraps rather than raising: a short clip is a quality problem,
        not a crash, and the caller can see it with crosses_cut."""
        segs = pick_segments([Clip("tiny", 20.0)], narration_s=60, seed=1)
        self.assertTrue(segs)
        self.assertEqual(len({n for n, _s, _l in segs}), 1)

    def test_no_clips_is_an_error_not_an_empty_render(self):
        with self.assertRaises(ValueError):
            pick_segments([], narration_s=60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
