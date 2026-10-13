"""The auto-balancing assignment algorithm, as pure functions with no DB
session — crud.run_balancing gathers everything it needs from the
database, calls `balance()` then `rebalance()`, and persists whatever
they return. Keeping them pure makes the fairness logic itself
unit-testable without a database or an event loop (see
tests/test_balancing.py).

`balance()` hands out anything not yet assigned this period. `rebalance()`
runs after it and pulls an unfinished task away from whoever's most ahead
when another eligible person is meaningfully behind — the mid-week
fairness check for "someone pulled ahead early in the week."

Fairness rule: each item (a weekly/monthly task, or an unclaimed board
todo) goes to whichever eligible user is currently carrying the least
total load — points already earned this week, plus the expected points
of everything they're already carrying into this run. Processing the
heaviest items first means the biggest point values land while the load
picture is least skewed, which is what keeps one person from quietly
absorbing a string of small items before a big one comes up. Ties always
break on the lower user id, so a run is exactly reproducible given the
same inputs — no shuffling.

`CandidateTask`/`CandidateTodo.pinned_user_ids` ("always assign to" — see
Task.pinned_users) is the one exception to all of the above: a pinned
item skips the HOUSEHOLD-WIDE fairness pick entirely, in `balance()`,
and is never a candidate for `rebalance()`'s pull either — it's a
standing household agreement, not a household-wide fairness decision,
though it still counts toward the picked member's own load for
everything else being distributed. Pinning to more than one person
doesn't waive fairness, it just shrinks its scope: whichever ELIGIBLE
member of the pinned group is currently least loaded gets it — the
exact same tie-break rule (`min(load, uid)`) the household-wide pick
uses, just run over the smaller candidate set. A single-member group
degenerates to the original "always this one person" behavior for
free. `correct_pins()` is the third, separate operation this module
offers: moving an EXISTING assignment held by someone outside the
pinned group back to whichever eligible member of that group is
fairest right now (e.g. the pin was just set, or changed) — not a
fairness computation either, just the same "don't disrupt real
work"/"don't undo an accepted takeover" gates `rebalance()` already
uses, plus the same within-group fair pick `balance()` uses.
"""

from dataclasses import dataclass, field
from enum import Enum


class ItemKind(str, Enum):
    task = "task"
    todo = "todo"


@dataclass(frozen=True)
class EligibleUser:
    user_id: int
    points_this_week: int
    # Expected points / count of whatever this user is already carrying
    # into this run (open assignments from a previous run this period,
    # plus any open todos already assigned to them) — seeds their load so
    # a re-run doesn't pile more onto someone already loaded up.
    already_assigned_points: int = 0
    already_assigned_count: int = 0


@dataclass(frozen=True)
class CandidateTask:
    task_id: int
    expected_points: int
    ramp_up_enabled: bool
    # The single most recent assignee, for ramp-up stickiness.
    last_assignee_id: int | None = None
    # Up to the last 2 assignees, for non-ramp-up rotation (skip them if
    # another eligible candidate exists).
    recent_assignee_ids: frozenset[int] = field(default_factory=frozenset)
    # "Always assign to" group (Task.pinned_users) — bypasses the
    # household-wide fairness pick (and the per-run cap) entirely in
    # balance() below, straight to whichever eligible member of this
    # set is currently least loaded, or left unassigned if nobody in
    # it is eligible right now. DOES still reach the ramp-up-stickiness
    # branch (unlike pre-group pins, where it was moot with only one
    # possible assignee) — see balance()'s own comment. Empty
    # frozenset = not pinned.
    pinned_user_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class CandidateTodo:
    todo_id: int
    points: int
    # Set for a todo spawned by a "different person" chain task — the
    # user who completed the parent, who must never receive this todo.
    # Hard-filtered out of the candidate pool for this item specifically
    # (not removed from `users` entirely — they can still receive OTHER
    # items in the same run).
    excluded_user_id: int | None = None
    # Same meaning as CandidateTask.pinned_user_ids — a todo has no pin
    # of its own, only the Task it was posted from (or an event group
    # root) might; the caller resolves that and passes it through here
    # (crud.run_balancing / crud.trigger_event_group).
    pinned_user_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class BalanceResult:
    task_assignments: dict[int, int]  # task_id -> user_id
    todo_assignments: dict[int, int]  # todo_id -> user_id
    unassigned_task_ids: list[int]
    unassigned_todo_ids: list[int]


@dataclass(frozen=True)
class PullableAssignment:
    """An existing TaskAssignment rebalance() is allowed to *consider*
    moving — the gating rules below still have to pass. `remaining_points`
    is what's left of the task's whole-period value (full value minus
    whatever's already been completed by anyone), not its total value, so
    a task someone's partway through is correctly worth less to move than
    one nobody's touched."""

    assignment_id: int
    holder_id: int
    remaining_points: int
    ramp_up_enabled: bool = False
    # Never pull a task with ANY logged progress this period, by anyone —
    # someone's partway through it, and yanking it away mid-stream is a
    # worse outcome than letting a bit of unfairness ride one more day.
    has_progress: bool = False
    # Each assignment can only be pulled once per period — otherwise nothing
    # stops it bouncing between two people as small, noisy point swings
    # flip who looks "ahead" from one day's run to the next.
    already_reassigned: bool = False
    # Never pull something assigned today — give the original holder at
    # least a day before it's up for grabs again.
    assigned_today: bool = False
    # True for a task with an "always assign to" group — rebalance()
    # below skips these unconditionally, regardless of group size. A
    # pin isn't a household-wide fairness decision, so none of this
    # dataclass's other gating fields apply to it (see correct_pins()
    # instead, which is what moves a pinned assignment held by someone
    # outside the group back to whichever eligible member is fairest).
    pinned: bool = False


@dataclass(frozen=True)
class PinnedAssignment:
    """An existing TaskAssignment whose task has an "always assign to"
    group (Task.pinned_users) that does NOT include whoever currently
    holds it — a candidate for correct_pins() to move back to the
    group. Built straight from DB state; correct_pins() itself still
    runs the same within-group fair pick balance() does, seeded from
    `users`' own load."""

    assignment_id: int
    holder_id: int
    pinned_user_ids: frozenset[int]
    remaining_points: int
    # Same "don't disrupt real work" reasoning as PullableAssignment's
    # own has_progress — never move a task someone's partway through,
    # pinned or not.
    has_progress: bool = False
    # Sourced from the SAME TaskAssignment.reassigned_at column
    # PullableAssignment's own already_reassigned reads — it's stamped
    # by rebalance()'s own pull AND by crud.accept_takeover_request's
    # consent-based move. A pin must never silently undo a holder's own
    # accepted takeover; there's no way to tell the two apart from this
    # column alone, so both are treated the same: once moved this
    # period, a pin correction leaves it alone too.
    already_reassigned: bool = False


def correct_pins(
    *, assignments: list[PinnedAssignment], users: list[EligibleUser]
) -> list[tuple[int, int, int]]:
    """Moves a mis-held pinned assignment back to the pinned group —
    e.g. the pin was just set, or changed, after this period's sweep
    already ran — to whichever eligible member of that group is
    currently least loaded (same tie-break as balance()'s own pick).
    Returns (assignment_id, from_user_id, to_user_id) for each move,
    same shape as rebalance()'s own moves, so the caller can apply both
    through identical code (including cancelling any pending takeover
    request on a moved assignment).

    `users` seeds a LOCAL load tally (separate from the caller's own
    running one) so that correcting several mis-held assignments in the
    same call doesn't pile all of them onto whoever looked least loaded
    before any of them moved — each move updates this function's own
    tally before the next assignment is considered.

    Deliberately does NOT gate on "assigned today," unlike
    PullableAssignment's rebalance() sibling — that gate exists to give
    a FAIRNESS pick at least a day before it's up for grabs again; a pin
    is not a fairness pick, and the whole point of setting one is an
    immediate, deterministic correction, not a day's grace period.
    `has_progress`/`already_reassigned` are what actually protect real
    work and an accepted takeover, and those still apply."""
    load = {u.user_id: u.points_this_week + u.already_assigned_points for u in users}
    moves: list[tuple[int, int, int]] = []
    for a in assignments:
        if (
            a.has_progress
            or a.already_reassigned
            or a.remaining_points <= 0
            or a.holder_id in a.pinned_user_ids
        ):
            continue
        eligible_pinned = [uid for uid in a.pinned_user_ids if uid in load]
        if not eligible_pinned:
            continue
        target = min(eligible_pinned, key=lambda uid: (load[uid], uid))
        moves.append((a.assignment_id, a.holder_id, target))
        if a.holder_id in load:
            load[a.holder_id] -= a.remaining_points
        load[target] += a.remaining_points
    return moves


@dataclass
class _Item:
    kind: ItemKind
    item_id: int
    points: int
    ramp_up_enabled: bool = False
    last_assignee_id: int | None = None
    recent_assignee_ids: frozenset[int] = field(default_factory=frozenset)
    excluded_user_id: int | None = None
    pinned_user_ids: frozenset[int] = frozenset()


def balance(
    *,
    users: list[EligibleUser],
    tasks: list[CandidateTask],
    todos: list[CandidateTodo],
    max_new_items_per_user: int,
) -> BalanceResult:
    if not users:
        return BalanceResult(
            task_assignments={},
            todo_assignments={},
            unassigned_task_ids=[t.task_id for t in tasks],
            unassigned_todo_ids=[t.todo_id for t in todos],
        )

    load = {u.user_id: u.points_this_week + u.already_assigned_points for u in users}
    count = {u.user_id: u.already_assigned_count for u in users}
    user_ids = [u.user_id for u in users]

    items = [
        _Item(
            kind=ItemKind.task,
            item_id=t.task_id,
            points=t.expected_points,
            ramp_up_enabled=t.ramp_up_enabled,
            last_assignee_id=t.last_assignee_id,
            recent_assignee_ids=t.recent_assignee_ids,
            pinned_user_ids=t.pinned_user_ids,
        )
        for t in tasks
    ] + [
        _Item(
            kind=ItemKind.todo,
            item_id=t.todo_id,
            points=t.points,
            excluded_user_id=t.excluded_user_id,
            pinned_user_ids=t.pinned_user_ids,
        )
        for t in todos
    ]
    # Heaviest first; ties broken by (kind, id) so a run is reproducible.
    items.sort(key=lambda i: (-i.points, i.kind.value, i.item_id))

    task_assignments: dict[int, int] = {}
    todo_assignments: dict[int, int] = {}
    unassigned_task_ids: list[int] = []
    unassigned_todo_ids: list[int] = []

    for item in items:
        if item.pinned_user_ids:
            # A standing assignment, not a household-wide fairness
            # decision — goes straight to whichever eligible member of
            # the pinned group is currently least loaded (bypassing
            # both the general fairness pick AND the per-run cap,
            # since this was never a candidate for redistribution
            # outside the group in the first place), or is left
            # unassigned if nobody in the group is currently eligible
            # (on break, or no longer in this household) — never
            # handed to anyone OUTSIDE the group just because every
            # member of it is unavailable right now; that would defeat
            # the point.
            pinned_candidates = [
                uid
                for uid in item.pinned_user_ids
                if uid in load and uid != item.excluded_user_id
            ]
            if pinned_candidates:
                # Ramp-up stickiness applies WITHIN the group too — a
                # multi-person pin still shouldn't rotate a solo streak
                # away from whoever's actually been completing it, the
                # same reasoning the unpinned branch below has.
                if (
                    item.ramp_up_enabled
                    and item.last_assignee_id is not None
                    and item.last_assignee_id in pinned_candidates
                ):
                    picked = item.last_assignee_id
                else:
                    picked = min(pinned_candidates, key=lambda uid: (load[uid], uid))
                if item.kind == ItemKind.task:
                    task_assignments[item.item_id] = picked
                else:
                    todo_assignments[item.item_id] = picked
                load[picked] += item.points
                count[picked] += 1
            else:
                (
                    unassigned_task_ids
                    if item.kind == ItemKind.task
                    else unassigned_todo_ids
                ).append(item.item_id)
            continue

        candidates = [
            uid
            for uid in user_ids
            if count[uid] < max_new_items_per_user and uid != item.excluded_user_id
        ]
        if not candidates:
            (
                unassigned_task_ids
                if item.kind == ItemKind.task
                else unassigned_todo_ids
            ).append(item.item_id)
            continue

        picked: int
        if (
            item.ramp_up_enabled
            and item.last_assignee_id is not None
            and item.last_assignee_id in candidates
        ):
            # Sticky: rotating a ramp-up task away from its one completer
            # would permanently kill the bonus for everyone (see
            # crud.complete_task) — keep it with them as long as they're
            # still eligible and under the cap.
            picked = item.last_assignee_id
        else:
            avoid = item.recent_assignee_ids
            pool = [uid for uid in candidates if uid not in avoid] or candidates
            picked = min(pool, key=lambda uid: (load[uid], uid))

        if item.kind == ItemKind.task:
            task_assignments[item.item_id] = picked
        else:
            todo_assignments[item.item_id] = picked
        load[picked] += item.points
        count[picked] += 1

    return BalanceResult(
        task_assignments=task_assignments,
        todo_assignments=todo_assignments,
        unassigned_task_ids=unassigned_task_ids,
        unassigned_todo_ids=unassigned_todo_ids,
    )


def rebalance(
    *,
    users: list[EligibleUser],
    assignments: list[PullableAssignment],
    weekly_points_goal: int | None,
    max_new_items_per_user: int,
) -> list[tuple[int, int, int]]:
    """Mid-week fairness pass: pulls an unfinished, already-assigned task
    away from whoever's currently most ahead and hands it to whoever's
    least loaded, when doing so is actually worth the disruption. Called
    AFTER balance() has already handed out anything freshly unassigned —
    `users` here should reflect load post-sweep, so a brand-new item never
    gets passed over in favor of yanking an existing one.

    A move only happens if `load[holder] - load[recipient] > item's own
    value` — not just any positive gap. That guarantees the move actually
    narrows the gap without just flipping who's ahead (transferring
    `remaining_points` can never push the recipient past the holder's old
    total when the gap itself is bigger than the item). No separate
    tunable threshold to get wrong or need re-tuning per household.

    Returns (assignment_id, from_user_id, to_user_id) for each move. Each
    assignment moves at most once per call; `max_new_items_per_user`
    counts both what the sweep already gave someone and what this pass
    gives them, so a recipient can't end up over the same per-run cap.
    """
    if not users or not assignments:
        return []

    load = {u.user_id: u.points_this_week + u.already_assigned_points for u in users}
    count = {u.user_id: u.already_assigned_count for u in users}
    user_ids = [u.user_id for u in users]

    eligible = [
        a
        for a in assignments
        if not a.pinned
        and not a.ramp_up_enabled
        and not a.has_progress
        and not a.already_reassigned
        and not a.assigned_today
        and a.remaining_points > 0
        and a.holder_id in load
    ]
    eligible.sort(key=lambda a: (-a.remaining_points, a.assignment_id))

    moves: list[tuple[int, int, int]] = []
    for a in eligible:
        holder = a.holder_id
        candidates = [
            uid
            for uid in user_ids
            if uid != holder and count[uid] < max_new_items_per_user
        ]
        if not candidates:
            continue
        recipient = min(candidates, key=lambda uid: (load[uid], uid))

        gap = load[holder] - load[recipient]
        if gap <= a.remaining_points:
            continue  # not worth the disruption — doesn't meaningfully narrow the gap

        if weekly_points_goal is not None:
            holder_was_on_track = load[holder] >= weekly_points_goal
            holder_still_on_track = (
                load[holder] - a.remaining_points
            ) >= weekly_points_goal
            if holder_was_on_track and not holder_still_on_track:
                # Don't manufacture a new goal miss — if they were already
                # going to fall short regardless, fairness wins instead.
                continue

        moves.append((a.assignment_id, holder, recipient))
        load[holder] -= a.remaining_points
        load[recipient] += a.remaining_points
        count[recipient] += 1

    return moves
