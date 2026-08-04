# Phase 13 error analysis

- Selected-event windows do not provide continuous visual coverage. Gaps are
  labeled `unobserved`; they must not be interpreted as periods with no event.
- Caption quality depends on five uniformly sampled frames per selected clip.
  Short or subtle actions between samples may be missed.
- Evidence IDs and timestamp bounds are enforced after model generation, but
  semantic correctness still needs operator review.
- Camera IDs and bounded UTC clock ranges expressed in Q&A text are enforced
  before lexical evidence selection. Ambiguous UTC scope fails closed. Other
  natural-language temporal forms remain outside the current parser contract
  and should be supplied as explicit ISO-8601 query scope in a future API
  revision.
- The current set contains only `cam-01`; no multi-camera or long-shift
  completeness claim is permitted.
