"""Unit tests for the pure balancing algorithm (household_service.balancing).
No DB/event loop needed — see that module's docstring for why it's kept
pure. Run with: uv run --package household-backend pytest household/backend/tests/test_balancing.py
"""

from household_service.balancing import (
    CandidateTask,
    CandidateTodo,
    EligibleUser,
    PinnedAssignment,
    PullableAssignment,
    balance,
    correct_pins,
    rebalance,
)


def test_cap_is_never_exceeded():
    users = [EligibleUser(user_id=i, points_this_week=0) for i in range(1, 3)]
    tasks = [
        CandidateTask(task_id=i, expected_points=5, ramp_up_enabled=False)
        for i in range(1, 11)
    ]

    result = balance(users=users, tasks=tasks, todos=[], max_new_items_per_user=3)

    counts: dict[int, int] = {}
    for uid in result.task_assignments.values():
        counts[uid] = counts.get(uid, 0) + 1
    assert all(c <= 3 for c in counts.values())
    # 2 users * cap 3 = 6 placed, 4 left over.
    assert len(result.task_assignments) == 6
    assert len(result.unassigned_task_ids) == 4


def test_no_eligible_users_leaves_everything_unassigned():
    tasks = [CandidateTask(task_id=1, expected_points=5, ramp_up_enabled=False)]
    todos = [CandidateTodo(todo_id=1, points=3)]

    result = balance(users=[], tasks=tasks, todos=todos, max_new_items_per_user=5)

    assert result.task_assignments == {}
    assert result.todo_assignments == {}
    assert result.unassigned_task_ids == [1]
    assert result.unassigned_todo_ids == [1]


def test_rotation_avoids_recent_assignee_when_alternative_exists():
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        recent_assignee_ids=frozenset({1}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 2


def test_rotation_falls_back_to_recent_assignee_if_no_alternative():
    users = [EligibleUser(user_id=1, points_this_week=0)]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        recent_assignee_ids=frozenset({1}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 1


def test_ramp_up_tasks_stay_sticky_with_their_last_assignee():
    # User 1 is far less loaded than user 2, so ordinary load-based
    # picking would hand this to user 1 — but it's ramp-up and user 2 was
    # the last (and only) completer, so the bonus-preserving behavior
    # means it should stay with user 2.
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=100),
    ]
    task = CandidateTask(
        task_id=1, expected_points=5, ramp_up_enabled=True, last_assignee_id=2
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 2


def test_ramp_up_task_falls_back_to_load_based_pick_when_last_assignee_ineligible():
    # Last assignee (user 2) is on break this run — not in `users` at all.
    users = [EligibleUser(user_id=1, points_this_week=0)]
    task = CandidateTask(
        task_id=1, expected_points=5, ramp_up_enabled=True, last_assignee_id=2
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 1


def test_biggest_deficit_user_gets_the_heaviest_item():
    # User 1 has earned far more this week already — the single big item
    # should go to user 2, who's furthest behind.
    users = [
        EligibleUser(user_id=1, points_this_week=50),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    tasks = [
        CandidateTask(task_id=1, expected_points=20, ramp_up_enabled=False),
        CandidateTask(task_id=2, expected_points=5, ramp_up_enabled=False),
    ]

    result = balance(users=users, tasks=tasks, todos=[], max_new_items_per_user=5)

    assert (
        result.task_assignments[1] == 2
    )  # the 20-point task goes to the less-loaded user


def test_rerun_with_existing_load_creates_no_duplicate_pileup():
    # Simulates calling balance() again mid-period: user 1 already has
    # (carried-in) load recorded via already_assigned_points/count, which
    # should steer new items toward user 2 instead of piling onto 1.
    users = [
        EligibleUser(
            user_id=1,
            points_this_week=0,
            already_assigned_points=15,
            already_assigned_count=1,
        ),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    tasks = [CandidateTask(task_id=1, expected_points=5, ramp_up_enabled=False)]

    result = balance(users=users, tasks=tasks, todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 2


def test_deterministic_tie_break_by_id():
    users = [
        EligibleUser(user_id=5, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    task = CandidateTask(task_id=1, expected_points=5, ramp_up_enabled=False)

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 2  # lower user_id wins an exact tie

    # And it's reproducible — same inputs, same answer, every time.
    result2 = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)
    assert result.task_assignments == result2.task_assignments


def test_todos_and_tasks_are_balanced_together():
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    tasks = [CandidateTask(task_id=1, expected_points=10, ramp_up_enabled=False)]
    todos = [CandidateTodo(todo_id=1, points=10)]

    result = balance(users=users, tasks=tasks, todos=todos, max_new_items_per_user=5)

    # Same point value, processed heaviest-first with a tie-break on
    # (kind, id) — task sorts before todo — so the task goes to user 1
    # first, then the todo (now the heavier remaining load) goes to user 2.
    assert result.task_assignments[1] == 1
    assert result.todo_assignments[1] == 2


# ---- rebalance() — the mid-week pull pass -------------------------------


def test_pull_moves_from_overloaded_to_underloaded_when_gap_is_big_enough():
    users = [
        EligibleUser(user_id=1, points_this_week=50),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10)

    moves = rebalance(
        users=users, assignments=[a], weekly_points_goal=None, max_new_items_per_user=5
    )

    assert moves == [(1, 1, 2)]


def test_no_pull_when_gap_does_not_exceed_the_items_own_value():
    # Gap is exactly 10 (50 vs 40), the same as the item's own value —
    # must be STRICTLY greater, not equal, to be worth the disruption.
    users = [
        EligibleUser(user_id=1, points_this_week=50),
        EligibleUser(user_id=2, points_this_week=40),
    ]
    a = PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10)

    moves = rebalance(
        users=users, assignments=[a], weekly_points_goal=None, max_new_items_per_user=5
    )

    assert moves == []


def test_ramp_up_assignment_is_never_pulled():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(
        assignment_id=1, holder_id=1, remaining_points=10, ramp_up_enabled=True
    )

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=None,
            max_new_items_per_user=5,
        )
        == []
    )


def test_assignment_with_any_progress_is_never_pulled():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(
        assignment_id=1, holder_id=1, remaining_points=10, has_progress=True
    )

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=None,
            max_new_items_per_user=5,
        )
        == []
    )


def test_already_reassigned_assignment_is_never_pulled_again():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(
        assignment_id=1, holder_id=1, remaining_points=10, already_reassigned=True
    )

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=None,
            max_new_items_per_user=5,
        )
        == []
    )


def test_assignment_made_today_is_never_pulled():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(
        assignment_id=1, holder_id=1, remaining_points=10, assigned_today=True
    )

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=None,
            max_new_items_per_user=5,
        )
        == []
    )


def test_recipient_cap_counts_pulled_items_too():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        # user 2 already has 2 items from the sweep phase this run —
        # cap of 2 means they can't receive a pulled item either.
        EligibleUser(user_id=2, points_this_week=0, already_assigned_count=2),
    ]
    a = PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10)

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=None,
            max_new_items_per_user=2,
        )
        == []
    )


def test_donor_guard_blocks_pull_that_would_newly_cause_a_goal_miss():
    # Holder is at exactly goal (100) before the pull; losing 10 would
    # drop them to 90, newly missing it — blocked.
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10)

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=100,
            max_new_items_per_user=5,
        )
        == []
    )


def test_donor_guard_allows_pull_when_holder_was_already_short_of_goal():
    # Holder is already below goal (100) even before losing anything —
    # fairness wins since the pull can't make their goal status worse.
    users = [
        EligibleUser(user_id=1, points_this_week=50),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    a = PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10)

    assert rebalance(
        users=users, assignments=[a], weekly_points_goal=100, max_new_items_per_user=5
    ) == [(1, 1, 2)]


def test_heaviest_pullable_assignment_moves_first_and_updates_running_load():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
        EligibleUser(user_id=3, points_this_week=5),
    ]
    assignments = [
        PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10),
        PullableAssignment(assignment_id=2, holder_id=1, remaining_points=50),
    ]

    moves = rebalance(
        users=users,
        assignments=assignments,
        weekly_points_goal=None,
        max_new_items_per_user=5,
    )

    # The 50-point item is processed first and goes to user 2 (lowest
    # load, 0). That brings user 2 up to 50 — still less than user 3's 5?
    # No: 50 > 5, so by the time the 10-point item is considered, user 3
    # (load 5) is now the least-loaded eligible recipient, not user 2.
    assert moves[0] == (2, 1, 2)
    assert moves[1] == (1, 1, 3)


def test_no_eligible_recipients_leaves_assignments_unmoved():
    users = [EligibleUser(user_id=1, points_this_week=0)]
    a = PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10)

    assert (
        rebalance(
            users=users,
            assignments=[a],
            weekly_points_goal=None,
            max_new_items_per_user=5,
        )
        == []
    )


def test_deterministic_across_repeated_calls():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    assignments = [
        PullableAssignment(assignment_id=1, holder_id=1, remaining_points=10),
        PullableAssignment(assignment_id=2, holder_id=1, remaining_points=10),
    ]

    moves1 = rebalance(
        users=users,
        assignments=assignments,
        weekly_points_goal=None,
        max_new_items_per_user=5,
    )
    moves2 = rebalance(
        users=users,
        assignments=assignments,
        weekly_points_goal=None,
        max_new_items_per_user=5,
    )

    assert moves1 == moves2


# ---- CandidateTodo.excluded_user_id (chain tasks) ------------------------
# Hard-excludes one specific user from one specific item — used for a
# "different person" chain task, where the excluded user is whoever
# completed the parent occurrence. See household_service.crud
# ._spawn_chain_children and the daily sweep's own candidate_todos
# construction in run_balancing (both pass this through).


def test_excluded_user_never_receives_that_item():
    # Only two eligible users, and the excluded one is the only one with
    # room under the cap removed — without the exclusion they'd be the
    # obvious (only) pick; with it, the item must go to the other one.
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=100),
    ]
    todos = [CandidateTodo(todo_id=1, points=5, excluded_user_id=1)]

    result = balance(users=users, tasks=[], todos=todos, max_new_items_per_user=5)

    assert result.todo_assignments[1] == 2


def test_excluded_user_can_still_receive_other_items():
    # Exclusion is per-item, not a removal from `users` entirely.
    users = [EligibleUser(user_id=1, points_this_week=0)]
    todos = [
        CandidateTodo(todo_id=1, points=5, excluded_user_id=1),
        CandidateTodo(todo_id=2, points=5),
    ]

    result = balance(users=users, tasks=[], todos=todos, max_new_items_per_user=5)

    assert 1 not in result.todo_assignments
    assert result.unassigned_todo_ids == [1]
    assert result.todo_assignments[2] == 1


def test_excluded_user_leaves_item_unassigned_if_nobody_else_eligible():
    users = [EligibleUser(user_id=1, points_this_week=0)]
    todos = [CandidateTodo(todo_id=1, points=5, excluded_user_id=1)]

    result = balance(users=users, tasks=[], todos=todos, max_new_items_per_user=5)

    assert result.todo_assignments == {}
    assert result.unassigned_todo_ids == [1]


# ---- CandidateTask/CandidateTodo.pinned_user_ids ("always assign to") --
# A standing household agreement, not a household-wide fairness decision
# — see Task.pinned_users's own docstring and balancing.py's module one.
# A pin can now name more than one person; when it does, the pick among
# THEM still follows the same fair, load-based tie-break the household-
# wide pick uses — it's just scoped to the smaller group.


def test_pinned_task_always_goes_to_its_owner_even_when_most_loaded():
    # Without the pin, user 1 (loaded) would never be picked over user 2
    # (empty) — the pin must override the fairness pick entirely, not
    # just bias it. Single-member group == the original "always this
    # one person" behavior.
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 1


def test_pinned_todo_always_goes_to_its_owner():
    users = [
        EligibleUser(user_id=1, points_this_week=100),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    todo = CandidateTodo(todo_id=1, points=5, pinned_user_ids=frozenset({1}))

    result = balance(users=users, tasks=[], todos=[todo], max_new_items_per_user=5)

    assert result.todo_assignments[1] == 1


def test_pinned_group_goes_to_whichever_member_is_least_loaded():
    # Three-person group — the task must land on user 3 (0 points), not
    # user 1 or 2 (both more loaded), and definitely not user 4 (not in
    # the group at all, even though they're the least loaded overall).
    users = [
        EligibleUser(user_id=1, points_this_week=50),
        EligibleUser(user_id=2, points_this_week=30),
        EligibleUser(user_id=3, points_this_week=0),
        EligibleUser(user_id=4, points_this_week=0),
    ]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1, 2, 3}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 3


def test_pinned_group_skips_an_ineligible_member():
    # User 1 (least loaded of the group) is on break — not in `users`
    # at all — so the next-least-loaded ELIGIBLE group member (user 2)
    # gets it, never user 3 (outside the group).
    users = [
        EligibleUser(user_id=2, points_this_week=10),
        EligibleUser(user_id=3, points_this_week=0),
    ]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1, 2}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 2


def test_pinned_item_bypasses_the_per_run_cap():
    # A standing assignment isn't a "new fairness-allocated item," so it
    # must never be skipped just because its owner already hit the cap
    # from other candidates processed earlier in the same run (points
    # descending, so the heavier plain task lands on user 1 first here).
    users = [EligibleUser(user_id=1, points_this_week=0)]
    plain_task = CandidateTask(task_id=1, expected_points=10, ramp_up_enabled=False)
    pinned_task = CandidateTask(
        task_id=2,
        expected_points=5,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1}),
    )

    result = balance(
        users=users,
        tasks=[plain_task, pinned_task],
        todos=[],
        max_new_items_per_user=1,
    )

    assert result.task_assignments == {1: 1, 2: 1}
    assert result.unassigned_task_ids == []


def test_pinned_item_left_unassigned_when_owner_not_eligible():
    # The pinned owner isn't in `users` at all here (e.g. on break) —
    # must NOT fall back to handing it to someone else; that would
    # defeat the whole point of pinning.
    users = [EligibleUser(user_id=2, points_this_week=0)]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments == {}
    assert result.unassigned_task_ids == [1]


def test_pinned_group_left_unassigned_when_no_member_eligible():
    users = [EligibleUser(user_id=99, points_this_week=0)]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1, 2, 3}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments == {}
    assert result.unassigned_task_ids == [1]


def test_pinned_item_still_counts_toward_owners_load_for_other_items():
    # Once the pinned item lands on user 1, an unrelated plain item
    # processed afterward (lower points, so later in the sort) must see
    # user 1 as already loaded and prefer user 2 instead.
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    pinned_task = CandidateTask(
        task_id=1,
        expected_points=10,
        ramp_up_enabled=False,
        pinned_user_ids=frozenset({1}),
    )
    plain_task = CandidateTask(task_id=2, expected_points=1, ramp_up_enabled=False)

    result = balance(
        users=users,
        tasks=[pinned_task, plain_task],
        todos=[],
        max_new_items_per_user=5,
    )

    assert result.task_assignments[1] == 1
    assert result.task_assignments[2] == 2


def test_pinned_group_excluded_user_is_skipped_even_if_least_loaded():
    # A "different person" chain todo excludes whoever completed its
    # parent — even when that person is the least-loaded member of the
    # pinned group, they must never get it; the next-least-loaded
    # eligible member does instead.
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=20),
    ]
    todo = CandidateTodo(
        todo_id=1, points=5, excluded_user_id=1, pinned_user_ids=frozenset({1, 2})
    )

    result = balance(users=users, tasks=[], todos=[todo], max_new_items_per_user=5)

    assert result.todo_assignments[1] == 2


def test_pinned_group_ramp_up_stays_with_last_assignee():
    # User 2 is least loaded, but user 1 is the ramp-up streak's last
    # completer and is still an eligible group member — stickiness
    # keeps it with user 1 rather than rotating to user 2.
    users = [
        EligibleUser(user_id=1, points_this_week=10),
        EligibleUser(user_id=2, points_this_week=0),
    ]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=True,
        last_assignee_id=1,
        pinned_user_ids=frozenset({1, 2}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 1


def test_pinned_group_ramp_up_falls_back_to_fair_pick_when_last_assignee_ineligible():
    users = [EligibleUser(user_id=2, points_this_week=0)]
    task = CandidateTask(
        task_id=1,
        expected_points=5,
        ramp_up_enabled=True,
        last_assignee_id=1,  # on break, not in `users`
        pinned_user_ids=frozenset({1, 2}),
    )

    result = balance(users=users, tasks=[task], todos=[], max_new_items_per_user=5)

    assert result.task_assignments[1] == 2


def test_rebalance_never_pulls_a_pinned_assignment():
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=100),
    ]
    assignments = [
        PullableAssignment(
            assignment_id=1, holder_id=2, remaining_points=50, pinned=True
        )
    ]

    moves = rebalance(
        users=users,
        assignments=assignments,
        weekly_points_goal=None,
        max_new_items_per_user=5,
    )

    assert moves == []


def test_correct_pins_moves_a_mis_held_assignment_to_its_owner():
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=2,
        pinned_user_ids=frozenset({1}),
        remaining_points=10,
    )
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]

    moves = correct_pins(assignments=[a], users=users)

    assert moves == [(1, 2, 1)]


def test_correct_pins_picks_the_least_loaded_group_member():
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=3,  # outside the group
        pinned_user_ids=frozenset({1, 2}),
        remaining_points=10,
    )
    users = [
        EligibleUser(user_id=1, points_this_week=50),
        EligibleUser(user_id=2, points_this_week=0),
    ]

    moves = correct_pins(assignments=[a], users=users)

    assert moves == [(1, 3, 2)]


def test_correct_pins_leaves_an_assignment_already_held_by_a_group_member():
    # Holder IS in the pinned group (just not the single formerly-
    # tracked "owner") — nothing to correct.
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=2,
        pinned_user_ids=frozenset({1, 2}),
        remaining_points=10,
    )
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]

    assert correct_pins(assignments=[a], users=users) == []


def test_correct_pins_sequences_multiple_moves_by_updated_load():
    # Two mis-held assignments, same two-person pinned group, both
    # initially tied at 0 — the first move must be reflected in load
    # before the second is decided, so they land on DIFFERENT people
    # rather than both piling onto whoever looked least loaded first.
    a1 = PinnedAssignment(
        assignment_id=1,
        holder_id=3,
        pinned_user_ids=frozenset({1, 2}),
        remaining_points=10,
    )
    a2 = PinnedAssignment(
        assignment_id=2,
        holder_id=3,
        pinned_user_ids=frozenset({1, 2}),
        remaining_points=5,
    )
    users = [
        EligibleUser(user_id=1, points_this_week=0),
        EligibleUser(user_id=2, points_this_week=0),
    ]

    moves = correct_pins(assignments=[a1, a2], users=users)

    assert moves == [(1, 3, 1), (2, 3, 2)]


def test_correct_pins_skips_an_assignment_with_progress():
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=2,
        pinned_user_ids=frozenset({1}),
        remaining_points=10,
        has_progress=True,
    )
    users = [EligibleUser(user_id=1, points_this_week=0)]

    assert correct_pins(assignments=[a], users=users) == []


def test_correct_pins_never_undoes_an_accepted_takeover():
    # already_reassigned is sourced from the same TaskAssignment.
    # reassigned_at column crud.accept_takeover_request stamps — a pin
    # correction must not silently move a holder's own accepted
    # takeover right back to the pinned group.
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=2,
        pinned_user_ids=frozenset({1}),
        remaining_points=10,
        already_reassigned=True,
    )
    users = [EligibleUser(user_id=1, points_this_week=0)]

    assert correct_pins(assignments=[a], users=users) == []


def test_correct_pins_leaves_it_when_owner_not_currently_eligible():
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=2,
        pinned_user_ids=frozenset({1}),
        remaining_points=10,
    )
    users = [EligibleUser(user_id=99, points_this_week=0)]

    assert correct_pins(assignments=[a], users=users) == []


def test_correct_pins_skips_a_fully_completed_assignment():
    a = PinnedAssignment(
        assignment_id=1,
        holder_id=2,
        pinned_user_ids=frozenset({1}),
        remaining_points=0,
    )
    users = [EligibleUser(user_id=1, points_this_week=0)]

    assert correct_pins(assignments=[a], users=users) == []
