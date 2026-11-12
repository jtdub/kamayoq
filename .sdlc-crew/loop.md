# Crew loop: one pass

Start the loop with:

```
/loop Do one pass of .sdlc-crew/loop.md
```

Each pass takes one issue to a pull request, or acts on one open pull request. The loop
is not fully unattended. The crew asks you to approve each plan.

## Labels

| Label | Meaning |
| --- | --- |
| `status:ready` | All blockers are closed. `ready_queue.py` sets it. |
| `needs-human` | A decision for a person. The loop never takes it. |
| `human-merge` | The loop opens the pull request. A person reviews and merges it. |

## Step 1: Refresh the queue

```bash
git switch develop && git pull --ff-only
python3 .sdlc-crew/ready_queue.py --apply
```

## Step 2: Act on open crew pull requests first

List the open pull requests with a head branch that starts with `sdlc/`:

```bash
gh pr list --state open --json number,headRefName,isDraft,autoMergeRequest,statusCheckRollup,reviewDecision \
  --jq '[.[] | select(.headRefName | startswith("sdlc/"))]'
```

1. If a pull request has a failed check or an unresolved review comment, run
   `/sdlc-crew --feedback <PR>`. End the pass.
2. If a pull request without `human-merge` on its issue has auto-merge on and its checks
   are still running, end the pass. Wake up again in 20 minutes.
3. If three or more `human-merge` pull requests wait for review, stop the loop. Tell
   the person which pull requests wait.

## Step 3: Pick the next issue

Take the open issues with `status:ready`. Remove each issue that has `needs-human` or
`type:epic`, and each issue that an open pull request already closes. Sort the rest:

1. The lowest open milestone first.
2. Then `priority:p0`, then `p1`, then `p2`.
3. Then the lowest issue number.

If no issue is left and no crew pull request is open, stop the loop and report. If no
issue is left but a crew pull request is open, end the pass.

## Step 4: Build it

Run `/sdlc-crew #<N>`. The crew plans, asks for plan approval, builds, runs QA, and
opens the pull request.

If the crew stops on a limit (`max_qa_rounds`, `max_ci_rounds`) or a blocking plan
finding, add `needs-human` to the issue. Comment the reason on the issue. End the pass.

## Step 5: Link the issue

```bash
gh pr view <PR> --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'
```

If `<N>` is not in the list, add the line `Closes #<N>` to the pull request body.

## Step 6: The merge gate

1. If the issue has `human-merge`, comment on the pull request: "Needs a human review
   and merge (security core)." End the pass.
2. Find out whether `develop` has required status checks:

   ```bash
   gh api repos/jtdub/kamayoq/branches/develop/protection/required_status_checks --jq '.contexts'
   ```

3. If the call fails or the list is empty, do not merge. Comment on the pull request:
   "Auto-merge is off until develop has required checks." End the pass.
4. Otherwise run `gh pr merge <PR> --squash --auto`. GitHub merges the pull request
   when the checks pass. The merge closes the issue.

## Never

- Push to `develop` or `main`.
- Merge without `--auto`, or merge a `human-merge` pull request.
- Close an issue directly.
- Change branch protection, repository settings, or labels other than `status:ready`
  and `needs-human`.
- Delete a branch or a worktree that a person made.
