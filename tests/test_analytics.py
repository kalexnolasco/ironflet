"""Tests for analytics.py.

No database and no Flet: everything here is a pure function, so the cases are
built from literal data. Where a test pins down a disagreement with
`storage.py`, the storage behaviour is asserted alongside the new one so the
difference is visible rather than implied.
"""

from __future__ import annotations

from datetime import date, timedelta

from analytics import (
    COARSE_MUSCLE,
    PRKind,
    all_personal_records,
    best_e1rm,
    detect_new_records,
    e1rm_progression,
    estimated_1rm,
    is_warmup,
    moving_average,
    personal_records,
    resolve_muscles,
    session_count,
    sets_per_muscle_group,
    total_volume,
    training_streak,
    volume,
    week_key,
    week_stats,
    working_sets,
)

# 2026-08-13 is a Thursday, so this anchor week runs Mon 2026-08-10 → Sun 08-16.
THURSDAY = date(2026, 8, 13)
MONDAY = date(2026, 8, 10)
SATURDAY = date(2026, 8, 15)
SUNDAY = date(2026, 8, 16)


def entry(day, exercise, sets, **kw):
    """A workout entry in the dict shape `Storage.export_all()` produces."""
    return {
        "date": day.isoformat() if isinstance(day, date) else day,
        "exercise": exercise,
        "sets": sets,
        **kw,
    }


def s(weight, reps, **kw):
    return {"weight": weight, "reps": reps, **kw}


# ── Epley ────────────────────────────────────────────────────────────────


def test_epley_against_hand_computed_values():
    # 100 × (1 + 5/30)  = 100 × 1.16666… = 116.67
    assert estimated_1rm(100, 5) == 116.67
    # 60 × (1 + 10/30)  = 60 × 1.33333… = 80.0 exactly
    assert estimated_1rm(60, 10) == 80.0
    # 140 × (1 + 3/30)  = 140 × 1.1      = 154.0
    assert estimated_1rm(140, 3) == 154.0
    # 82.5 × (1 + 8/30) = 82.5 × 1.26666… = 104.5
    assert estimated_1rm(82.5, 8) == 104.5


def test_epley_single_rep_is_the_weight_itself():
    """A true single is the max. Raw Epley would inflate it by 3.3%."""
    assert estimated_1rm(120, 1) == 120.0
    assert estimated_1rm(120, 1) != round(120 * (1 + 1 / 30), 2)


def test_epley_none_below_one_rep():
    assert estimated_1rm(100, 0) is None
    assert estimated_1rm(100, -3) is None
    assert estimated_1rm(100, None) is None


def test_epley_none_for_non_positive_load():
    """Bodyweight rows logged at 0 kg must not produce a 0.0 "max"."""
    assert estimated_1rm(0, 10) is None
    assert estimated_1rm(-20, 5) is None


def test_epley_tolerates_string_and_rejects_bool():
    assert estimated_1rm("100", "5") == 116.67
    assert estimated_1rm("82,5", 8) == 104.5  # comma decimal from the bot
    assert estimated_1rm(True, 5) is None


def test_best_e1rm_picks_the_best_set_not_the_heaviest():
    sets = [s(100, 5), s(110, 2), s(90, 12)]
    # 116.67 vs 117.33 vs 126.0 → the 12-rep set estimates highest
    assert best_e1rm(sets) == 126.0
    assert best_e1rm([]) is None
    assert best_e1rm([s(0, 10)]) is None


def test_e1rm_progression_is_one_point_per_day_oldest_first():
    entries = [
        entry(date(2026, 8, 3), "Squat", [s(100, 5)]),
        entry(date(2026, 8, 10), "Squat", [s(100, 8)]),
        entry(date(2026, 8, 10), "Squat", [s(105, 8)]),  # same day, logged twice
        entry(date(2026, 8, 10), "Deadlift", [s(200, 5)]),
    ]
    prog = e1rm_progression(entries, "Squat")
    assert [p["date"] for p in prog] == ["2026-08-03", "2026-08-10"]
    assert prog[0]["e1rm"] == 116.67
    assert prog[1]["e1rm"] == 133.0  # 105 × (1 + 8/30), the better of the two


# ── warm-up handling ─────────────────────────────────────────────────────


def test_is_warmup_only_for_warmup_types():
    assert is_warmup(s(60, 10, type="warmup"))
    assert is_warmup(s(60, 10, type="Warm-Up"))
    assert not is_warmup(s(60, 10))  # no type at all: pre-feature rows are work
    assert not is_warmup(s(60, 10, type="normal"))
    assert not is_warmup(s(60, 10, type="dropset"))


def test_warmup_sets_do_not_count_towards_volume():
    sets = [s(60, 10, type="warmup"), s(100, 5), s(100, 5)]
    assert volume(sets) == 1000.0  # only the two working sets
    assert len(working_sets(sets)) == 2
    # and the warm-up is genuinely excluded, not merely outweighed
    assert volume([s(60, 10, type="warmup")]) == 0.0


def test_warmup_sets_cannot_set_a_pr():
    """A deliberately absurd warm-up must lose to a modest working set."""
    entries = [
        entry(THURSDAY, "Squat", [s(300, 10, type="warmup"), s(100, 5)]),
    ]
    pr = personal_records(entries, "Squat")
    assert pr.max_weight.value == 100.0  # not 300
    assert pr.e1rm.value == 116.67  # not 400.0
    assert pr.session_volume.value == 500.0  # not 3500.0


def test_all_warmup_session_has_no_records_and_no_volume():
    entries = [entry(THURSDAY, "Squat", [s(60, 10, type="warmup")])]
    pr = personal_records(entries, "Squat")
    assert pr.all() == []
    assert total_volume(entries) == 0.0


# ── volume ───────────────────────────────────────────────────────────────


def test_volume_and_total_volume():
    assert volume([s(100, 5), s(80, 8)]) == 1140.0
    assert volume([]) == 0.0
    assert volume([s(0, 10)]) == 0.0  # bodyweight contributes nothing
    assert volume([s(100, 0)]) == 0.0
    entries = [
        entry(THURSDAY, "Squat", [s(100, 5)]),
        entry(THURSDAY, "Bench", [s(80, 5)]),
    ]
    assert total_volume(entries) == 900.0


# ── session_count: the get_week_stats bug ────────────────────────────────


def test_session_count_counts_days_not_rows():
    """One session of six exercises is ONE session.

    `Storage.get_week_stats()` returns `len(rows)` here, so this exact input
    is reported on the home screen as "6 Sessions".
    """
    six_exercises = [
        entry(THURSDAY, name, [s(100, 5)])
        for name in (
            "Barbell Bench Press",
            "Barbell Military Press",
            "Incline DB Press",
            "Lateral Raises",
            "Dips",
            "Triceps Pushdown",
        )
    ]
    assert len(six_exercises) == 6  # what storage counts
    assert session_count(six_exercises) == 1  # what the label means


def test_session_count_across_several_days():
    entries = [
        entry(date(2026, 8, 10), "Squat", [s(100, 5)]),
        entry(date(2026, 8, 10), "Leg Press", [s(200, 10)]),
        entry(date(2026, 8, 11), "Bench", [s(80, 5)]),
        entry(date(2026, 8, 12), "Deadlift", [s(140, 5)]),
    ]
    assert session_count(entries) == 3
    assert session_count([]) == 0


def test_week_stats_uses_days_and_skips_warmups():
    entries = [
        entry(THURSDAY, "Squat", [s(60, 10, type="warmup"), s(100, 5)]),
        entry(THURSDAY, "Leg Press", [s(200, 10)]),
    ]
    st = week_stats(entries, today=THURSDAY)
    assert st["sessions"] == 1
    assert st["sets"] == 2
    assert st["volume"] == 2500.0


# ── training_streak: the get_streak bug ──────────────────────────────────


def five_day_weeks(n, last_monday=MONDAY):
    """Mon–Fri sessions for `n` consecutive weeks, ending at `last_monday`."""
    out = []
    for w in range(n):
        monday = last_monday - timedelta(days=7 * w)
        out += [monday + timedelta(days=d) for d in range(5)]
    return out


def test_streak_survives_the_two_rest_days():
    """THE BUG: 5 on / 2 off breaks a day-based streak every weekend.

    `Storage.get_streak()` walks back from today over consecutive calendar
    days, so on Saturday — after a flawless Mon–Fri — it finds nothing dated
    today and returns 0.
    """
    dates = five_day_weeks(4)

    # The old semantics, reproduced exactly, on the Saturday after a full week.
    day_set = set(dates)
    old, d = 0, SATURDAY
    while d in day_set:
        old += 1
        d -= timedelta(days=1)
    assert old == 0  # four perfect weeks reported as a 🔥 0

    assert training_streak(dates, today=SATURDAY) == 4
    assert training_streak(dates, today=SUNDAY) == 4


def test_streak_is_not_zero_on_any_rest_day_of_a_perfect_week():
    dates = five_day_weeks(3)
    for rest_day in (SATURDAY, SUNDAY):
        assert training_streak(dates, today=rest_day) == 3


def test_streak_counts_weeks_not_sessions():
    assert training_streak(five_day_weeks(1), today=SATURDAY) == 1
    assert training_streak(five_day_weeks(6), today=SATURDAY) == 6
    assert training_streak([], today=SATURDAY) == 0


def test_current_week_in_progress_does_not_break_the_streak():
    """Mid-week the current week is unfinished, not failed."""
    dates = five_day_weeks(3, last_monday=MONDAY - timedelta(days=7))
    dates += [MONDAY, MONDAY + timedelta(days=1)]  # Mon+Tue of the live week
    # Only 2 sessions so far this week — below the minimum, but it is Thursday.
    assert training_streak(dates, today=THURSDAY) == 3
    # Once the week hits the minimum it joins the streak.
    dates += [MONDAY + timedelta(days=2), MONDAY + timedelta(days=3)]
    assert training_streak(dates, today=THURSDAY) == 4


def test_a_genuinely_missed_week_breaks_the_streak():
    dates = five_day_weeks(2)  # the two most recent weeks
    dates += five_day_weeks(2, last_monday=MONDAY - timedelta(days=28))  # then a gap
    assert training_streak(dates, today=SATURDAY) == 2


def test_streak_minimum_is_configurable_and_tolerates_one_missed_day():
    four_days = []
    for w in range(3):
        monday = MONDAY - timedelta(days=7 * w)
        four_days += [monday + timedelta(days=d) for d in range(4)]  # 4 of 5
    assert training_streak(four_days, today=SATURDAY) == 3  # default min 4
    assert training_streak(four_days, today=SATURDAY, min_sessions=5) == 0


def test_streak_ignores_duplicate_rows_on_the_same_day():
    """Six rows on one day is one session, so it must not fake a week."""
    dates = [MONDAY] * 6
    assert training_streak(dates, today=THURSDAY) == 0


def test_streak_ignores_future_dates():
    dates = five_day_weeks(2) + [SATURDAY + timedelta(days=30)]
    assert training_streak(dates, today=SATURDAY) == 2


def test_week_key_is_sortable_and_iso():
    assert week_key(THURSDAY) == week_key(MONDAY) == "2026-W33"
    assert week_key(MONDAY - timedelta(days=7)) == "2026-W32"


# ── personal records ─────────────────────────────────────────────────────


def test_personal_records_three_kinds():
    entries = [
        entry(date(2026, 8, 3), "Squat", [s(100, 5), s(100, 5)]),
        entry(date(2026, 8, 10), "Squat", [s(120, 2), s(90, 10)]),
    ]
    pr = personal_records(entries, "Squat")
    assert pr.max_weight.value == 120.0
    assert pr.max_weight.date == "2026-08-10"
    # The three kinds disagree on purpose: 120×2 estimates 128.0 and 90×10
    # estimates 120.0, so the heavy double owns both the weight and the e1RM
    # record even though the 10-rep set is the bigger pile of tonnage.
    assert pr.e1rm.value == 128.0
    assert pr.session_volume.value == 1140.0  # 240 + 900 on 08-10 beats 1000


def test_personal_records_e1rm_picks_the_true_best():
    entries = [entry(THURSDAY, "Squat", [s(120, 2), s(90, 10)])]
    pr = personal_records(entries, "Squat")
    assert pr.e1rm.value == 128.0  # 120 × (1 + 2/30)
    assert pr.e1rm.weight == 120.0
    assert pr.e1rm.reps == 2


def test_personal_records_session_volume_merges_rows_of_the_same_day():
    entries = [
        entry(THURSDAY, "Squat", [s(100, 5)]),
        entry(THURSDAY, "Squat", [s(100, 5)]),
    ]
    assert personal_records(entries, "Squat").session_volume.value == 1000.0


def test_personal_records_empty_for_unknown_exercise():
    pr = personal_records([entry(THURSDAY, "Squat", [s(100, 5)])], "Bench")
    assert pr.all() == []
    assert pr.get(PRKind.E1RM) is None


def test_max_weight_ignores_a_set_that_was_never_performed():
    entries = [entry(THURSDAY, "Squat", [s(200, 0), s(100, 5)])]
    assert personal_records(entries, "Squat").max_weight.value == 100.0


def test_all_personal_records_keyed_by_exercise():
    entries = [
        entry(THURSDAY, "Squat", [s(100, 5)]),
        entry(THURSDAY, "Bench", [s(80, 5)]),
    ]
    prs = all_personal_records(entries)
    assert set(prs) == {"Squat", "Bench"}
    assert prs["Bench"].max_weight.value == 80.0


def test_detect_new_records_first_ever_log_sets_all_three():
    new = detect_new_records([], entry(THURSDAY, "Squat", [s(100, 5)]))
    assert {r.kind for r in new} == {PRKind.E1RM, PRKind.MAX_WEIGHT, PRKind.SESSION_VOLUME}


def test_detect_new_records_ties_are_not_records():
    history = [entry(date(2026, 8, 3), "Squat", [s(100, 5)])]
    same = entry(THURSDAY, "Squat", [s(100, 5)])
    assert detect_new_records(history, same) == []


def test_detect_new_records_reports_only_the_kinds_beaten():
    history = [entry(date(2026, 8, 3), "Squat", [s(100, 5), s(100, 5)])]
    # Heavier single: beats weight and e1RM, but the session is lighter work.
    heavier = entry(THURSDAY, "Squat", [s(130, 1)])
    kinds = {r.kind for r in detect_new_records(history, heavier)}
    assert kinds == {PRKind.E1RM, PRKind.MAX_WEIGHT}
    assert PRKind.SESSION_VOLUME not in kinds


def test_detect_new_records_ignores_other_exercises():
    history = [entry(date(2026, 8, 3), "Bench", [s(300, 5)])]
    new = detect_new_records(history, entry(THURSDAY, "Squat", [s(60, 5)]))
    assert len(new) == 3  # the heavy bench is irrelevant to the squat PR


def test_detect_new_records_ignores_a_warmup_pr_attempt():
    history = [entry(date(2026, 8, 3), "Squat", [s(100, 5)])]
    warmup_only = entry(THURSDAY, "Squat", [s(500, 5, type="warmup")])
    assert detect_new_records(history, warmup_only) == []


def test_record_carries_a_ui_label():
    pr = personal_records([entry(THURSDAY, "Squat", [s(100, 5)])], "Squat")
    assert pr.e1rm.label == "Estimated 1RM"


# ── muscle resolution ────────────────────────────────────────────────────


def test_resolve_muscles_exact_hit():
    res = resolve_muscles("Barbell Bench Press")
    assert res.status == "exact"
    assert "chest" in res.primary


def test_resolve_muscles_unknown_is_reported_not_swallowed():
    """`details_for()` goes through EXERCISE_IMAGE, so an unmapped name has no
    muscle data either — the two tables are keyed by the same slug.

    `Hip Thrust` used to be the other example here. It resolves now: it was
    given a slug and a details entry from the source database. Bulgarian Split
    Squat stays unknown because that source has no such exercise at all.
    """
    res = resolve_muscles("Bulgarian Split Squat")
    assert res.status == "unknown"
    assert res.unresolved == ("Bulgarian Split Squat",)
    assert res.primary == ()


def test_resolve_muscles_splits_combination_entries():
    """The routine logs a superset as one exercise the database never lists."""
    assert resolve_muscles("SS: Squat + Lying Leg Curl").status == "exact"
    res = resolve_muscles("SS: Squat + Lying Leg Curl")
    assert "quadriceps" in res.primary
    assert "hamstrings" in res.primary


def test_resolve_muscles_partial_declares_what_is_missing():
    res = resolve_muscles("SS: Leg Press + Romanian DL")
    assert res.status == "partial"
    assert res.unresolved == ("Romanian DL",)
    assert "quadriceps" in res.primary  # the half that did resolve still counts


def test_resolve_muscles_uses_an_injectable_lookup():
    table = {"Fake Press": {"primary": ["chest"], "secondary": ["triceps"]}}
    res = resolve_muscles("Fake Press", lookup=table.get)
    assert res.primary == ("chest",)
    assert res.secondary == ("triceps",)
    assert resolve_muscles("Nope", lookup=table.get).status == "unknown"


def test_resolve_muscles_recovers_most_of_the_missing_keys():
    """Splitting takes the unmapped routine keys down to 8.

    It was 9 until `Hip Thrust` got both a slug and a details entry pulled from
    the source database. What is left is seven composite entries — two or three
    movements on one line, where at least one component still does not resolve —
    plus `Bulgarian Split Squat`, which is absent from the 500-exercise source
    altogether.
    """
    import data
    from exercises import exercise_key

    keys = set()
    for name in dir(data):
        value = getattr(data, name)
        if isinstance(value, list) and value and isinstance(value[0], data.TrainingDay):
            for day in value:
                keys.update(exercise_key(ex) for ex in day.exercises)

    unknown = {k for k in keys if resolve_muscles(k).status == "unknown"}
    assert len(keys) == 104
    assert len(unknown) == 8
    assert "Bulgarian Split Squat" in unknown
    assert "Hip Thrust" not in unknown
    # Everything else left over is a composite line, never a single movement.
    assert all(
        any(t in k for t in ("+", "SS:", "Bi-set", "Triset"))
        for k in unknown - {"Bulgarian Split Squat"}
    )


# ── sets per muscle group ────────────────────────────────────────────────


def test_sets_per_muscle_group_counts_primary_and_half_secondary():
    entries = [entry(THURSDAY, "Barbell Bench Press", [s(100, 5)] * 4)]
    mv = sets_per_muscle_group(entries, weeks=1, today=THURSDAY)
    assert mv.weeks == ("2026-W33",)
    assert mv.by_week["2026-W33"]["chest"] == 4.0  # primary, full credit
    assert mv.by_week["2026-W33"]["triceps"] == 2.0  # secondary, half credit
    assert mv.totals["chest"] == 4.0


def test_sets_per_muscle_group_strict_direct_sets():
    entries = [entry(THURSDAY, "Barbell Bench Press", [s(100, 5)] * 4)]
    mv = sets_per_muscle_group(entries, weeks=1, today=THURSDAY, secondary_weight=0.0)
    assert mv.by_week["2026-W33"]["chest"] == 4.0
    assert "triceps" not in mv.by_week["2026-W33"]


def test_sets_per_muscle_group_excludes_warmups():
    sets = [s(60, 10, type="warmup"), s(100, 5), s(100, 5)]
    mv = sets_per_muscle_group([entry(THURSDAY, "Barbell Bench Press", sets)], 1, today=THURSDAY)
    assert mv.by_week["2026-W33"]["chest"] == 2.0  # not 3


def test_sets_per_muscle_group_reports_unattributed_instead_of_dropping():
    entries = [entry(THURSDAY, "Bulgarian Split Squat", [s(100, 10)] * 3)]
    mv = sets_per_muscle_group(entries, weeks=1, today=THURSDAY)
    assert mv.by_week["2026-W33"] == {}
    assert mv.unattributed == {"Bulgarian Split Squat": 3}
    assert mv.unattributed_sets == 3


def test_hip_thrust_now_counts_towards_glutes():
    """It used to fall into `unattributed`, so leg volume was under-counted."""
    entries = [entry(THURSDAY, "Hip Thrust", [s(100, 10)] * 3)]
    mv = sets_per_muscle_group(entries, weeks=1, today=THURSDAY)
    assert mv.by_week["2026-W33"]["glutes"] == 3.0
    assert mv.unattributed == {}


def test_sets_per_muscle_group_flags_partial_combinations():
    entries = [entry(THURSDAY, "SS: Leg Press + Romanian DL", [s(100, 10)] * 3)]
    mv = sets_per_muscle_group(entries, weeks=1, today=THURSDAY)
    assert mv.partial == {"SS: Leg Press + Romanian DL": ("Romanian DL",)}
    assert mv.by_week["2026-W33"]["quadriceps"] == 3.0


def test_sets_per_muscle_group_superset_credits_both_components():
    entries = [entry(THURSDAY, "SS: Squat + Lying Leg Curl", [s(100, 10)] * 3)]
    mv = sets_per_muscle_group(entries, weeks=1, today=THURSDAY)
    week = mv.by_week["2026-W33"]
    # Each round contains both movements, so both primaries get all three sets.
    assert week["quadriceps"] == 3.0
    # Hamstrings are primary in the leg curl (3.0) *and* secondary in the squat
    # (3 × 0.5), so they legitimately land above the round count at 4.5. Credit
    # accumulates across components rather than being capped — a muscle worked
    # twice in a paired set was, in fact, worked twice.
    assert week["hamstrings"] == 4.5
    assert week["glutes"] == 1.5  # squat secondary only


def test_sets_per_muscle_group_buckets_by_week_and_keeps_empty_weeks():
    entries = [
        entry(MONDAY, "Barbell Bench Press", [s(100, 5)] * 2),
        entry(MONDAY - timedelta(days=14), "Barbell Bench Press", [s(100, 5)] * 5),
    ]
    mv = sets_per_muscle_group(entries, weeks=3, today=THURSDAY)
    assert mv.weeks == ("2026-W31", "2026-W32", "2026-W33")
    assert mv.by_week["2026-W31"]["chest"] == 5.0
    assert mv.by_week["2026-W32"] == {}  # present but empty: no gap to handle
    assert mv.by_week["2026-W33"]["chest"] == 2.0
    assert mv.totals["chest"] == 7.0


def test_sets_per_muscle_group_ignores_entries_outside_the_window():
    old = entry(MONDAY - timedelta(days=70), "Barbell Bench Press", [s(100, 5)] * 5)
    mv = sets_per_muscle_group([old], weeks=4, today=THURSDAY)
    assert mv.totals == {}


def test_sets_per_muscle_group_coarse_folds_into_app_buckets():
    entries = [entry(THURSDAY, "Barbell Row", [s(80, 10)] * 4)]
    fine = sets_per_muscle_group(entries, 1, today=THURSDAY)
    coarse = sets_per_muscle_group(entries, 1, today=THURSDAY, coarse=True)
    assert "middle back" in fine.by_week["2026-W33"]
    assert "Back" in coarse.by_week["2026-W33"]
    assert set(coarse.totals) <= {"Chest", "Back", "Shoulder", "Biceps", "Triceps", "Leg", "Abs"}


def test_coarse_mapping_covers_the_whole_details_vocabulary():
    """Every muscle name the database can emit must have a display bucket."""
    from exercise_details import EXERCISE_DETAILS

    seen = set()
    for details in EXERCISE_DETAILS.values():
        seen.update(details.get("primary") or ())
        seen.update(details.get("secondary") or ())
    assert seen <= set(COARSE_MUSCLE), seen - set(COARSE_MUSCLE)


# ── moving average ───────────────────────────────────────────────────────


def test_moving_average_smooths_a_daily_swing():
    weights = [
        {"date": "2026-08-10", "kg": 80.0},
        {"date": "2026-08-11", "kg": 81.0},
        {"date": "2026-08-12", "kg": 79.0},
    ]
    avg = moving_average(weights, days=7)
    assert [p["date"] for p in avg] == ["2026-08-10", "2026-08-11", "2026-08-12"]
    assert avg[0]["kg"] == 80.0
    assert avg[1]["kg"] == 80.5
    assert avg[2]["kg"] == 80.0  # the 1 kg water swing is gone


def test_moving_average_window_is_calendar_days_not_samples():
    """Two weigh-ins a month apart must not average together."""
    weights = [
        {"date": "2026-07-01", "kg": 70.0},
        {"date": "2026-08-01", "kg": 80.0},
    ]
    avg = moving_average(weights, days=7)
    assert avg[1]["kg"] == 80.0  # not 75.0


def test_moving_average_drops_readings_leaving_the_window():
    weights = [{"date": f"2026-08-{d:02d}", "kg": 80.0} for d in range(1, 8)]
    weights.append({"date": "2026-08-08", "kg": 87.0})
    avg = moving_average(weights, days=7)
    # 2026-08-08 window is 08-02…08-08: six 80s and one 87.
    assert avg[-1]["kg"] == round((80.0 * 6 + 87.0) / 7, 2)


def test_moving_average_collapses_same_day_duplicates():
    weights = [
        {"date": "2026-08-10", "kg": 80.0},
        {"date": "2026-08-10", "kg": 82.0},
    ]
    avg = moving_average(weights, days=7)
    assert len(avg) == 1
    assert avg[0]["kg"] == 81.0


def test_moving_average_accepts_tuples_and_empty_input():
    assert moving_average([("2026-08-10", 80.0)])[0]["kg"] == 80.0
    assert moving_average([]) == []
    assert moving_average(None) == []


def test_moving_average_skips_unparseable_rows():
    weights = [
        {"date": "not-a-date", "kg": 80.0},
        {"date": "2026-08-10", "kg": None},
        {"date": "2026-08-11", "kg": 80.0},
    ]
    assert moving_average(weights) == [{"date": "2026-08-11", "kg": 80.0}]


# ── shape tolerance ──────────────────────────────────────────────────────


def test_functions_accept_storage_dataclass_entries():
    """The same helpers must work on WorkoutEntry, not just on dicts."""
    from storage import WorkoutEntry

    rows = [
        WorkoutEntry(
            date=THURSDAY.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=1,
            sets=[s(100, 5), s(60, 10, type="warmup")],
        ),
    ]
    assert session_count(rows) == 1
    assert total_volume(rows) == 500.0
    assert personal_records(rows, "Squat").max_weight.value == 100.0
    assert sets_per_muscle_group(rows, 1, today=THURSDAY).unattributed == {}
