"""
Core SQLAlchemy Models for Nigrani Platform Database.

Implements tables specified in docs/database.md:
- users (Platform user authentication and role mapping)
- projects
- versions
- runs
- protections
- protection_results
- regressions
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """Platform user for self-hosted authentication and role mapping."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'viewer')",
            name="chk_users_role",
        ),
    )

    # Relationships
    projects: Mapped[list[Project]] = relationship("Project", back_populates="owner")


class Project(Base):
    """Target software project monitored by Nigrani."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    stack: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_branch: Mapped[str] = mapped_column(
        String(64), nullable=False, default="main"
    )
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('github', 'zip', 'folder')",
            name="chk_projects_source_type",
        ),
    )

    # Relationships
    owner: Mapped[User | None] = relationship("User", back_populates="projects")
    versions: Mapped[list[Version]] = relationship(
        "Version", back_populates="project", cascade="all, delete-orphan"
    )
    protections: Mapped[list[Protection]] = relationship(
        "Protection", back_populates="project", cascade="all, delete-orphan"
    )
    regressions: Mapped[list[Regression]] = relationship(
        "Regression", back_populates="project", cascade="all, delete-orphan"
    )


class Version(Base):
    """Immutable release or commit version of a project."""

    __tablename__ = "versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('import', 'webhook', 'manual')",
            name="chk_versions_trigger",
        ),
        UniqueConstraint("project_id", "number", name="uq_versions_project_number"),
        Index("ix_versions_project_number", "project_id", "number"),
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="versions")
    runs: Mapped[list[Run]] = relationship(
        "Run", back_populates="version", cascade="all, delete-orphan"
    )
    protection_results: Mapped[list[ProtectionResult]] = relationship(
        "ProtectionResult", back_populates="version", cascade="all, delete-orphan"
    )


class Run(Base):
    """Execution run (test, baseline, fix, or condense) on a version."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    model: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('baseline', 'monitor', 'fix', 'condense')",
            name="chk_runs_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="chk_runs_status",
        ),
    )

    # Relationships
    version: Mapped[Version] = relationship("Version", back_populates="runs")
    protection_results: Mapped[list[ProtectionResult]] = relationship(
        "ProtectionResult", back_populates="run", cascade="all, delete-orphan"
    )


class Protection(Base):
    """Security property or invariant established for a project."""

    __tablename__ = "protections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_node_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    test_template: Mapped[str] = mapped_column(String(32), nullable=False)
    test_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="rule")
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "test_template IN ('ownership', 'unauthenticated', 'role', 'rls', 'validation')",
            name="chk_protections_test_template",
        ),
        CheckConstraint(
            "state IN ('candidate', 'confirmed', 'rejected')",
            name="chk_protections_state",
        ),
        CheckConstraint(
            "source IN ('rule', 'model', 'developer')",
            name="chk_protections_source",
        ),
        UniqueConstraint("project_id", "code", name="uq_protections_project_code"),
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="protections")
    results: Mapped[list[ProtectionResult]] = relationship(
        "ProtectionResult", back_populates="protection", cascade="all, delete-orphan"
    )
    regressions: Mapped[list[Regression]] = relationship(
        "Regression", back_populates="protection", cascade="all, delete-orphan"
    )


class ProtectionResult(Base):
    """Result of running a protection test against a specific version and run."""

    __tablename__ = "protection_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    protection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("protections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PASS', 'FAIL', 'ERROR', 'SKIPPED')",
            name="chk_protection_results_status",
        ),
        UniqueConstraint(
            "protection_id", "run_id", name="uq_protection_results_protection_run"
        ),
        Index(
            "ix_protection_results_protection_version",
            "protection_id",
            "version_id",
        ),
    )

    # Relationships
    protection: Mapped[Protection] = relationship(
        "Protection", back_populates="results"
    )
    version: Mapped[Version] = relationship(
        "Version", back_populates="protection_results"
    )
    run: Mapped[Run] = relationship("Run", back_populates="protection_results")


class Regression(Base):
    """Detected regression when a protection changed from PASS to FAIL."""

    __tablename__ = "regressions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    protection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("protections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    first_failed_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    suspect_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    associated_feature: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('open', 'fixed', 'dismissed')",
            name="chk_regressions_state",
        ),
        Index("ix_regressions_project_state", "project_id", "state"),
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="regressions")
    protection: Mapped[Protection] = relationship(
        "Protection", back_populates="regressions"
    )
    previous_version: Mapped[Version] = relationship(
        "Version", foreign_keys=[previous_version_id]
    )
    current_version: Mapped[Version] = relationship(
        "Version", foreign_keys=[current_version_id]
    )
    first_failed_version: Mapped[Version] = relationship(
        "Version", foreign_keys=[first_failed_version_id]
    )
