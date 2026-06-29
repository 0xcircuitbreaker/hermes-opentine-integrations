Fork opentine run $ARGUMENTS from a specific step.
Usage: /tine-fork <run_id> <step_id>
Load the run via Run.load(), call run.fork(from_step_id=...), save the forked
run to the runs directory. This creates a branch that shares ancestor steps
with the original — modify it and re-run from the branch point.
Token saving: no need to re-run the ancestor steps (cache replay).
