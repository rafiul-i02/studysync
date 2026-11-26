from datetime import datetime, time, timedelta
from models import StudySlot, Task, db

STUDY_WINDOWS = [
    (time(6, 0), time(12, 0)),
    (time(18, 0), time(23, 59)),
]


def duration_hours(start_t: time, end_t: time) -> float:
    start_dt = datetime.combine(datetime.today().date(), start_t)
    end_dt = datetime.combine(datetime.today().date(), end_t)
    diff_seconds = (end_dt - start_dt).total_seconds()
    return round(diff_seconds / 3600.0, 2)


def _overlaps(s1: time, e1: time, s2: time, e2: time) -> bool:
    return s1 < e2 and e1 > s2


def scheduled_hours_for_day(user_id: int, target_date) -> float:
    slots = StudySlot.query.filter(
        StudySlot.user_id == user_id,
        StudySlot.date == target_date,
        StudySlot.status != "cancelled",
    ).all()
    total = sum(duration_hours(s.start_time, s.end_time) for s in slots)
    return round(total, 2)


def _rounded_now_cutoff(now_dt: datetime) -> time | None:
    mins = ((now_dt.minute // 15) + 1) * 15
    hr = now_dt.hour + (mins // 60)
    rem_min = mins % 60
    if hr >= 24:
        return None
    return time(hr, rem_min)


def suggest_free_slot(
    user_id: int,
    target_date,
    desired_hours: float = 1.0,
    latest_time: time | None = None,
    ignore_past_for_suggestion: bool = False,
):
    existing = StudySlot.query.filter(
        StudySlot.user_id == user_id,
        StudySlot.date == target_date,
        StudySlot.status != "cancelled",
    ).order_by(StudySlot.start_time.asc()).all()

    now_dt = datetime.now()
    now_cutoff = None
    if (not ignore_past_for_suggestion) and target_date == now_dt.date():
        now_cutoff = _rounded_now_cutoff(now_dt)
        if now_cutoff is None:
            return None

    needed = timedelta(hours=max(0.5, min(desired_hours, 4.0)))

    for win_start, win_end in STUDY_WINDOWS:
        effective_start = win_start
        if now_cutoff and now_cutoff > effective_start:
            effective_start = now_cutoff

        effective_end = win_end
        if latest_time is not None and latest_time < effective_end:
            effective_end = latest_time

        if effective_end <= effective_start:
            continue

        cursor = datetime.combine(target_date, effective_start)
        block_end = datetime.combine(target_date, effective_end)

        for slot in existing:
            s_dt = datetime.combine(target_date, slot.start_time)
            e_dt = datetime.combine(target_date, slot.end_time)
            if e_dt <= cursor or s_dt >= block_end:
                continue
            window_end = min(s_dt, block_end)
            if window_end > cursor and (window_end - cursor) >= needed:
                return cursor.time(), (cursor + needed).time()
            if e_dt > cursor:
                cursor = e_dt

        if (block_end - cursor) >= needed:
            return cursor.time(), (cursor + needed).time()

    return None


def _suggest_within_deadline(user, start_from_date, desired_hours: float, task: Task | None = None):
    now_dt = datetime.now()
    today = now_dt.date()

    if task is not None:
        if task.deadline <= now_dt:
            return None, f"Task '{task.title}' deadline ({task.deadline.strftime('%Y-%m-%d %H:%M')}) has already passed."
        max_date = task.deadline.date()
    else:
        max_date = max(start_from_date, today + timedelta(days=7))

    check_date = max(start_from_date, today)
    while check_date <= max_date:
        used_today = scheduled_hours_for_day(user.id, check_date)
        rem_limit = round(user.daily_study_limit_hours - used_today, 2)
        if rem_limit >= 0.5:
            latest_t = task.deadline.time() if (task is not None and check_date == max_date) else None
            # Try desired duration first, then step down to 0.5h if window is tighter
            try_hrs = min(desired_hours, rem_limit)
            while try_hrs >= 0.5:
                free = suggest_free_slot(user.id, check_date, try_hrs, latest_time=latest_t)
                if free:
                    return (check_date, free[0], free[1]), None
                try_hrs = round(try_hrs - 0.5, 2)
        check_date += timedelta(days=1)

    if task is not None:
        return None, f"No free slot available before task deadline ({task.deadline.strftime('%Y-%m-%d %H:%M')})."
    return None, f"No free {desired_hours}h window found."


def validate_and_check_conflict(user, target_date, start_t: time, end_t: time, linked_task: Task | None = None):
    now_dt = datetime.now()
    if target_date < now_dt.date():
        return False, "Cannot schedule a study slot in the past.", None

    if target_date == now_dt.date() and start_t < now_dt.time():
        return False, "Start time cannot be in the past for today.", None

    if end_t <= start_t:
        return False, "End time must be after start time.", None

    req_hours = duration_hours(start_t, end_t)
    if req_hours < 0.25 or req_hours > 8.0:
        return False, "Slot duration must be between 15 minutes and 8 hours.", None

    if linked_task is not None:
        if linked_task.deadline <= now_dt:
            return False, f"Task '{linked_task.title}' deadline has already passed.", None

        slot_end_dt = datetime.combine(target_date, end_t)
        if slot_end_dt > linked_task.deadline:
            found, note = _suggest_within_deadline(user, now_dt.date(), req_hours, task=linked_task)
            hint = (
                f"Suggested slot before deadline: {found[0]} {found[1].strftime('%H:%M')} - {found[2].strftime('%H:%M')}"
                if found
                else note
            )
            return (
                False,
                f"Slot ends after '{linked_task.title}' deadline ({linked_task.deadline.strftime('%Y-%m-%d %H:%M')}).",
                hint,
            )

    existing = StudySlot.query.filter(
        StudySlot.user_id == user.id,
        StudySlot.date == target_date,
        StudySlot.status != "cancelled",
    ).all()

    for slot in existing:
        if _overlaps(start_t, end_t, slot.start_time, slot.end_time):
            found, note = _suggest_within_deadline(user, target_date, req_hours, task=linked_task)
            if found:
                hint = f"Suggested free slot: {found[0]} {found[1].strftime('%H:%M')} - {found[2].strftime('%H:%M')}"
            else:
                hint = note
            return (
                False,
                f"Time conflict with existing slot ({slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}).",
                hint,
            )

    current_day_hours = scheduled_hours_for_day(user.id, target_date)
    if round(current_day_hours + req_hours, 2) > user.daily_study_limit_hours:
        remaining = max(0.0, round(user.daily_study_limit_hours - current_day_hours, 2))
        return (
            False,
            f"Daily study limit ({user.daily_study_limit_hours}h) exceeded on {target_date}. Remaining today: {remaining}h.",
            None,
        )

    return True, None, None


def find_next_available_slot(user, chunk_hours: float, deadline_dt: datetime):
    now_dt = datetime.now()
    today = now_dt.date()
    if deadline_dt <= now_dt:
        return None

    limit_date = min(today + timedelta(days=14), deadline_dt.date())
    day_offset = 0
    while (today + timedelta(days=day_offset)) <= limit_date:
        day = today + timedelta(days=day_offset)
        day_offset += 1

        used_today = scheduled_hours_for_day(user.id, day)
        remaining_limit = round(user.daily_study_limit_hours - used_today, 2)
        if remaining_limit < 0.5:
            continue

        latest_t = deadline_dt.time() if day == deadline_dt.date() else None
        # Try desired chunk first, then step down by 0.5h so tight windows (e.g. 22:15 - 23:45) are used
        try_chunk = min(chunk_hours, remaining_limit)
        while try_chunk >= 0.5:
            free = suggest_free_slot(user.id, day, try_chunk, latest_time=latest_t)
            if free:
                return day, free[0], free[1], round(try_chunk, 2)
            try_chunk = round(try_chunk - 0.5, 2)

    return None


def auto_schedule_tasks(user):
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    now_dt = datetime.now()

    active_tasks = Task.query.filter(
        Task.user_id == user.id,
        Task.status.in_(["pending", "in_progress"]),
    ).all()

    active_tasks.sort(key=lambda t: (priority_rank.get(t.priority, 1), t.deadline))

    created_slots = 0
    scheduled_summary = []
    unscheduled_details = []

    for task in active_tasks:
        existing_task_slots = StudySlot.query.filter(
            StudySlot.user_id == user.id,
            StudySlot.task_id == task.id,
            StudySlot.status != "cancelled",
        ).all()
        already_scheduled_hours = sum(
            duration_hours(s.start_time, s.end_time) for s in existing_task_slots
        )
        remaining_needed = round(task.estimated_hours - already_scheduled_hours, 2)
        if remaining_needed <= 0:
            continue

        if task.deadline <= now_dt:
            unscheduled_details.append(f"{task.title} (deadline passed)")
            continue

        added_for_this_task = 0.0
        while remaining_needed > 0:
            chunk = min(remaining_needed, 2.0)
            found = find_next_available_slot(user, chunk, task.deadline)
            if not found:
                break

            slot_date, st, et, actual_hrs = found
            new_slot = StudySlot(
                user_id=user.id,
                task_id=task.id,
                date=slot_date,
                start_time=st,
                end_time=et,
                status="scheduled",
            )
            db.session.add(new_slot)
            db.session.flush()

            created_slots += 1
            added_for_this_task = round(added_for_this_task + actual_hrs, 2)
            remaining_needed = round(remaining_needed - actual_hrs, 2)

        if added_for_this_task > 0:
            if remaining_needed > 0:
                scheduled_summary.append(
                    f"{task.title}: +{added_for_this_task}h scheduled ({remaining_needed}h left before deadline)"
                )
            else:
                scheduled_summary.append(f"{task.title}: +{added_for_this_task}h scheduled (fully covered)")
        else:
            unscheduled_details.append(f"{task.title} ({remaining_needed}h left)")

    return created_slots, scheduled_summary, unscheduled_details