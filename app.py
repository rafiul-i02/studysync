import mimetypes
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from assistant import generate_assistant_reply
from models import AuditLog, Course, StudySlot, Task, TaskResource, User, db
from scheduler import auto_schedule_tasks, duration_hours, validate_and_check_conflict

MAX_RESOURCE_BYTES = 5 * 1024 * 1024  # 5 MB limit
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".doc", ".txt"}
INLINE_VIEW_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt"}
ALLOWED_TASK_TRANSITIONS = {
    "pending": {"pending", "in_progress", "completed"},
    "in_progress": {"pending", "in_progress", "completed"},
    "completed": {"completed", "in_progress", "pending"},
}


def create_app():
    app = Flask(__name__)

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        secret_key = "dev-secret-change-in-prod"
    app.config["SECRET_KEY"] = secret_key
    app.config["MAX_CONTENT_LENGTH"] = MAX_RESOURCE_BYTES

    default_upload_dir = os.path.join(app.root_path, "uploads", "resources")
    upload_dir = os.environ.get("UPLOAD_FOLDER") or default_upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_dir

    database_url = os.environ.get("DATABASE_URL", "sqlite:///studysync.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    def log_audit(action, target_type, target_id=None, status="allowed", details=None, actor_id=None):
        uid = actor_id if actor_id is not None else (current_user.id if current_user.is_authenticated else None)
        entry = AuditLog(
            actor_id=uid,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            status=status,
            details=details,
        )
        db.session.add(entry)
        db.session.commit()

    def can_access_record(record):
        if not current_user.is_authenticated:
            return False
        return current_user.role == "admin" or record.user_id == current_user.id

    def admin_required(f):
        @wraps(f)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role != "admin":
                log_audit("ADMIN_VIEW_ATTEMPT", "admin_panel", status="blocked", details="Non-admin tried to access admin route")
                flash("Admin access required. Unauthorized attempt logged.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_view

    @app.errorhandler(413)
    def file_too_large(_e):
        flash("File size exceeds the 5 MB limit.", "danger")
        return redirect(url_for("dashboard"))

    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role="admin").first():
            admin_user = User(
                name="System Admin",
                email="admin@studysync.local",
                password_hash=generate_password_hash("Admin@123"),
                role="admin",
                daily_study_limit_hours=6.0,
            )
            db.session.add(admin_user)
            db.session.commit()

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            limit_raw = request.form.get("daily_study_limit_hours") or "4.0"

            if not name or not email or not password:
                flash("Name, email, and password are required.", "danger")
                return render_template("register.html")

            if len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return render_template("register.html")

            try:
                daily_limit = float(limit_raw)
                if daily_limit <= 0 or daily_limit > 16:
                    raise ValueError()
            except ValueError:
                flash("Daily study limit must be between 0.5 and 16 hours.", "danger")
                return render_template("register.html")

            if User.query.filter_by(email=email).first():
                flash("Email is already registered.", "warning")
                return render_template("register.html")

            user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                role="student",
                daily_study_limit_hours=daily_limit,
            )
            db.session.add(user)
            db.session.commit()
            log_audit("USER_REGISTER", "user", user.id, status="allowed", details=f"Registered student {email}", actor_id=user.id)
            login_user(user)
            flash("Account created successfully!", "success")
            return redirect(url_for("dashboard"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            user = User.query.filter_by(email=email).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                log_audit("USER_LOGIN", "user", user.id, status="allowed", details=f"Logged in {email}", actor_id=user.id)
                flash("Welcome back!", "success")
                return redirect(url_for("dashboard"))

            log_audit("USER_LOGIN_FAILED", "user", None, status="blocked", details=f"Failed login for {email}")
            flash("Invalid email or password.", "danger")

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        uid = current_user.id
        logout_user()
        log_audit("USER_LOGOUT", "user", uid, status="allowed", details="User logged out", actor_id=uid)
        flash("Logged out.", "info")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        now = datetime.now()
        focus_cutoff = now + timedelta(hours=24)

        if current_user.role == "admin":
            courses = Course.query.order_by(Course.created_at.desc()).all()
            all_tasks = Task.query.order_by(Task.deadline.asc()).all()
            slots = StudySlot.query.order_by(StudySlot.date.asc(), StudySlot.start_time.asc()).all()
            all_resources = TaskResource.query.order_by(TaskResource.uploaded_at.desc()).all()
        else:
            courses = Course.query.filter_by(user_id=current_user.id).order_by(Course.created_at.desc()).all()
            all_tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.deadline.asc()).all()
            slots = StudySlot.query.filter_by(user_id=current_user.id).order_by(StudySlot.date.asc(), StudySlot.start_time.asc()).all()
            all_resources = TaskResource.query.filter_by(user_id=current_user.id).order_by(TaskResource.uploaded_at.desc()).all()

        urgent_tasks = [
            t for t in all_tasks
            if t.status != "completed" and t.deadline <= focus_cutoff
        ]

        course_filter = request.args.get("course_id", "")
        priority_filter = request.args.get("priority", "")
        status_filter = request.args.get("status", "")
        search_q = (request.args.get("q") or "").strip().lower()

        filtered_tasks = all_tasks
        if course_filter.isdigit():
            cid = int(course_filter)
            filtered_tasks = [t for t in filtered_tasks if t.course_id == cid]
        if priority_filter in ("high", "medium", "low"):
            filtered_tasks = [t for t in filtered_tasks if t.priority == priority_filter]
        if status_filter in ("pending", "in_progress", "completed"):
            filtered_tasks = [t for t in filtered_tasks if t.status == status_filter]
        if search_q:
            filtered_tasks = [
                t for t in filtered_tasks
                if search_q in t.title.lower() or (t.course and search_q in t.course.code.lower())
            ]

        note_task_filter = request.args.get("note_task_id", "")
        note_search_q = (request.args.get("note_q") or "").strip().lower()

        filtered_resources = all_resources
        if note_task_filter.isdigit():
            ntid = int(note_task_filter)
            filtered_resources = [r for r in filtered_resources if r.task_id == ntid]
        if note_search_q:
            filtered_resources = [
                r for r in filtered_resources
                if note_search_q in (r.note_title or "").lower()
                or note_search_q in (r.original_filename or "").lower()
                or (r.task and note_search_q in r.task.title.lower())
            ]

        for r in filtered_resources:
            ext = os.path.splitext(r.original_filename or "")[1].lower()
            r._ext = ext.lstrip(".").upper() if ext else "FILE"
            r._is_inline = ext in INLINE_VIEW_EXTENSIONS

        total_tasks = len(all_tasks)
        completed_tasks = sum(1 for t in all_tasks if t.status == "completed")
        completion_pct = round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0.0
        remaining_hours = round(sum(t.estimated_hours for t in all_tasks if t.status != "completed"), 2)

        completed_slot_hours = 0.0
        for s in slots:
            s._hours = duration_hours(s.start_time, s.end_time)
            if s.status == "completed":
                completed_slot_hours = round(completed_slot_hours + s._hours, 2)

        return render_template(
            "dashboard.html",
            courses=courses,
            tasks=filtered_tasks,
            all_tasks=all_tasks,
            urgent_tasks=urgent_tasks,
            slots=slots,
            resources=filtered_resources,
            total_resources_count=len(all_resources),
            now=now,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            completion_pct=completion_pct,
            remaining_hours=remaining_hours,
            completed_slot_hours=completed_slot_hours,
            course_filter=course_filter,
            priority_filter=priority_filter,
            status_filter=status_filter,
            search_q=search_q,
            note_task_filter=note_task_filter,
            note_search_q=note_search_q,
        )

    @app.route("/api/assistant", methods=["POST"])
    @login_required
    def assistant_chat():
        payload = request.get_json(silent=True) or {}
        message = (payload.get("message") or request.form.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "reply": "Please enter a question or calculation."}), 400
        reply = generate_assistant_reply(message)
        return jsonify({"ok": True, "reply": reply})

    @app.route("/courses/add", methods=["POST"])
    @login_required
    def add_course():
        code = (request.form.get("code") or "").strip().upper()
        title = (request.form.get("title") or "").strip()

        if not code or not title:
            flash("Course code and title are required.", "danger")
            return redirect(url_for("dashboard"))

        existing = Course.query.filter_by(user_id=current_user.id, code=code).first()
        if existing:
            flash(f"Course code '{code}' already exists in your list.", "warning")
            return redirect(url_for("dashboard"))

        course = Course(user_id=current_user.id, code=code, title=title)
        db.session.add(course)
        db.session.commit()
        log_audit("COURSE_CREATE", "course", course.id, status="allowed", details=f"Created {code}")
        flash(f"Course {code} added.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/tasks/add", methods=["POST"])
    @login_required
    def add_task():
        course_id_raw = request.form.get("course_id") or ""
        title = (request.form.get("title") or "").strip()
        task_type = request.form.get("task_type") or "assignment"
        deadline_raw = request.form.get("deadline") or ""
        est_raw = request.form.get("estimated_hours") or "2.0"
        priority = request.form.get("priority") or "medium"

        if not course_id_raw.isdigit() or not title or not deadline_raw:
            flash("Course, task title, and deadline are required.", "danger")
            return redirect(url_for("dashboard"))

        course = db.session.get(Course, int(course_id_raw))
        if not course:
            flash("Selected course not found.", "danger")
            return redirect(url_for("dashboard"))

        if not can_access_record(course):
            log_audit("UNAUTHORIZED_COURSE_TASK", "course", course.id, status="blocked", details="Tried adding task to another user's course")
            flash("Access denied: you do not own this course.", "danger")
            return redirect(url_for("dashboard"))

        try:
            deadline_dt = datetime.strptime(deadline_raw, "%Y-%m-%dT%H:%M")
            if deadline_dt <= datetime.now():
                flash("Deadline must be in the future.", "danger")
                return redirect(url_for("dashboard"))
        except ValueError:
            flash("Invalid deadline format.", "danger")
            return redirect(url_for("dashboard"))

        try:
            est_hours = float(est_raw)
            if est_hours <= 0 or est_hours > 100:
                raise ValueError()
        except ValueError:
            flash("Estimated hours must be between 0.25 and 100.", "danger")
            return redirect(url_for("dashboard"))

        dup = Task.query.filter(
            Task.user_id == course.user_id,
            Task.course_id == course.id,
            Task.title.ilike(title),
        ).first()
        if dup:
            flash("A task with this title already exists in this course.", "warning")
            return redirect(url_for("dashboard"))

        task = Task(
            user_id=course.user_id,
            course_id=course.id,
            title=title,
            task_type=task_type if task_type in ("exam", "assignment") else "assignment",
            deadline=deadline_dt,
            estimated_hours=round(est_hours, 2),
            priority=priority if priority in ("high", "medium", "low") else "medium",
            status="pending",
        )
        db.session.add(task)
        db.session.commit()
        log_audit("TASK_CREATE", "task", task.id, status="allowed", details=f"Created task '{title}'")
        flash("Task added successfully.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/tasks/<int:task_id>/status", methods=["POST"])
    @login_required
    def update_task_status(task_id):
        task = Task.query.get_or_404(task_id)
        if not can_access_record(task):
            log_audit("UNAUTHORIZED_TASK_UPDATE", "task", task.id, status="blocked", details=f"Blocked status change on task {task.id}")
            flash("403 Forbidden: You cannot modify another user's task. Incident logged.", "danger")
            return redirect(url_for("dashboard"))

        new_status = request.form.get("status") or ""
        if new_status not in ("pending", "in_progress", "completed"):
            flash("Invalid status transition.", "danger")
            return redirect(url_for("dashboard"))

        old_status = task.status
        if new_status not in ALLOWED_TASK_TRANSITIONS.get(old_status, set()):
            log_audit("INVALID_TASK_TRANSITION", "task", task.id, status="blocked", details=f"Rejected {old_status} -> {new_status}")
            flash(f"Transition from '{old_status}' to '{new_status}' is not allowed.", "danger")
            return redirect(url_for("dashboard"))

        if old_status == new_status:
            flash(f"Task is already marked as '{new_status}'.", "info")
            return redirect(url_for("dashboard"))

        task.status = new_status
        db.session.commit()

        if old_status == "completed" and new_status == "pending":
            log_audit("TASK_STATUS_REOPENED", "task", task.id, status="allowed", details=f"Reopened completed task: {old_status} -> {new_status}")
            flash("Completed task moved back to 'pending' — remember to re-schedule if needed.", "warning")
        else:
            log_audit("TASK_STATUS_CHANGE", "task", task.id, status="allowed", details=f"{old_status} -> {new_status}")
            flash("Task status updated.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/tasks/<int:task_id>/delete", methods=["POST"])
    @login_required
    def delete_task(task_id):
        task = Task.query.get_or_404(task_id)
        if not can_access_record(task):
            log_audit("UNAUTHORIZED_TASK_DELETE", "task", task.id, status="blocked", details=f"Blocked delete on task {task.id}")
            flash("403 Forbidden: You cannot delete another user's task. Incident logged.", "danger")
            return redirect(url_for("dashboard"))

        for res in task.resources:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], res.stored_filename)
            if os.path.exists(file_path):
                os.remove(file_path)

        title = task.title
        StudySlot.query.filter_by(task_id=task.id).delete()
        db.session.delete(task)
        db.session.commit()
        log_audit("TASK_DELETE", "task", task_id, status="allowed", details=f"Deleted task '{title}'")
        flash("Task deleted.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/resources/upload", methods=["POST"])
    @login_required
    def upload_resource():
        task_id_raw = request.form.get("task_id") or ""
        note_title_raw = (request.form.get("note_title") or "").strip()
        resource_file = request.files.get("resource_file") or request.files.get("pdf_file")

        if not task_id_raw.isdigit() or not resource_file or not resource_file.filename:
            flash("Please select a task and a PDF, image, or document file.", "danger")
            return redirect(url_for("dashboard"))

        task = db.session.get(Task, int(task_id_raw))
        if not task:
            flash("Selected task not found.", "danger")
            return redirect(url_for("dashboard"))

        if not can_access_record(task):
            log_audit("UNAUTHORIZED_RESOURCE_UPLOAD", "task", task.id, status="blocked", details="Tried uploading resource to another user's task")
            flash("403 Forbidden: You cannot attach resources to another user's task.", "danger")
            return redirect(url_for("dashboard"))

        clean_name = secure_filename(resource_file.filename)
        ext = os.path.splitext(clean_name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            flash("Allowed types: PDF (.pdf), Images (.png, .jpg, .jpeg, .webp), Docs (.docx, .doc, .txt).", "danger")
            return redirect(url_for("dashboard"))

        if ext == ".pdf":
            header = resource_file.stream.read(5)
            resource_file.stream.seek(0)
            if header != b"%PDF-":
                flash("Invalid PDF file signature. Please upload a valid PDF document.", "danger")
                return redirect(url_for("dashboard"))

        fallback_title = os.path.splitext(clean_name)[0].replace("_", " ").replace("-", " ").strip() or "Study Resource"
        final_note_title = (note_title_raw or fallback_title)[:150]

        stored_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_name)
        resource_file.save(save_path)

        size_kb = round(os.path.getsize(save_path) / 1024.0, 1)
        resource = TaskResource(
            task_id=task.id,
            user_id=task.user_id,
            note_title=final_note_title,
            original_filename=clean_name,
            stored_filename=stored_name,
            file_size_kb=size_kb,
        )
        db.session.add(resource)
        db.session.commit()
        log_audit("RESOURCE_UPLOAD", "task_resource", resource.id, status="allowed", details=f"Uploaded '{final_note_title}' ({clean_name}) for task #{task.id}")
        flash(f"Saved '{final_note_title}' ({clean_name}) for '{task.title}'.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/resources/<int:resource_id>/view")
    @login_required
    def view_resource(resource_id):
        res = TaskResource.query.get_or_404(resource_id)
        if not can_access_record(res):
            log_audit("UNAUTHORIZED_RESOURCE_VIEW", "task_resource", res.id, status="blocked", details=f"Blocked access to resource {res.id}")
            flash("403 Forbidden: You cannot access another user's study resource.", "danger")
            return redirect(url_for("dashboard"))

        file_path = os.path.join(app.config["UPLOAD_FOLDER"], res.stored_filename)
        if not os.path.exists(file_path):
            flash("Resource file not found on server storage.", "warning")
            return redirect(url_for("dashboard"))

        ext = os.path.splitext(res.original_filename or "")[1].lower()
        guessed_mime, _ = mimetypes.guess_type(res.original_filename)
        mime = "application/pdf" if ext == ".pdf" else (guessed_mime or "application/octet-stream")
        as_attach = ext not in INLINE_VIEW_EXTENSIONS

        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            res.stored_filename,
            mimetype=mime,
            as_attachment=as_attach,
            download_name=res.original_filename,
        )

    @app.route("/resources/<int:resource_id>/delete", methods=["POST"])
    @login_required
    def delete_resource(resource_id):
        res = TaskResource.query.get_or_404(resource_id)
        if not can_access_record(res):
            log_audit("UNAUTHORIZED_RESOURCE_DELETE", "task_resource", res.id, status="blocked", details=f"Blocked delete on resource {res.id}")
            flash("403 Forbidden: You cannot delete another user's study resource.", "danger")
            return redirect(url_for("dashboard"))

        file_path = os.path.join(app.config["UPLOAD_FOLDER"], res.stored_filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        label = res.note_title or res.original_filename
        db.session.delete(res)
        db.session.commit()
        log_audit("RESOURCE_DELETE", "task_resource", resource_id, status="allowed", details=f"Deleted resource '{label}'")
        flash("Study resource deleted.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/slots/add", methods=["POST"])
    @login_required
    def add_slot():
        date_raw = request.form.get("date") or ""
        start_raw = request.form.get("start_time") or ""
        end_raw = request.form.get("end_time") or ""
        task_id_raw = request.form.get("task_id") or ""

        try:
            target_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
            start_t = datetime.strptime(start_raw, "%H:%M").time()
            end_t = datetime.strptime(end_raw, "%H:%M").time()
        except ValueError:
            flash("Please provide a valid date, start time, and end time.", "danger")
            return redirect(url_for("dashboard"))

        task_id = None
        linked_task = None
        target_user = current_user
        if task_id_raw.isdigit():
            t = db.session.get(Task, int(task_id_raw))
            if t:
                if not can_access_record(t):
                    log_audit("UNAUTHORIZED_SLOT_TASK", "task", t.id, status="blocked", details="Tried scheduling slot for another user's task")
                    flash("403 Forbidden: Cannot link slot to another user's task.", "danger")
                    return redirect(url_for("dashboard"))
                task_id = t.id
                linked_task = t
                target_user = t.owner

        is_valid, err_msg, suggestion = validate_and_check_conflict(
            target_user, target_date, start_t, end_t, linked_task=linked_task
        )
        if not is_valid:
            log_audit("SLOT_CONFLICT_REJECTED", "study_slot", None, status="blocked", details=err_msg)
            msg = f"Cannot schedule slot: {err_msg}"
            if suggestion:
                msg += f" | {suggestion}"
            flash(msg, "warning")
            return redirect(url_for("dashboard"))

        slot = StudySlot(
            user_id=target_user.id,
            task_id=task_id,
            date=target_date,
            start_time=start_t,
            end_time=end_t,
            status="scheduled",
        )
        db.session.add(slot)
        db.session.commit()
        log_audit("SLOT_CREATE", "study_slot", slot.id, status="allowed", details=f"{target_date} {start_t}-{end_t}")
        flash("Study slot scheduled successfully!", "success")
        return redirect(url_for("dashboard"))

    @app.route("/slots/<int:slot_id>/status", methods=["POST"])
    @login_required
    def update_slot_status(slot_id):
        slot = StudySlot.query.get_or_404(slot_id)
        if not can_access_record(slot):
            log_audit("UNAUTHORIZED_SLOT_UPDATE", "study_slot", slot.id, status="blocked", details=f"Blocked status change on slot {slot.id}")
            flash("403 Forbidden: You cannot update another user's study slot.", "danger")
            return redirect(url_for("dashboard"))

        new_status = request.form.get("status") or ""
        if new_status not in ("scheduled", "completed", "cancelled"):
            flash("Invalid slot status.", "danger")
            return redirect(url_for("dashboard"))

        old_status = slot.status
        slot.status = new_status
        db.session.commit()
        log_audit("SLOT_STATUS_CHANGE", "study_slot", slot.id, status="allowed", details=f"{old_status} -> {new_status}")
        flash(f"Study slot marked as {new_status}.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/slots/<int:slot_id>/delete", methods=["POST"])
    @login_required
    def delete_slot(slot_id):
        slot = StudySlot.query.get_or_404(slot_id)
        if not can_access_record(slot):
            log_audit("UNAUTHORIZED_SLOT_DELETE", "study_slot", slot.id, status="blocked", details=f"Blocked delete on slot {slot.id}")
            flash("403 Forbidden: You cannot delete another user's study slot. Incident logged.", "danger")
            return redirect(url_for("dashboard"))

        db.session.delete(slot)
        db.session.commit()
        log_audit("SLOT_DELETE", "study_slot", slot_id, status="allowed", details=f"Deleted slot {slot_id}")
        flash("Study slot removed.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/auto-schedule", methods=["POST"])
    @login_required
    def run_auto_schedule():
        created, scheduled_summary, unscheduled_details = auto_schedule_tasks(current_user)
        db.session.commit()
        log_audit(
            "AUTO_SCHEDULE",
            "study_slot",
            None,
            status="allowed",
            details=f"Created {created} slots; partially/unscheduled: {len(unscheduled_details)}",
        )
        if created > 0:
            flash(
                f"Auto-scheduled {created} study slot(s) before deadlines: " + " ; ".join(scheduled_summary),
                "success",
            )
        else:
            flash("No new slots could be scheduled before deadlines.", "info")
        if unscheduled_details:
            flash(
                "Needs attention (deadline passed / tight free window / daily limit): " + " ; ".join(unscheduled_details),
                "warning",
            )
        return redirect(url_for("dashboard"))

    @app.route("/audit-logs")
    @login_required
    @admin_required
    def view_audit_logs():
        logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()
        return render_template("audit_logs.html", logs=logs)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)