from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")  # 'student' or 'admin'
    daily_study_limit_hours = db.Column(db.Float, nullable=False, default=4.0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    courses = db.relationship("Course", backref="owner", lazy=True, cascade="all, delete-orphan")
    tasks = db.relationship("Task", backref="owner", lazy=True, cascade="all, delete-orphan")
    study_slots = db.relationship("StudySlot", backref="owner", lazy=True, cascade="all, delete-orphan")
    resources = db.relationship("TaskResource", backref="owner", lazy=True, cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", backref="actor", lazy=True)


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    tasks = db.relationship("Task", backref="course", lazy=True, cascade="all, delete-orphan")


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    task_type = db.Column(db.String(20), nullable=False, default="assignment")  # 'exam' or 'assignment'
    deadline = db.Column(db.DateTime, nullable=False)
    estimated_hours = db.Column(db.Float, nullable=False, default=2.0)
    priority = db.Column(db.String(20), nullable=False, default="medium")  # 'high', 'medium', 'low'
    status = db.Column(db.String(20), nullable=False, default="pending")  # 'pending', 'in_progress', 'completed'
    created_at = db.Column(db.DateTime, default=datetime.now)

    study_slots = db.relationship("StudySlot", backref="task", lazy=True)
    resources = db.relationship("TaskResource", backref="task", lazy=True, cascade="all, delete-orphan")


class TaskResource(db.Model):
    __tablename__ = "task_resources"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note_title = db.Column(db.String(150), nullable=False, default="Study Note")
    original_filename = db.Column(db.String(200), nullable=False)
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    file_size_kb = db.Column(db.Float, nullable=False, default=0.0)
    uploaded_at = db.Column(db.DateTime, default=datetime.now)


class StudySlot(db.Model):
    __tablename__ = "study_slots"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="scheduled")  # 'scheduled', 'completed', 'cancelled'
    created_at = db.Column(db.DateTime, default=datetime.now)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="allowed")  # 'allowed' or 'blocked'
    details = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)