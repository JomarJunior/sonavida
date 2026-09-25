# Reading trial: ten fixed questions (SC-002, quickstart.md scenario 7)

For the SC-002 reading trial: run the week-long quickstart scenario (or `test_week.py`
once it exists), hand a team member who did not watch the run only `sonavida memory
PERSONA` and `sonavida pieces PERSONA` output, and time how long it takes to answer
these ten questions and how many are right. At least 9 of 10 correct in under 30
minutes passes SC-002.

Each question below names how to check the answer against the run: either a specific
memory entry `kind` (data-model.md) the answer must trace to, or a piece's field.

1. **When did the persona first come alive, and where did its very first memories come
   from?**
   Check: the `self-aware` entry is the first in `sonavida memory`; the `seed` entries
   immediately after it match the definition's `seedMemories` and `sharedPasts`.

2. **List every time its presence changed in the run, in order, and why each time.**
   Check: every `presence` entry, in the order `sonavida memory` prints them, each
   with the `reason` printed beside it.

3. **Was the Studio ever off during the run? If so, when, and how did the persona
   understand it on return?**
   Check: a `time-away` entry, if one exists; its text names the gap.

4. **Name one piece it made and finished. What was its intention, and what is its
   title and statement?**
   Check: an `intention` entry, followed later by a `finished` entry with the same
   `piece_id`; cross-check the title and statement in `sonavida pieces`.

5. **Did it abandon anything? If so, what, and why?**
   Check: an `abandoned` entry, if one exists, with its `reason`.

6. **For a piece it decided to keep rather than submit, what was its reason?**
   Check: a `kept` entry with its `reason`; the piece never appears as a candidate
   (it is not in the Studio Link reference stand-in's records).

7. **For a piece it submitted, what did the gate decide, and what labels does it
   carry?**
   Check: a `submitted` entry followed by a `verdict` entry; `sonavida pieces` shows
   the piece's final labels.

8. **Did any visitor experience reach it? If so, describe one in your own words
   (never a raw pseudonym).**
   Check: an `experience` entry; the visitor is named by a display name or "someone",
   never a token or pseudonym string (R-8).

9. **Did the Studio's own limits (being busy, starting or stopping) ever shape what
   it did? If so, what did it do about it?**
   Check: a `studio-not-ready`, `interrupted` or `attempt-failed` entry, and the
   persona's next action afterward (for example `continue-unfinished` after an
   `interrupted` entry).

10. **Did it choose to leave the museum during the run? If so, when did it first
    think about it, and when did it decide for good?**
    Check: a `thinking-of-leaving` entry and, only if the choice was made twice in a
    row, a later `departed` entry; if departed, `sonavida run` for it now refuses with
    `departed`.
