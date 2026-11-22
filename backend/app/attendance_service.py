from __future__ import annotations

import base64
import asyncio
import csv
import hashlib
import html
import io
import json
import os
import secrets
import smtplib
import tempfile
import time
import unicodedata
import uuid
import zipfile
from email.message import EmailMessage
from string import Template
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from dotenv import load_dotenv

PACKAGE_DATA = Path(__file__).resolve().parent / "attendance_data"
LEGACY_DATA = Path.home() / "Desktop" / "Nexus-Attendance" / "backend"
ROOT = Path(os.getenv("NEXUS_ATTENDANCE_DATA_DIR", str(LEGACY_DATA if LEGACY_DATA.exists() else PACKAGE_DATA))).expanduser()
ROOT.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "attendance.db"
PROFILE_PHOTO_DIR = ROOT / "profile_photos"
MODELS = ROOT / "models" if (ROOT / "models").exists() else PACKAGE_DATA / "models"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
SFACE = MODELS / "face_recognition_sface_2021dec.onnx"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
CAMERA_MODE_FILE = Path(tempfile.gettempdir()) / "nexus-attendance-camera-mode.json"
CAMERA_MODE_ACK_FILE = Path(tempfile.gettempdir()) / "nexus-attendance-camera-mode-ack.json"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 180_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split(":", 1)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 180_000)
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    surname: Mapped[str] = mapped_column(String(80))
    class_name: Mapped[str] = mapped_column(String(100), index=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True, nullable=True)
    credentials_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_photo_path: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pin_hash: Mapped[str] = mapped_column(String(160))
    must_change_password: Mapped[bool] = mapped_column(default=True)
    embeddings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Instructor(Base):
    __tablename__ = "instructors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(30), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InstructorSession(Base):
    __tablename__ = "instructor_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    instructor_id: Mapped[str] = mapped_column(ForeignKey("instructors.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentSession(Base):
    __tablename__ = "student_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClassGroup(Base):
    __tablename__ = "class_groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_name: Mapped[str] = mapped_column(String(100), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    late_after_seconds: Mapped[int] = mapped_column(Integer, default=30)
    absent_after_seconds: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(20), default="active")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_session_student"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    similarity: Mapped[float | None] = mapped_column(nullable=True)


class AttendanceReview(Base):
    __tablename__ = "attendance_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    previous_status: Mapped[str] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(80), default="Instructor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttendanceAudit(Base):
    __tablename__ = "attendance_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    previous_status: Mapped[str] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(Text, default="Please rescan me")
    claimed_status: Mapped[str] = mapped_column(String(20), default="present")
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Vision:
    def __init__(self) -> None:
        if not YUNET.exists() or not SFACE.exists():
            raise RuntimeError("Local face models are missing from backend/models")
        self.detector = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.82, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(SFACE), "")
        self.threshold = float(os.getenv("FACE_MATCH_THRESHOLD", "0.363"))
        self.margin = float(os.getenv("FACE_MATCH_MARGIN", "0.045"))
        self.review_floor = float(os.getenv("FACE_REVIEW_THRESHOLD", str(self.threshold - 0.06)))

    def image(self, data_url: str) -> np.ndarray:
        try:
            raw = data_url.split(",", 1)[1] if "," in data_url else data_url
            arr = np.frombuffer(base64.b64decode(raw), np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("invalid image")
            return frame
        except Exception as exc:
            raise HTTPException(400, "Could not read the camera image") from exc

    def detect(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        return faces if faces is not None else np.empty((0, 15), dtype=np.float32)

    def feature(self, frame: np.ndarray, face: np.ndarray) -> np.ndarray:
        aligned = self.recognizer.alignCrop(frame, face[:14].reshape(1, 14))
        return self.recognizer.feature(aligned).astype(np.float32).reshape(-1)

    def enroll_sample(self, data_url: str) -> tuple[list[float], dict[str, Any]]:
        frame = self.image(data_url)
        faces = self.detect(frame)
        if len(faces) != 1:
            raise HTTPException(422, "Show exactly one face in the camera")
        face = faces[0]
        width, height = float(face[2]), float(face[3])
        if min(width, height) < 80:
            raise HTTPException(422, "Move a little closer so your face is clear")
        feature = self.feature(frame, face)
        norm = float(np.linalg.norm(feature)) or 1.0
        feature = feature / norm
        landmarks = face[4:14].reshape(5, 2)
        eye_span = max(1.0, float(np.linalg.norm(landmarks[0] - landmarks[1])))
        eye_mid = (landmarks[0] + landmarks[1]) / 2
        yaw_hint = float((landmarks[2][0] - eye_mid[0]) / eye_span)
        pitch_hint = float((landmarks[2][1] - eye_mid[1]) / max(height, 1.0))
        return feature.tolist(), {"face_detected": True, "face_size": [round(width), round(height)], "image_size": [frame.shape[1], frame.shape[0]],
                                 "pose_hint": [round(yaw_hint, 3), round(pitch_hint, 3)]}

    def pose_check(self, data_url: str, view: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
        frame = self.image(data_url)
        faces = self.detect(frame)
        if len(faces) != 1:
            return {"ready": False, "reason": "Keep exactly one face in view"}
        face = faces[0]
        width, height = float(face[2]), float(face[3])
        if min(width, height) < 80:
            return {"ready": False, "reason": "Move a little closer so your face fills more of the guide"}
        landmarks = face[4:14].reshape(5, 2)
        eye_span = max(1.0, float(np.linalg.norm(landmarks[0] - landmarks[1])))
        eye_mid = (landmarks[0] + landmarks[1]) / 2
        yaw = float((landmarks[2][0] - eye_mid[0]) / eye_span)
        pitch = float((landmarks[2][1] - eye_mid[1]) / max(height, 1.0))
        prior = {sample.get("view"): sample.get("pose_hint") for sample in samples if sample.get("pose_hint")}
        front = prior.get("front")
        front_yaw = float(front[0]) if front else 0.0
        front_pitch = float(front[1]) if front else 0.0
        target = (yaw, pitch)
        ready = False
        reason = "Follow the pose prompt"
        if view == "front":
            ready = abs(yaw) < 0.18
            reason = "Face the camera and level your head" if not ready else "Hold still"
        elif view == "left_30":
            ready = abs(yaw - front_yaw) > 0.055
            reason = "Turn your head a little to your left" if not ready else "Hold still"
            if ready:
                target = (yaw, pitch)
        elif view in ("left_60", "right_60"):
            base = prior.get("left_30") if view == "left_60" else prior.get("right_30")
            if base:
                base_delta = float(base[0]) - front_yaw
                current_delta = yaw - front_yaw
                ready = current_delta * base_delta > 0 and abs(current_delta) > max(0.11, abs(base_delta) * 1.12)
            reason = "Turn a little farther in the same direction" if not ready else "Hold still"
        elif view in ("right_30", "right_60"):
            opposite = prior.get("left_30") or prior.get("left_60")
            if opposite:
                opposite_delta = float(opposite[0]) - front_yaw
                current_delta = yaw - front_yaw
                ready = current_delta * opposite_delta < 0 and abs(current_delta) > (0.11 if view == "right_60" else 0.055)
                if view == "right_60":
                    base = prior.get("right_30")
                    if base:
                        ready = ready and abs(current_delta) > abs(float(base[0]) - front_yaw) * 1.12
            reason = "Turn a little to the opposite side" if not ready else "Hold still"
        elif view == "up":
            ready = bool(front and pitch > front_pitch + 0.012)
            reason = "Raise your chin slightly" if not ready else "Hold still"
        elif view == "down":
            ready = bool(front and pitch < front_pitch - 0.012)
            reason = "Lower your chin slightly" if not ready else "Hold still"
        return {"ready": ready, "reason": reason, "pose_hint": [round(yaw, 3), round(pitch, 3)],
                "face_size": [round(width), round(height)]}

    def scan(self, data_url: str, students: list[Student], target_student_id: str | None = None) -> dict[str, Any]:
        frame = self.image(data_url)
        faces = self.detect(frame)
        if not len(faces):
            return {"faces": 0, "matches": [], "message": "No face detected"}
        if target_student_id:
            students = [s for s in students if s.id == target_student_id]
        matches: list[dict[str, Any]] = []
        for face in faces:
            face_width, face_height = float(face[2]), float(face[3])
            if face_width < 48 or face_height < 48:
                continue
            feature = self.feature(frame, face)
            feature = feature / (np.linalg.norm(feature) or 1.0)
            scores: list[tuple[float, Student]] = []
            for student in students:
                samples = student.embeddings or []
                sample_scores = []
                for sample in samples:
                    vector = np.asarray(sample.get("vector", []), dtype=np.float32)
                    if vector.shape == feature.shape:
                        vector = vector / (np.linalg.norm(vector) or 1.0)
                        sample_scores.append(float(np.dot(feature, vector)))
                if sample_scores:
                    scores.append((max(sample_scores), student))
            scores.sort(key=lambda item: item[0], reverse=True)
            if not scores:
                continue
            best_score, best = scores[0]
            second_score = scores[1][0] if len(scores) > 1 else -1.0
            face_quality_sufficient = min(face_width, face_height) >= 80
            accepted = face_quality_sufficient and best_score >= self.threshold and (len(scores) == 1 or best_score - second_score >= self.margin)
            needs_review = best_score >= self.review_floor and (not accepted or not face_quality_sufficient)
            matches.append({"student_id": best.id if accepted or needs_review else None, "student_code": best.student_code if accepted or needs_review else None,
                            "first_name": best.first_name if accepted or needs_review else None, "surname": best.surname if accepted or needs_review else None,
                            "similarity": round(best_score, 4), "ambiguous": needs_review,
                            "needs_review": needs_review, "face_quality_sufficient": face_quality_sufficient,
                            "face_size": [round(face_width), round(face_height)],
                            "box": [round(float(v)) for v in face[:4]]})
        return {"faces": int(len(faces)), "matches": matches, "message": "Face detected" if matches else "No enrolled identity matched"}


vision: Vision | None = None
app = FastAPI(title="NEXUS Attendance", version="0.1.0", description="Classroom attendance demo API")
app.add_middleware(CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()],
    allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):3000",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type"], allow_credentials=True)


class StudentCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    surname: str = Field(min_length=1, max_length=80)
    class_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=5, max_length=254)

class ClassGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class SampleCreate(BaseModel):
    image: str
    view: str = Field(min_length=1, max_length=30)

class PoseCheck(BaseModel):
    image: str
    view: str = Field(min_length=1, max_length=30)

class SessionCreate(BaseModel):
    class_name: str = Field(min_length=1, max_length=100)
    late_after_seconds: int = Field(default=30, ge=5, le=600)
    absent_after_seconds: int = Field(default=60, ge=10, le=1200)

class ScanCreate(BaseModel):
    image: str
    target_student_id: str | None = None

class NoticeCreate(BaseModel):
    student_code: str
    password: str = Field(min_length=1, max_length=128)
    claim: str = Field(pattern="^(present|late)$")
    note: str = Field(default="I am in class. Please rescan me.", max_length=500)

class FirstPasswordChange(BaseModel):
    student_code: str
    temporary_pin: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

class PhoneLogin(BaseModel):
    student_code: str
    password: str = Field(min_length=1, max_length=128)
    mobile_session: bool = False

class StudentPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

class StudentPhotoUpload(BaseModel):
    image_data: str = Field(min_length=32, max_length=7_000_000)

class StudentNoticeSession(BaseModel):
    claim: str = Field(pattern="^(present|late)$")
    note: str = Field(default="I am in class. Please rescan me.", max_length=500)

class AttendanceReviewCreate(BaseModel):
    status: str = Field(pattern="^(present|late|absent)$")
    reason: str = Field(min_length=3, max_length=500)

class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)

class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=128)

class InstructorLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)

class CameraModeUpdate(BaseModel):
    mode: str = Field(pattern="^(attendance|surveillance)$")


def make_student_code(first_name: str, surname: str) -> str:
    def name_part(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        letters = "".join(char for char in normalized if char.isalpha() and not unicodedata.combining(char))
        if not any(char.isascii() for char in letters):
            letters = "".join(char for char in value if char.isalpha())
        return letters[:2].upper().ljust(2, "X")

    initials = f"{name_part(first_name)}{name_part(surname)}"
    return f"ST-{datetime.now().year}-{initials}"


def make_temporary_pin() -> str:
    return f"{secrets.randbelow(100_000_000):08d}"


def valid_password(password: str) -> bool:
    return (len(password) >= 12 and any(c.islower() for c in password) and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password) and any(not c.isalnum() for c in password))


def integrated_student_url(value: str) -> str:
    """Keep legacy email links working after Attendance moved under /attendance."""
    if value.endswith("/student/reset") and "/attendance/student/reset" not in value:
        return value[:-len("/student/reset")] + "/attendance/student/reset"
    if value.endswith("/student") and "/attendance/student" not in value:
        return value[:-len("/student")] + "/attendance/student"
    return value


def send_credentials_email(email: str, first_name: str, student_code: str, temporary_pin: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Your NEXUS student phone sign-in"
    message["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")).strip()
    message["To"] = email
    login_url = integrated_student_url(os.getenv("STUDENT_LOGIN_URL", "").strip())
    values = {"first_name": first_name, "student_code": student_code, "temporary_pin": temporary_pin,
              "login_url": login_url or "Use the student phone page link shared by your instructor.",
              "login_section": (f'<a class="button" href="{html.escape(login_url, quote=True)}">Open student sign-in</a>'
                                if login_url.startswith(("https://", "http://")) else "")}
    templates = ROOT / "templates"
    message.set_content(Template((templates / "student_credentials.txt").read_text(encoding="utf-8")).substitute(values))
    message.add_alternative(Template((templates / "student_credentials.html").read_text(encoding="utf-8")).substitute(
        {key: html.escape(value) if key != "login_section" else value for key, value in values.items()}), subtype="html")
    deliver_email(message)


def deliver_email(message: EmailMessage) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user).strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    if not host or not sender or not user or not password:
        raise RuntimeError("Email is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM in backend/.env")
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes"):
            smtp.starttls()
            smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(message)


def send_password_reset_email(email: str, first_name: str, reset_token: str) -> None:
    reset_base = integrated_student_url(os.getenv("STUDENT_RESET_URL", "").strip())
    if not reset_base:
        login_url = integrated_student_url(os.getenv("STUDENT_LOGIN_URL", "").strip())
        reset_base = login_url[:-len("/attendance/student")] + "/attendance/student/reset" if login_url.endswith("/attendance/student") else login_url.rstrip("/") + "/reset"
    if not reset_base.startswith(("https://", "http://")):
        raise RuntimeError("Set STUDENT_RESET_URL or STUDENT_LOGIN_URL in backend/.env")
    reset_url = f"{reset_base}{'&' if '?' in reset_base else '?'}{urlencode({'token': reset_token})}"
    values = {"first_name": first_name, "reset_url": reset_url}
    templates = ROOT / "templates"
    message = EmailMessage()
    message["Subject"] = "Reset your NEXUS student password"
    message["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")).strip()
    message["To"] = email
    message.set_content(Template((templates / "password_reset.txt").read_text(encoding="utf-8")).substitute(values))
    message.add_alternative(Template((templates / "password_reset.html").read_text(encoding="utf-8")).substitute(
        {"first_name": html.escape(first_name), "reset_url": html.escape(reset_url, quote=True)}), subtype="html")
    deliver_email(message)


def need_vision() -> Vision:
    global vision
    if vision is None:
        try:
            vision = Vision()
        except Exception as exc:
            raise HTTPException(503, f"Face recognition is unavailable: {exc}") from exc
    return vision


async def get_db():
    async with SessionLocal() as db:
        yield db


INSTRUCTOR_COOKIE = "nexus_instructor_session"


async def require_instructor(request: Request, db: AsyncSession = Depends(get_db)) -> Instructor:
    raw_token = request.cookies.get(INSTRUCTOR_COOKIE)
    if not raw_token:
        raise HTTPException(401, "Instructor sign-in required")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    session_result = await db.execute(select(InstructorSession).where(InstructorSession.token_hash == token_hash))
    login_session = session_result.scalar_one_or_none()
    if not login_session or as_utc(login_session.expires_at) <= utcnow():
        raise HTTPException(401, "Instructor session expired. Sign in again.")
    instructor_result = await db.execute(select(Instructor).where(Instructor.id == login_session.instructor_id))
    instructor = instructor_result.scalar_one_or_none()
    if not instructor or instructor.role not in {"instructor", "admin"}:
        raise HTTPException(403, "This account does not have instructor access")
    return instructor


async def require_student(request: Request, db: AsyncSession = Depends(get_db)) -> Student:
    authorization = request.headers.get("authorization", "")
    scheme, _, raw_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not raw_token:
        raise HTTPException(401, "Student sign-in required")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    session_result = await db.execute(select(StudentSession).where(StudentSession.token_hash == token_hash))
    login_session = session_result.scalar_one_or_none()
    if not login_session or as_utc(login_session.expires_at) <= utcnow():
        raise HTTPException(401, "Student session expired. Sign in again.")
    student_result = await db.execute(select(Student).where(Student.id == login_session.student_id))
    student = student_result.scalar_one_or_none()
    if not student or student.must_change_password:
        raise HTTPException(401, "Student sign-in required")
    return student


def elapsed_seconds(session: AttendanceSession, now: datetime | None = None) -> float:
    return max(0.0, (as_utc(now or utcnow()) - as_utc(session.started_at)).total_seconds())


def audit_status_change(db: AsyncSession, session_id: str, student_id: str, previous_status: str,
                        new_status: str, actor: str, reason: str, changed_at: datetime | None = None) -> None:
    db.add(AttendanceAudit(session_id=session_id, student_id=student_id, previous_status=previous_status,
                           new_status=new_status, actor=actor, reason=reason, created_at=changed_at or utcnow()))


async def get_open_request(db: AsyncSession, session_id: str, student_id: str) -> CorrectionRequest | None:
    result = await db.execute(select(CorrectionRequest).where(CorrectionRequest.session_id == session_id,
        CorrectionRequest.student_id == student_id, CorrectionRequest.status == "open").order_by(CorrectionRequest.created_at.desc()))
    return result.scalars().first()


async def refresh_records(db: AsyncSession, session: AttendanceSession) -> None:
    now = utcnow(); elapsed = elapsed_seconds(session, now)
    result = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id))
    attendance_rows = list(result.scalars())
    for record in attendance_rows:
        if record.status == "present" or record.source in ("automatic face match", "phone notice + targeted face rescan", "instructor review", "uncertain face match"):
            continue
        old_status = record.status
        if elapsed >= session.absent_after_seconds:
            new_status = "absent"
            reason = f"The {session.absent_after_seconds}-second attendance window elapsed without a confirmed face match."
        elif elapsed >= session.late_after_seconds:
            new_status = "late"
            reason = f"The {session.late_after_seconds}-second on-time window elapsed without a confirmed face match."
        else:
            continue
        if new_status != old_status:
            record.status = new_status
            record.source = "time-based attendance rule"
            audit_status_change(db, session.id, record.student_id, old_status, new_status,
                                "Automatic time rule", reason, now)
    pending_result = await db.execute(select(CorrectionRequest).where(CorrectionRequest.session_id == session.id, CorrectionRequest.status == "open"))
    for request in pending_result.scalars():
        if (as_utc(now) - as_utc(request.created_at)).total_seconds() >= 25:
            request.status = "not_found"; request.resolved_at = now
    all_seen = bool(attendance_rows) and all(
        record.status == "present" or record.source in ("automatic face match", "phone notice + targeted face rescan")
        for record in attendance_rows
    )
    if elapsed >= session.absent_after_seconds or all_seen:
        session.status = "completed"
    await db.commit()


def student_json(student: Student, record: AttendanceRecord | None = None) -> dict[str, Any]:
    samples = student.embeddings or []
    views = [sample.get("view") for sample in samples]
    required_views = {"front", "left_30", "left_60", "right_30", "right_60", "up", "down"}
    return {"id": student.id, "student_code": student.student_code, "first_name": student.first_name,
            "surname": student.surname, "class_name": student.class_name, "email": student.email,
            "created_at": as_utc(student.created_at).isoformat(), "sample_count": len(samples),
            "profile_photo_available": bool(student.profile_photo_path),
            "credentials_email_sent": student.credentials_sent_at is not None,
            "enrolled": student.credentials_sent_at is not None and required_views.issubset(set(views)), "views": views,
            "pose_views": [sample.get("view") for sample in samples if sample.get("pose_hint")],
            "attendance": record.status if record else "not started", "marked_at": record.marked_at.isoformat() if record and record.marked_at else None,
            "source": record.source if record else None, "similarity": record.similarity if record else None}


def request_json(req: CorrectionRequest, student: Student) -> dict[str, Any]:
    return {"id": req.id, "student_id": student.id, "student_code": student.student_code,
            "first_name": student.first_name, "surname": student.surname, "claimed_status": req.claimed_status,
            "note": req.note, "status": req.status, "created_at": as_utc(req.created_at).isoformat()}


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        tables = await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='students'")
        if tables.first():
            columns = await conn.exec_driver_sql("PRAGMA table_info(students)")
            existing_columns = {row[1] for row in columns.fetchall()}
            if "email" not in existing_columns:
                await conn.exec_driver_sql("ALTER TABLE students ADD COLUMN email VARCHAR(254)")
            if "must_change_password" not in existing_columns:
                await conn.exec_driver_sql("ALTER TABLE students ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 1")
            if "credentials_sent_at" not in existing_columns:
                await conn.exec_driver_sql("ALTER TABLE students ADD COLUMN credentials_sent_at DATETIME")
                # Existing accounts were committed only after the SMTP send succeeded.
                await conn.exec_driver_sql("UPDATE students SET credentials_sent_at = created_at WHERE email IS NOT NULL")
            if "profile_photo_path" not in existing_columns:
                await conn.exec_driver_sql("ALTER TABLE students ADD COLUMN profile_photo_path VARCHAR(120)")
        await conn.run_sync(Base.metadata.create_all)
    bootstrap_username = os.getenv("INSTRUCTOR_USERNAME", "").strip().lower()
    bootstrap_password = os.getenv("INSTRUCTOR_PASSWORD", "")
    async with SessionLocal() as db:
        if bootstrap_username and valid_password(bootstrap_password):
            admin_result = await db.execute(select(Instructor).where(Instructor.role == "admin").order_by(Instructor.created_at).limit(1))
            bootstrap_admin = admin_result.scalars().first()
            if bootstrap_admin is None:
                existing_result = await db.execute(select(Instructor).where(Instructor.username == bootstrap_username))
                bootstrap_admin = existing_result.scalar_one_or_none()
                if bootstrap_admin:
                    bootstrap_admin.role = "admin"
                else:
                    bootstrap_admin = Instructor(username=bootstrap_username, password_hash=hash_pin(bootstrap_password), role="admin")
                    db.add(bootstrap_admin)
                print("[NEXUS Attendance] Initial instructor account created from backend/.env")
            changed = bootstrap_admin.username != bootstrap_username or not verify_pin(bootstrap_password, bootstrap_admin.password_hash)
            if changed:
                username_owner = await db.execute(select(Instructor.id).where(
                    Instructor.username == bootstrap_username, Instructor.id != bootstrap_admin.id))
                if username_owner.scalar_one_or_none():
                    print("[NEXUS Attendance] Configured instructor username is already assigned to another account")
                else:
                    bootstrap_admin.username = bootstrap_username
                    bootstrap_admin.password_hash = hash_pin(bootstrap_password)
                    old_sessions = await db.execute(select(InstructorSession).where(InstructorSession.instructor_id == bootstrap_admin.id))
                    for old_session in old_sessions.scalars():
                        await db.delete(old_session)
                    await db.commit()
                    print("[NEXUS Attendance] Bootstrap instructor credentials synchronized from backend/.env")
            elif db.new or db.dirty:
                await db.commit()
        elif not await db.scalar(select(Instructor.id).limit(1)):
            print("[NEXUS Attendance] Instructor sign-in not configured. Set INSTRUCTOR_USERNAME and a strong INSTRUCTOR_PASSWORD in backend/.env")
    try:
        need_vision()
        print("[NEXUS Attendance] YuNet and SFace loaded for local face processing")
    except Exception as exc:
        print(f"[NEXUS Attendance] Recognition model will be unavailable until repaired: {exc}")


@app.get("/api/auth/status")
async def instructor_auth_status(db: AsyncSession = Depends(get_db)):
    configured = await db.scalar(select(Instructor.id).limit(1)) is not None
    return {"configured": configured}


@app.get("/api/auth/me")
async def instructor_me(instructor: Instructor = Depends(require_instructor)):
    return {"authenticated": True, "username": instructor.username, "role": instructor.role}


@app.post("/api/auth/login")
async def instructor_login(body: InstructorLogin, response: Response, db: AsyncSession = Depends(get_db)):
    instructor_result = await db.execute(select(Instructor).where(Instructor.username == body.username.strip().lower()))
    instructor = instructor_result.scalar_one_or_none()
    if not instructor:
        raise HTTPException(401, "Username or password is incorrect")
    if not verify_pin(body.password, instructor.password_hash):
        raise HTTPException(401, "Username or password is incorrect")
    token = secrets.token_urlsafe(48)
    lifetime = max(1, min(24, int(os.getenv("INSTRUCTOR_SESSION_HOURS", "12"))))
    db.add(InstructorSession(instructor_id=instructor.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             expires_at=utcnow() + timedelta(hours=lifetime)))
    await db.commit()
    response.set_cookie(INSTRUCTOR_COOKIE, token, max_age=lifetime * 3600, httponly=True,
                        secure=os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
                        samesite="lax", path="/")
    return {"authenticated": True, "username": instructor.username, "role": instructor.role}


@app.post("/api/auth/logout")
async def instructor_logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(INSTRUCTOR_COOKIE)
    if raw_token:
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await db.execute(select(InstructorSession).where(InstructorSession.token_hash == digest))
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()
    response.delete_cookie(INSTRUCTOR_COOKIE, path="/", httponly=True, samesite="lax",
                           secure=os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"})
    return {"logged_out": True}


@app.get("/api/health")
async def health():
    try:
        model_state = "ready" if need_vision() else "unavailable"
    except HTTPException as exc:
        model_state = "unavailable"
        reason = str(exc.detail)
    else:
        reason = None
    return {"status": "ok", "recognition": model_state, "reason": reason}


@app.post("/api/camera-mode", dependencies=[Depends(require_instructor)])
async def update_camera_mode(body: CameraModeUpdate):
    """Give the shared webcam to Attendance while an authenticated instructor module is open."""
    requested_at = time.time()
    temp_mode_file = CAMERA_MODE_FILE.with_name(f"{CAMERA_MODE_FILE.stem}.{uuid.uuid4().hex}.tmp")
    temp_mode_file.write_text(json.dumps({"mode": body.mode, "updated_at": requested_at}), encoding="utf-8")
    try:
        os.replace(temp_mode_file, CAMERA_MODE_FILE)
    finally:
        temp_mode_file.unlink(missing_ok=True)
    camera_released = False
    if body.mode == "attendance":
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                ack = json.loads(CAMERA_MODE_ACK_FILE.read_text(encoding="utf-8"))
                if ack.get("mode") == "attendance" and float(ack.get("updated_at", 0)) >= requested_at:
                    camera_released = True
                    break
            except (OSError, ValueError, TypeError):
                pass
            await asyncio.sleep(0.1)
    return {"mode": body.mode, "camera_released": camera_released, "updated_at": time.time()}


@app.get("/api/students", dependencies=[Depends(require_instructor)])
async def list_students(class_name: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Student).order_by(Student.surname, Student.first_name)
    if class_name:
        query = query.where(Student.class_name == class_name)
    result = await db.execute(query)
    return [student_json(student) for student in result.scalars()]


@app.get("/api/students/{student_id}/profile-photo", dependencies=[Depends(require_instructor)])
async def get_instructor_student_profile_photo(student_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")
    if not student.profile_photo_path:
        return {"image_data": None}
    photo_path = PROFILE_PHOTO_DIR / f"{student.id}.jpg"
    if not photo_path.is_file():
        return {"image_data": None}
    image_data = base64.b64encode(photo_path.read_bytes()).decode("ascii")
    return {"image_data": f"data:image/jpeg;base64,{image_data}"}


@app.get("/api/classes", dependencies=[Depends(require_instructor)])
async def list_class_groups(db: AsyncSession = Depends(get_db)):
    saved_result = await db.execute(select(ClassGroup.name).order_by(ClassGroup.name))
    student_result = await db.execute(select(Student.class_name).distinct().order_by(Student.class_name))
    names = [name for (name,) in saved_result.all()] + [name for (name,) in student_result.all()]
    unique: dict[str, str] = {}
    for name in names:
        clean = name.strip()
        if clean:
            unique.setdefault(clean.casefold(), clean)
    return sorted(unique.values(), key=str.casefold)


async def ensure_class_group(db: AsyncSession, name: str) -> None:
    saved_result = await db.execute(select(ClassGroup.name))
    saved_names = [value for (value,) in saved_result.all()]
    if not any(value.strip().casefold() == name.strip().casefold() for value in saved_names):
        db.add(ClassGroup(name=name.strip()))


@app.post("/api/classes", dependencies=[Depends(require_instructor)])
async def create_class_group(body: ClassGroupCreate, db: AsyncSession = Depends(get_db)):
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Group name must contain at least two characters")
    existing_saved = await db.execute(select(ClassGroup.name))
    existing_students = await db.execute(select(Student.class_name).distinct())
    names = [value for (value,) in existing_saved.all()] + [value for (value,) in existing_students.all()]
    if any(value.strip().casefold() == name.casefold() for value in names):
        raise HTTPException(409, "That class/group already exists")
    group = ClassGroup(name=name)
    db.add(group)
    await db.commit()
    return {"name": group.name, "created": True}


@app.post("/api/students", dependencies=[Depends(require_instructor)])
async def create_student(body: StudentCreate, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Enter a valid student email address")
    exists = await db.execute(select(Student).where(Student.email == email))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "That email address already has a student account")
    base_code = make_student_code(body.first_name.strip(), body.surname.strip())
    code = base_code
    suffix = 2
    while (await db.execute(select(Student.id).where(Student.student_code == code))).first():
        code = f"{base_code}-{suffix:02d}"
        suffix += 1
    temporary_pin = make_temporary_pin()
    student = Student(student_code=code, first_name=body.first_name.strip(), surname=body.surname.strip(),
                      class_name=body.class_name.strip(), email=email, pin_hash=hash_pin(temporary_pin),
                      must_change_password=True, embeddings=[])
    db.add(student)
    await db.flush()
    await ensure_class_group(db, student.class_name)
    try:
        await asyncio.to_thread(send_credentials_email, email, student.first_name, code, temporary_pin)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, f"Student account was not created because the credential email could not be sent: {exc}") from exc
    student.credentials_sent_at = utcnow()
    await db.commit(); await db.refresh(student)
    return student_json(student)


@app.post("/api/students/{student_id}/samples", dependencies=[Depends(require_instructor)])
async def add_face_sample(student_id: str, body: SampleCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Student).where(Student.id == student_id)); student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")
    samples = list(student.embeddings or [])
    existing = next((i for i, sample in enumerate(samples) if sample.get("view") == body.view), None)
    if existing is not None and samples[existing].get("pose_hint"):
        raise HTTPException(409, f"The {body.view} view is already captured")
    vector, quality = need_vision().enroll_sample(body.image)
    new_sample = {"view": body.view, "vector": vector, "pose_hint": quality["pose_hint"], "created_at": utcnow().isoformat()}
    if existing is None:
        samples.append(new_sample)
    else:
        samples[existing] = new_sample
    student.embeddings = samples
    await db.commit()
    return {"student": student_json(student), "quality": quality}


@app.post("/api/students/{student_id}/pose-check", dependencies=[Depends(require_instructor)])
async def check_face_pose(student_id: str, body: PoseCheck, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")
    return need_vision().pose_check(body.image, body.view, student.embeddings or [])


@app.delete("/api/students/{student_id}", dependencies=[Depends(require_instructor)])
async def delete_student(student_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Student).where(Student.id == student_id)); student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")
    (PROFILE_PHOTO_DIR / f"{student.id}.jpg").unlink(missing_ok=True)
    for model in (CorrectionRequest, AttendanceReview, AttendanceAudit, PasswordReset, StudentSession, AttendanceRecord):
        rows = await db.execute(select(model).where(model.student_id == student_id))
        for row in rows.scalars():
            await db.delete(row)
    await db.delete(student); await db.commit()
    return {"deleted": True}


@app.delete("/api/students/{student_id}/biometric-data", dependencies=[Depends(require_instructor)])
async def delete_student_biometric_data(student_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")
    (PROFILE_PHOTO_DIR / f"{student.id}.jpg").unlink(missing_ok=True)
    student.profile_photo_path = None
    student.embeddings = []
    await db.commit()
    return {"deleted": True, "profile_photo": True, "face_templates": True,
            "attendance_history_retained": True}


@app.post("/api/sessions", dependencies=[Depends(require_instructor)])
async def create_session(body: SessionCreate, db: AsyncSession = Depends(get_db)):
    if body.absent_after_seconds <= body.late_after_seconds:
        raise HTTPException(422, "Absent cutoff must be after the late cutoff")
    students_result = await db.execute(select(Student).where(Student.class_name == body.class_name.strip()))
    required_views = {"front", "left_30", "left_60", "right_30", "right_60", "up", "down"}
    students = [s for s in students_result.scalars()
                if s.credentials_sent_at is not None
                and required_views.issubset({sample.get("view") for sample in (s.embeddings or [])})]
    if not students:
        raise HTTPException(409, "At least one student needs a confirmed credential email and all seven face views before attendance can start")
    old_result = await db.execute(select(AttendanceSession).where(AttendanceSession.class_name == body.class_name.strip(), AttendanceSession.status == "active"))
    old = old_result.scalars().first()
    if old:
        raise HTTPException(409, "This class already has an active attendance session")
    session = AttendanceSession(class_name=body.class_name.strip(), late_after_seconds=body.late_after_seconds,
                               absent_after_seconds=body.absent_after_seconds, status="active", started_at=utcnow())
    db.add(session); await db.flush()
    for student in students:
        db.add(AttendanceRecord(session_id=session.id, student_id=student.id, status="waiting"))
        audit_status_change(db, session.id, student.id, "not enrolled", "waiting", "Attendance session",
                            "Student added to this class session's attendance roster.", session.started_at)
    await db.commit(); await db.refresh(session)
    return {"id": session.id, "class_name": session.class_name, "started_at": as_utc(session.started_at).isoformat(),
            "late_after_seconds": session.late_after_seconds, "absent_after_seconds": session.absent_after_seconds, "status": session.status}


@app.get("/api/sessions/latest", dependencies=[Depends(require_instructor)])
async def latest_session(class_name: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(AttendanceSession).order_by(AttendanceSession.started_at.desc())
    if class_name:
        query = query.where(AttendanceSession.class_name == class_name)
    result = await db.execute(query.limit(1)); session = result.scalars().first()
    if not session:
        return None
    return await session_view(db, session)


@app.get("/api/sessions/history", dependencies=[Depends(require_instructor)])
async def session_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AttendanceSession).order_by(AttendanceSession.started_at.desc()).limit(200))
    return [{"id": session.id, "class_name": session.class_name,
             "started_at": as_utc(session.started_at).isoformat(), "status": session.status,
             "late_after_seconds": session.late_after_seconds,
             "absent_after_seconds": session.absent_after_seconds}
            for session in result.scalars()]


async def session_view(db: AsyncSession, session: AttendanceSession) -> dict[str, Any]:
    await refresh_records(db, session)
    records_result = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id))
    records = {r.student_id: r for r in records_result.scalars()}
    students_result = await db.execute(select(Student).where(Student.id.in_(list(records.keys()))).order_by(Student.surname))
    students = list(students_result.scalars())
    req_result = await db.execute(select(CorrectionRequest).where(CorrectionRequest.session_id == session.id,
        CorrectionRequest.status == "open").order_by(CorrectionRequest.created_at))
    requests: list[dict[str, Any]] = []
    for req in req_result.scalars():
        stu = next((s for s in students if s.id == req.student_id), None)
        if stu:
            requests.append(request_json(req, stu))
    review_result = await db.execute(select(AttendanceReview, Student).join(Student, Student.id == AttendanceReview.student_id)
        .where(AttendanceReview.session_id == session.id).order_by(AttendanceReview.created_at.desc()))
    reviews = [{"id": review.id, "student_id": stu.id, "student_code": stu.student_code,
                "first_name": stu.first_name, "surname": stu.surname,
                "previous_status": review.previous_status, "new_status": review.new_status,
                "reason": review.reason, "actor": review.actor,
                "created_at": as_utc(review.created_at).isoformat()} for review, stu in review_result.all()]
    audit_result = await db.execute(select(AttendanceAudit, Student).join(Student, Student.id == AttendanceAudit.student_id)
        .where(AttendanceAudit.session_id == session.id).order_by(AttendanceAudit.created_at.desc()))
    audit_log = [{"id": entry.id, "student_id": stu.id, "student_code": stu.student_code,
                  "first_name": stu.first_name, "surname": stu.surname,
                  "previous_status": entry.previous_status, "new_status": entry.new_status,
                  "reason": entry.reason, "actor": entry.actor,
                  "created_at": as_utc(entry.created_at).isoformat()} for entry, stu in audit_result.all()]
    audit_log.extend(reviews)
    audit_log.sort(key=lambda entry: entry["created_at"], reverse=True)
    elapsed = elapsed_seconds(session)
    needs_initial_scan = session.status == "active" and elapsed < session.absent_after_seconds and any(
        record.status == "waiting" or (record.status == "late" and record.source == "time-based attendance rule")
        for record in records.values()
    )
    return {"id": session.id, "class_name": session.class_name, "started_at": as_utc(session.started_at).isoformat(),
            "elapsed_seconds": round(elapsed, 1), "late_after_seconds": session.late_after_seconds,
            "absent_after_seconds": session.absent_after_seconds, "status": session.status,
            "scanner_should_run": needs_initial_scan or bool(requests),
            "students": [student_json(stu, records.get(stu.id)) for stu in students], "requests": requests,
            "reviews": reviews, "audit_log": audit_log}


def csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def csv_bytes(rows: list[list[Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerows([[csv_cell(value) for value in row] for row in rows])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


@app.get("/api/sessions/{session_id}/export.zip", dependencies=[Depends(require_instructor)])
async def export_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session_result = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id))
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Attendance session not found")

    roster_result = await db.execute(
        select(AttendanceRecord, Student).join(Student, Student.id == AttendanceRecord.student_id)
        .where(AttendanceRecord.session_id == session.id)
        .order_by(Student.surname, Student.first_name))
    roster_rows: list[list[Any]] = [[
        "Student code", "First name", "Surname", "Class/group", "Status", "Marked at", "Source", "Match similarity"
    ]]
    for record, student in roster_result.all():
        roster_rows.append([
            student.student_code, student.first_name, student.surname, student.class_name,
            record.status, as_utc(record.marked_at).isoformat() if record.marked_at else "",
            record.source or "", record.similarity if record.similarity is not None else ""
        ])

    audit_rows: list[list[Any]] = [[
        "Changed at", "Student code", "First name", "Surname",
        "Previous status", "New status", "Changed by", "Reason"
    ]]
    automatic_result = await db.execute(
        select(AttendanceAudit, Student).join(Student, Student.id == AttendanceAudit.student_id)
        .where(AttendanceAudit.session_id == session.id))
    for event, student in automatic_result.all():
        audit_rows.append([
            as_utc(event.created_at).isoformat(), student.student_code, student.first_name, student.surname,
            event.previous_status, event.new_status, event.actor, event.reason
        ])
    review_result = await db.execute(
        select(AttendanceReview, Student).join(Student, Student.id == AttendanceReview.student_id)
        .where(AttendanceReview.session_id == session.id))
    for event, student in review_result.all():
        audit_rows.append([
            as_utc(event.created_at).isoformat(), student.student_code, student.first_name, student.surname,
            event.previous_status, event.new_status, event.actor, event.reason
        ])
    audit_rows[1:] = sorted(audit_rows[1:], key=lambda row: row[0])

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("attendance-roster.csv", csv_bytes(roster_rows))
        bundle.writestr("attendance-audit-trail.csv", csv_bytes(audit_rows))
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="nexus-attendance-{session.id}.zip"'}
    )


@app.get("/api/sessions/{session_id}", dependencies=[Depends(require_instructor)])
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id)); session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    return await session_view(db, session)


@app.post("/api/sessions/{session_id}/students/{student_id}/review", dependencies=[Depends(require_instructor)])
async def review_attendance(session_id: str, student_id: str, body: AttendanceReviewCreate,
                            db: AsyncSession = Depends(get_db), instructor: Instructor = Depends(require_instructor)):
    session_result = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id))
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Attendance session not found")
    record_result = await db.execute(select(AttendanceRecord).where(
        AttendanceRecord.session_id == session_id, AttendanceRecord.student_id == student_id))
    record = record_result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Student is not part of this attendance session")
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "Add a short reason for the attendance correction")
    previous_status = record.status
    record.status = body.status
    record.marked_at = utcnow()
    record.source = "instructor review"
    db.add(AttendanceReview(session_id=session_id, student_id=student_id,
        previous_status=previous_status, new_status=body.status, reason=reason, actor=instructor.username))
    await db.commit()
    await db.refresh(session)
    return await session_view(db, session)


@app.post("/api/sessions/{session_id}/scan", dependencies=[Depends(require_instructor)])
async def scan_frame(session_id: str, body: ScanCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id)); session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    await refresh_records(db, session)
    if session.status != "active" and not body.target_student_id:
        return {"faces": 0, "matches": [], "message": "The standard attendance window has ended"}
    if body.target_student_id:
        target = await db.execute(select(Student).where(Student.id == body.target_student_id)); target_student = target.scalar_one_or_none()
        if not target_student:
            raise HTTPException(404, "Target student not found")
        request = await get_open_request(db, session.id, target_student.id)
        if not request:
            return {"faces": 0, "matches": [], "message": "No open rescan request for that student"}
        students = [target_student]
    else:
        students_result = await db.execute(select(Student).where(Student.class_name == session.class_name))
        required_views = {"front", "left_30", "left_60", "right_30", "right_60", "up", "down"}
        students = [s for s in students_result.scalars() if required_views.issubset({sample.get("view") for sample in (s.embeddings or [])})]
    result_data = need_vision().scan(body.image, students, body.target_student_id)
    elapsed = elapsed_seconds(session)
    for match in result_data["matches"]:
        if not match.get("student_id"):
            continue
        record_result = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id,
            AttendanceRecord.student_id == match["student_id"]))
        record = record_result.scalar_one_or_none()
        if not record:
            continue
        if match.get("needs_review"):
            if record.status != "present" and record.source != "instructor review":
                old_status = record.status
                record.status = "needs_review"
                record.source = "uncertain face match"
                record.marked_at = utcnow()
                record.similarity = match["similarity"]
                if old_status != "needs_review":
                    audit_status_change(db, session.id, record.student_id, old_status, "needs_review",
                        "Classroom camera + face matcher",
                        f"Possible face match needs instructor confirmation (similarity {match['similarity']:.3f}); no identity was confirmed.",
                        record.marked_at)
            match["attendance"] = record.status
            match["student_id"] = None
            match["student_code"] = None
            match["first_name"] = None
            match["surname"] = None
            continue
        if body.target_student_id:
            request = await get_open_request(db, session.id, match["student_id"])
            if not request:
                continue
            old_status = record.status
            record.status = request.claimed_status
            record.source = "phone notice + targeted face rescan"
            record.marked_at = utcnow(); record.similarity = match["similarity"]
            if record.status != old_status:
                audit_status_change(db, session.id, record.student_id, old_status, record.status,
                    "Student phone notice + targeted camera", 
                    f"Targeted face match confirmed the student after a phone notice; the student claimed {record.status} arrival.",
                    record.marked_at)
            request.status = "confirmed"; request.resolved_at = utcnow()
            match["attendance"] = record.status
        elif session.status == "active" and record.source != "instructor review" and record.status != "absent":
            old_status = record.status
            record.status = "present" if elapsed < session.late_after_seconds else "late"
            record.source = "automatic face match"; record.marked_at = utcnow(); record.similarity = match["similarity"]
            if record.status != old_status:
                timing = "on-time window" if record.status == "present" else "late window"
                audit_status_change(db, session.id, record.student_id, old_status, record.status,
                    "Classroom camera + face matcher",
                    f"Enrolled face matched (similarity {match['similarity']:.3f}) during the {timing}.", record.marked_at)
            match["attendance"] = record.status
    await db.commit()
    result_data["elapsed_seconds"] = round(elapsed, 1)
    return result_data


@app.post("/api/phone/notice")
async def phone_notice(body: NoticeCreate, db: AsyncSession = Depends(get_db)):
    stu_result = await db.execute(select(Student).where(Student.student_code == body.student_code.strip().upper()))
    student = stu_result.scalar_one_or_none()
    if not student or student.must_change_password or not verify_pin(body.password, student.pin_hash):
        raise HTTPException(401, "Student code or password is incorrect")
    session_result = await db.execute(select(AttendanceSession).where(AttendanceSession.class_name == student.class_name)
        .order_by(AttendanceSession.started_at.desc()).limit(1))
    session = session_result.scalars().first()
    if not session or elapsed_seconds(session) > 30 * 60:
        raise HTTPException(409, "There is no recent attendance session for this class")
    existing = await get_open_request(db, session.id, student.id)
    if existing:
        return {"request_id": existing.id, "status": existing.status, "message": "Your targeted rescan is already queued"}
    request = CorrectionRequest(session_id=session.id, student_id=student.id, note=body.note.strip() or "Please rescan me",
                                claimed_status=body.claim, status="open", created_at=utcnow())
    db.add(request); await db.commit(); await db.refresh(request)
    return {"request_id": request.id, "status": "open", "message": "Notice sent. The classroom camera will wake for a targeted rescan."}


@app.post("/api/phone/login")
async def phone_login(body: PhoneLogin, db: AsyncSession = Depends(get_db)):
    stu_result = await db.execute(select(Student).where(Student.student_code == body.student_code.strip().upper()))
    student = stu_result.scalar_one_or_none()
    if not student or not verify_pin(body.password, student.pin_hash):
        raise HTTPException(401, "Student code or password is incorrect")
    if student.must_change_password:
        return {"must_change_password": True, "student": {"student_code": student.student_code,
                "first_name": student.first_name, "surname": student.surname}}
    token = None
    lifetime = 30 * 24 * 60 * 60
    if body.mobile_session:
        token = secrets.token_urlsafe(48)
        db.add(StudentSession(student_id=student.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                              expires_at=utcnow() + timedelta(seconds=lifetime)))
        await db.commit()
    session_result = await db.execute(select(AttendanceSession).where(AttendanceSession.class_name == student.class_name)
        .order_by(AttendanceSession.started_at.desc()).limit(1))
    session = session_result.scalars().first()
    record = None
    if session:
        record_result = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id))
        record = record_result.scalar_one_or_none()
    response = {"student": {"student_code": student.student_code, "first_name": student.first_name,
                        "surname": student.surname, "class_name": student.class_name, "email": student.email,
                        "profile_photo_available": bool(student.profile_photo_path)},
            "session": ({"id": session.id, "status": session.status, "elapsed_seconds": round(elapsed_seconds(session),1),
                         "attendance": record.status if record else "not enrolled in this session"} if session else None)}
    if token:
        response.update({"access_token": token, "token_type": "bearer", "expires_in": lifetime})
    return response


@app.post("/api/phone/first-password")
async def first_password_change(body: FirstPasswordChange, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Student).where(Student.student_code == body.student_code.strip().upper()))
    student = result.scalar_one_or_none()
    if not student or not student.must_change_password or not verify_pin(body.temporary_pin, student.pin_hash):
        raise HTTPException(401, "Student code or temporary PIN is incorrect")
    if not valid_password(body.new_password):
        raise HTTPException(422, "Use at least 12 characters with uppercase and lowercase letters, a number, and a symbol")
    student.pin_hash = hash_pin(body.new_password)
    student.must_change_password = False
    await db.commit()
    return {"changed": True, "message": "Password changed. Sign in with your new password."}


@app.get("/api/phone/me")
async def student_me(student: Student = Depends(require_student), db: AsyncSession = Depends(get_db)):
    session_result = await db.execute(select(AttendanceSession).where(AttendanceSession.class_name == student.class_name)
        .order_by(AttendanceSession.started_at.desc()).limit(1))
    session = session_result.scalars().first()
    record = None
    if session:
        record_result = await db.execute(select(AttendanceRecord).where(
            AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id))
        record = record_result.scalar_one_or_none()
    return {"student": {"student_code": student.student_code, "first_name": student.first_name,
                         "surname": student.surname, "class_name": student.class_name, "email": student.email,
                         "profile_photo_available": bool(student.profile_photo_path)},
            "session": ({"id": session.id, "status": session.status,
                         "elapsed_seconds": round(elapsed_seconds(session), 1),
                         "attendance": record.status if record else "not enrolled in this session"} if session else None)}


@app.post("/api/phone/change-password")
async def student_change_password(body: StudentPasswordChange,
                                  student: Student = Depends(require_student), db: AsyncSession = Depends(get_db)):
    if not verify_pin(body.current_password, student.pin_hash):
        raise HTTPException(401, "Current password is incorrect")
    if not valid_password(body.new_password):
        raise HTTPException(422, "Use at least 12 characters with uppercase and lowercase letters, a number, and a symbol")
    student.pin_hash = hash_pin(body.new_password)
    sessions_result = await db.execute(select(StudentSession).where(StudentSession.student_id == student.id))
    for session in sessions_result.scalars():
        await db.delete(session)
    new_token = secrets.token_urlsafe(48)
    lifetime = 30 * 24 * 60 * 60
    db.add(StudentSession(student_id=student.id, token_hash=hashlib.sha256(new_token.encode()).hexdigest(),
                          expires_at=utcnow() + timedelta(seconds=lifetime)))
    await db.commit()
    return {"changed": True, "access_token": new_token, "token_type": "bearer", "expires_in": lifetime}


@app.post("/api/phone/profile-photo")
async def save_student_profile_photo(body: StudentPhotoUpload,
                                     student: Student = Depends(require_student), db: AsyncSession = Depends(get_db)):
    try:
        encoded = body.image_data.split(",", 1)[-1]
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(400, "Choose a valid photo") from exc
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Choose a photo smaller than 5 MB")
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(400, "That photo format could not be opened")
    height, width = frame.shape[:2]
    scale = min(1.0, 512 / max(width, height))
    if scale < 1.0:
        frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    ok, image_bytes = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 86])
    if not ok:
        raise HTTPException(400, "Could not process that photo")
    PROFILE_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{student.id}.jpg"
    (PROFILE_PHOTO_DIR / filename).write_bytes(image_bytes.tobytes())
    student.profile_photo_path = filename
    await db.commit()
    return {"saved": True}


@app.get("/api/phone/profile-photo")
async def get_student_profile_photo(student: Student = Depends(require_student)):
    if not student.profile_photo_path:
        return {"image_data": None}
    path = PROFILE_PHOTO_DIR / f"{student.id}.jpg"
    if not path.is_file():
        return {"image_data": None}
    image_data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"image_data": f"data:image/jpeg;base64,{image_data}"}


@app.delete("/api/phone/profile-photo")
async def delete_student_profile_photo(student: Student = Depends(require_student), db: AsyncSession = Depends(get_db)):
    path = PROFILE_PHOTO_DIR / f"{student.id}.jpg"
    path.unlink(missing_ok=True)
    student.profile_photo_path = None
    await db.commit()
    return {"deleted": True}


@app.post("/api/phone/notice-session")
async def student_notice_with_session(body: StudentNoticeSession,
                                      student: Student = Depends(require_student), db: AsyncSession = Depends(get_db)):
    session_result = await db.execute(select(AttendanceSession).where(AttendanceSession.class_name == student.class_name)
        .order_by(AttendanceSession.started_at.desc()).limit(1))
    session = session_result.scalars().first()
    if not session or elapsed_seconds(session) > 30 * 60:
        raise HTTPException(409, "There is no recent attendance session for this class")
    existing = await get_open_request(db, session.id, student.id)
    if existing:
        return {"request_id": existing.id, "status": existing.status,
                "message": "Your targeted rescan is already queued"}
    request = CorrectionRequest(session_id=session.id, student_id=student.id,
        note=body.note.strip() or "Please rescan me", claimed_status=body.claim, status="open", created_at=utcnow())
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return {"request_id": request.id, "status": "open",
            "message": "Notice sent. The classroom camera will wake for a targeted rescan."}


@app.post("/api/phone/logout")
async def student_logout(request: Request, db: AsyncSession = Depends(get_db)):
    raw_token = request.headers.get("authorization", "").partition(" ")[2]
    if raw_token:
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await db.execute(select(StudentSession).where(StudentSession.token_hash == digest))
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()
    return {"logged_out": True}


def safe_send_password_reset_email(email: str, first_name: str, token: str) -> None:
    try:
        send_password_reset_email(email, first_name, token)
        print("[NEXUS Attendance] Password reset email sent.")
    except Exception as exc:
        print(f"[NEXUS Attendance] Password reset email could not be sent: {exc}")


@app.post("/api/phone/password-reset/request")
async def request_password_reset(body: PasswordResetRequest, background_tasks: BackgroundTasks,
                                 db: AsyncSession = Depends(get_db)):
    generic_response = {"message": "If an account matches that email, password reset instructions will be sent shortly."}
    email = body.email.strip().lower()
    result = await db.execute(select(Student).where(Student.email == email))
    student = result.scalar_one_or_none()
    if not student:
        return generic_response
    now = utcnow()
    recent_result = await db.execute(select(PasswordReset).where(
        PasswordReset.student_id == student.id,
        PasswordReset.created_at >= now - timedelta(minutes=15)
    ).order_by(PasswordReset.created_at.desc()))
    recent_requests = list(recent_result.scalars())
    if len(recent_requests) >= 5:
        return generic_response
    active_result = await db.execute(select(PasswordReset).where(
        PasswordReset.student_id == student.id, PasswordReset.used_at.is_(None)))
    for old_reset in active_result.scalars():
        old_reset.used_at = now
    raw_token = secrets.token_urlsafe(32)
    reset = PasswordReset(student_id=student.id, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                          expires_at=now + timedelta(minutes=30), created_at=now)
    db.add(reset)
    await db.commit()
    background_tasks.add_task(safe_send_password_reset_email, email, student.first_name, raw_token)
    return generic_response


@app.post("/api/phone/password-reset/confirm")
async def confirm_password_reset(body: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    result = await db.execute(select(PasswordReset).where(PasswordReset.token_hash == token_hash))
    reset = result.scalar_one_or_none()
    now = utcnow()
    if not reset or reset.used_at is not None or as_utc(reset.expires_at) <= now:
        raise HTTPException(400, "This reset link is invalid or expired. Request a new one.")
    if not valid_password(body.new_password):
        raise HTTPException(422, "Use at least 12 characters with uppercase and lowercase letters, a number, and a symbol")
    student_result = await db.execute(select(Student).where(Student.id == reset.student_id))
    student = student_result.scalar_one_or_none()
    if not student:
        reset.used_at = now
        await db.commit()
        raise HTTPException(400, "This reset link is invalid or expired. Request a new one.")
    student.pin_hash = hash_pin(body.new_password)
    student.must_change_password = False
    sessions_result = await db.execute(select(StudentSession).where(StudentSession.student_id == student.id))
    for session in sessions_result.scalars():
        await db.delete(session)
    reset.used_at = now
    other_result = await db.execute(select(PasswordReset).where(
        PasswordReset.student_id == student.id, PasswordReset.used_at.is_(None), PasswordReset.id != reset.id))
    for other in other_result.scalars():
        other.used_at = now
    await db.commit()
    return {"changed": True, "message": "Password reset. You can now sign in with your new password."}


@app.post("/api/sessions/{session_id}/close", dependencies=[Depends(require_instructor)])
async def close_session(session_id: str, db: AsyncSession = Depends(get_db), instructor: Instructor = Depends(require_instructor)):
    result = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id)); session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    rows = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id))
    for record in rows.scalars():
        if record.status not in ("present", "late"):
            old_status = record.status
            record.status = "absent"; record.source = "instructor ended session"
            if old_status != "absent":
                audit_status_change(db, session.id, record.student_id, old_status, "absent", f"Instructor: {instructor.username}",
                    "The instructor closed the attendance session before this student had a confirmed present or late status.")
    session.status = "completed"; await db.commit()
    return await session_view(db, session)


@app.get("/api/sessions/{session_id}/requests", dependencies=[Depends(require_instructor)])
async def session_requests(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id)); session = result.scalar_one_or_none()
    if not session: raise HTTPException(404, "Session not found")
    view = await session_view(db, session)
    return view["requests"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
