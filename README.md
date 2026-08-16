# faceless-video-pipeline

An unattended short-form video pipeline: it scouts source material, writes the script on a local LLM, renders with ffmpeg, watches its own output back, throws away what fails, and uploads the survivors as private drafts for a human to publish.

It runs on a schedule on one Windows desktop with a 12 GB consumer GPU. Nothing in it calls a paid inference API on the critical path. It has produced real videos that are live on a channel, and four different content types share the same pipeline.

## Architecture

```
                        SCHEDULED, UNATTENDED                        HUMAN
  ┌──────────────────────────────────────────────────────────────┐  ┌──────┐
  │                                                              │  │      │
  │  [1] SCOUT (nightly)                                         │  │      │
  │      public feeds  ->  rate-limit-aware fetch                 │  │      │
  │      Reddit RSS / Wikipedia API / generated formats          │  │      │
  │            |                                                 │  │      │
  │            |  safety gate #1 (raw source text)               │  │      │
  │            v                                                 │  │      │
  │      local LLM ranks 1-10 for hook potential                 │  │      │
  │            |                                                 │  │      │
  │            v                                                 │  │      │
  │      queue as `scout` rows in a SQLite ledger                │  │      │
  │            |                                                 │  │      │
  │  [2] PLAN (nightly)                                          │  │      │
  │      local LLM (gemma via Ollama) condenses -> script + hook  │  │      │
  │            |                                                 │  │      │
  │            |  safety gate #2 (the model's own rewrite)       │  │      │
  │            |  hook screen: meta-language, length, on-topic   │  │      │
  │            |  <- CHEAP KILL HERE, before any pixels          │  │      │
  │            v                                                 │  │      │
  │      plan.json  (voice, music, sfx, footage family, seed)    │  │      │
  │            |                                                 │  │      │
  │  [3] PREVIEW RENDER (nightly)                                │  │      │
  │      TTS + word timings -> burned captions -> ffmpeg          │  │      │
  │      first 10 seconds only, seeded off the video id          │  │      │
  │            |                                                 │  │      │
  │  [4] QC (morning): WATCH IT BACK                             │  │      │
  │      frames extracted from the actual render, reviewed       │  │      │
  │      twice: once for content, once for presentation          │  │      │
  │       fail -> logged with a reason, story dies               │  │      │
  │       pass -> best per theme promoted                        │  │      │
  │            |                                                 │  │      │
  │  [5] FULL RENDER from the LOCKED plan                        │  │      │
  │      same seed, same footage, same voice as the preview      │  │      │
  │            |                                                 │  │      │
  │  [6] UPLOAD                                                  │  │      │
  │      assert authorized channel identity  <- immediately      │  │      │
  │      before the insert call                                  │  │      │
  │      privacyStatus = private, no code path sets otherwise    │  │      │
  │            |                                                 │  │      │
  │            +-------------- private draft ------------------->│->│PUBLISH│
  │                                                              │  │      │
  │  [7] RECONCILE (daily)  read platform state back  <----------│--+      │
  │  [8] HEAL (daily)  11 probes over the whole loop             │  └──────┘
  └──────────────────────────────────────────────────────────────┘
```

## Stage by stage

**1. Scout.** Pulls candidates from public feeds. Reddit's JSON endpoints reject scripts, so it reads the RSS feeds instead and obeys the rate-limit headers rather than guessing an interval: it parks the next request until `x-ratelimit-reset` says the window is clear. Measured anonymous budget is roughly one request per 25 seconds, so a nightly sweep of several feeds takes a few minutes and never gets 429'd out of the run. The Wikipedia adapter does the same with `Retry-After`. Every adapter returns an identical story dict, so nothing downstream knows or cares where a story came from.

**2. Rank and plan.** A local model (gemma through Ollama) scores each candidate 1-10 for short-form potential. The rubric is per-source, because a rubric asking for dialogue and first-person voice scores every encyclopedia article a 3 and silently starves that whole source. The winning stories are condensed into a narration script by a second local call, again with a per-source prompt: the Reddit prompt keeps dialogue and sensory detail, the Wikipedia prompt forbids invented dialogue, invented motives, and named suspects, because those are real cases about real people.

Everything creative is decided once, here, and written to a plan file: script, hook, voice, music bed, sound effect, footage family, and the RNG seed. The preview and the full render both replay that plan. What passed QC is what ships, down to the footage.

**3. Preview render.** Text-to-speech with word-boundary timings drives generated ASS subtitles, so captions are word-synced without a separate alignment pass. ffmpeg concatenates background cuts, applies a grade, overlays a hook card for the first sentence only, burns the captions, and mixes a music bed and one hit under the voice. Only the first 10 seconds are rendered. A 10-second preview costs a fraction of a full render, and the first 10 seconds are what decides whether a short-form video works.

**4. QC watches the output back.** This is the part that matters. The pipeline does not treat "ffmpeg exited 0" as success. It extracts frames from the render it just produced and reviews them twice against two separate checklists, one for content and one for presentation. Failures are logged with a written reason and the story is killed. The kill rate is itself a monitored metric, because a rising kill rate is the only automatic signal that production quality is drifting.

**5. Full render.** Only for previews that passed, and only from the locked plan. The duration window is re-enforced on the full script, so a preview that passed cannot produce an out-of-window full render.

**6. Upload.** The renders go up as private drafts with title, description, and tags filled in from a generated post pack. Wikipedia-sourced videos carry a CC BY-SA attribution line that no code path is allowed to strip. `privacyStatus` is hard-coded to private and there is no branch that changes it. Publishing is always a human's click.

**7. Reconcile.** A daily job reads state back from the platform for every uploaded video, including private ones, and updates the local ledger. This exists because a human publishes outside the pipeline, so the pipeline's own store drifts out of date the moment someone clicks Publish. When the two disagreed, the platform was right and the local store was badly wrong. The rule that came out of it: for anything a human can change outside your system, trust the platform over your own store.

**8. Heal.** A daily self-check runs eleven probes over the whole loop and reports what needs a human. It asks a different question from "did anything crash", because none of the expensive defects here ever crashed. It asks whether the loop can still reach a human and whether what it is about to spend is still worth spending.

## What makes it survive unattended

Every item below is a real defect that shipped, and the specific change that closed it.

**The QC step watches the render, not the exit code.** ffmpeg returning 0 means a file exists. It says nothing about whether the file is watchable. Frames come out of the actual output and get reviewed. That is the only check in the system that sees what a viewer would see.

**Screen the plan before you spend the render.** Hook screening originally ran after rendering. One bad hook cost a 76 MB render before being rejected for a garden-path opening. The screen moved onto the plan text, before TTS and before ffmpeg: 4 of 19 candidates in the next batch were killed on the hook alone at zero render cost. Cheap checks belong upstream of expensive work, and you find out where the expensive work is by watching what you throw away.

**Content safety runs at three points, not one.** The blocklist originally ran only on raw source text. The local model rewrites the story, and a rewrite can introduce phrasing the source never used, so the only text that reliably matches what a viewer hears is the condensed script, which nothing was checking. A story reached a full render with narration the source text never contained. The gate now runs on raw source, on the model's rewrite, and on generated scripts. A separate probe greps the tree and fails if the number of call sites drops, because the defect was a missing call site, not a weak pattern. The gate is deliberately regex, not a model call: a blocklist that depends on the local model being up fails open on exactly the night the model is down.

**A bug that looks like a data problem for four days.** Background footage was drawn as a random clip per 8-second segment. A "family" of footage is a filename prefix, so one family was 21 unrelated 90-second clips, and a 60-second video teleported between locations 9 times. QC caught the output every night (80%, 64%, 100%, 70% kill rates on four consecutive days) but the diagnosis was wrong the whole time, because the one footage family whose clips all look alike never showed the symptom and appeared to be the only healthy asset. It read as an asset-tagging problem. The fix is one source clip per video with cuts at random offsets inside it, so the shot changes without the world changing. It is locked by a regression test asserting all chunks come from one clip, that cuts still happen, that offsets stay in bounds, and that seeding on the video id still makes the preview and the full render identical.

**Assert identity immediately before the irreversible call.** The first OAuth consent authorized the wrong channel, and a video was one call away from landing there. The upload path now calls a channel assertion immediately before the insert, and aborts with both the authorized identity and the expected one printed. A probe verifies not just that the assertion exists but that its line number is above the insert, because a guard after the irreversible call is decoration. That probe exists because a written record claimed this guard was "now permanent" while the code did not contain it at all. Verify guards against the code, never against the changelog.

**The human gate is structural, not procedural.** Uploading is automatic, publishing never is. That is not enforced by a policy note; it is enforced by there being no code path that sets a video public.

**Scheduled tasks on Windows have a battery trap.** `New-ScheduledTaskSettingsSet` defaults both battery flags to true, and the scheduler then kills the task mid-run with `0xC000013A` on a desktop that has no battery. Proved by A/B with byte-identical actions: flags explicitly false gave 40/40 clean exits, flags left at the default gave 14/40 killed. Related hardening in the same installer: `StartWhenAvailable` plus a restart count, because a task that fires at wake hits DNS before the network stack is up, and that silently killed every run for a week; and the pipeline stages are chained with `&` rather than `&&`, because a scout failure must not skip the render step, which is a bug this pipeline shipped and lost a week of output to.

**A stopped pipeline looks exactly like a quiet week.** Every job writes a heartbeat at the end of a run, which proves the code finished rather than proving the scheduler launched something. Dashboards cannot report this, because dashboards are written by the thing that stopped.

## What this repo is

An architecture write-up and extracted components of a private system that actually runs. It is not a turnkey clone-and-run.

Specifically:

- The full production tree, credentials, source configuration, and content ledger stay private. What is here is the architecture, the reasoning, and the components that are useful on their own.
- Anything account-specific has been removed. There are no keys, no client secrets, no channel identifiers, and no scraped content in this repo.
- The interesting part is not the ffmpeg invocation. It is the shape of the loop: cheap checks upstream of expensive work, verification against the artifact instead of the exit code, an irreversible action guarded immediately before it fires, and a human gate that is enforced by the absence of a code path rather than by a rule someone is supposed to remember.

If you are hiring for unattended automation, that list is the argument. I am happy to walk through any of these defects and their fixes in detail.

### Code in this repo

`segments.py` is the background-footage selection logic, extracted whole and
with the media dependencies removed, plus `test_segments.py` covering it.

It is here because it is the clearest example of the thing above: the bug
was never in the encoding, it was in the arithmetic, so the arithmetic is
separated from ffmpeg and tested in milliseconds without touching a video
file. It also took two fixes, and the first was declared done while the bug
was still shipping, because the test suite pinned the half that had been
fixed and never asserted the half that had not. The docstring is honest
about that, and about what the fix cost.

## Stack

Python (standard library for all feed I/O, no scraping framework), Ollama running gemma locally, edge TTS with word-boundary timings, ffmpeg and ffprobe for rendering and probing, ASS subtitles generated per word, yt-dlp for background footage ingest, SQLite as the outcome ledger, Windows Task Scheduler with PowerShell installers.
