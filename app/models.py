from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Province(Base):
    __tablename__ = "provinces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    districts = relationship(
        "District",
        back_populates="province",
        cascade="all, delete-orphan"
    )


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    province_id: Mapped[int] = mapped_column(
        ForeignKey("provinces.id"),
        nullable=False
    )

    province = relationship("Province", back_populates="districts")

    substations = relationship(
        "GridSubstation",
        back_populates="district",
        cascade="all, delete-orphan"
    )


class GridSubstation(Base):
    __tablename__ = "grid_substations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    district_id: Mapped[int] = mapped_column(
        ForeignKey("districts.id"),
        nullable=False
    )

    district = relationship("District", back_populates="substations")

    installations = relationship(
        "SolarInstallation",
        back_populates="substation",
        cascade="all, delete-orphan"
    )


class SolarInstallation(Base):
    __tablename__ = "solar_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    meter_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False
    )

    capacity_kw: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    substation_id: Mapped[int] = mapped_column(
        ForeignKey("grid_substations.id"),
        nullable=False
    )

    substation = relationship(
        "GridSubstation",
        back_populates="installations"
    )

    readings = relationship(
        "GenerationReading",
        back_populates="installation",
        cascade="all, delete-orphan"
    )


class GenerationReading(Base):
    __tablename__ = "generation_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    installation_id: Mapped[int] = mapped_column(
        ForeignKey("solar_installations.id"),
        nullable=False
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )

    power_kw: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    cumulative_energy_kwh: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    voltage: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    installation = relationship(
        "SolarInstallation",
        back_populates="readings"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    username: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    province_id: Mapped[int | None] = mapped_column(
        ForeignKey("provinces.id"),
        nullable=True
    )

    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id"),
        nullable=True
    )

    substation_id: Mapped[int | None] = mapped_column(
        ForeignKey("grid_substations.id"),
        nullable=True
    )

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False
    )

    reading_id: Mapped[int] = mapped_column(
        ForeignKey("generation_readings.id"),
        nullable=False
    )