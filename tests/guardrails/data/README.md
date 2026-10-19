# Matching-view snapshots (CP-002)

- `matching_view_new_matches.json` (N-01): every corpus item whose Stage 0/1 result differs from v1 matching, with
  a written justification and a decision (`accepted-class`, `accepted-threshold`, `owner-review`).
- `matching_view_pasted_report.json` (N-06): verdict, patterns, rules and session risk for each pasted-text sample,
  and how many reach the require-human threshold (cumulative risk 4.0), alone and in one session.

The corpus is hand-written (see `tests/guardrails/matching_view_corpus.py`), not real traffic.
Tests compare the live result with these files. To change them: run the diff printed by the failing test, review
every new match, write its justification, and commit the file with the code change. Never overwrite blindly.
