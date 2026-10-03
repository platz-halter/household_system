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


@dataclass(frozen=True)
class CandidateTodo:
    todo_id: int
    points: int


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


@dataclass
class _Item:
    kind: ItemKind
    item_id: int
    points: int
    ramp_up_enabled: bool = False
    last_assignee_id: int | None = None
    recent_assignee_ids: frozenset[int] = field(default_factory=frozenset)


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
        )
        for t in tasks
    ] + [_Item(kind=ItemKind.todo, item_id=t.todo_id, points=t.points) for t in todos]
    # Heaviest first; ties broken by (kind, id) so a run is reproducible.
    items.sort(key=lambda i: (-i.points, i.kind.value, i.item_id))

    task_assignments: dict[int, int] = {}
    todo_assignments: dict[int, int] = {}
    unassigned_task_ids: list[int] = []
    unassigned_todo_ids: list[int] = []

    for item in items:
        candidates = [uid for uid in user_ids if count[uid] < max_new_items_per_user]
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
        if not a.ramp_up_enabled
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
