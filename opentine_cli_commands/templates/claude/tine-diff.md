Diff two opentine runs: $ARGUMENTS
Usage: /tine-diff <run_a> <run_b>
Load both runs, call run_a.diff(run_b), and show:
1. Changed steps (same DAG position, different content)
2. Steps only in A
3. Steps only in B
4. Common ancestor if any
This identifies exactly where two agent runs diverged.
