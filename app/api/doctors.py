"""Endpoints CRUD médecins + profil (pilote le digest personnalisé).

Voir ARCHITECTURE.md § API. Le profil détaillé sert au matching (MeSH/embedding)
et au scoring Claude ; ici on gère sa persistance (création / lecture / mise à jour).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Doctor, DoctorProfile

router = APIRouter()


# ---------- Schémas ----------

class ProfileIn(BaseModel):
    specialty_main: str
    subspecialties: list[str] = []
    pathologies: list[str] = []
    treatments: list[str] = []
    study_types: list[str] = []
    min_evidence_level: int | None = None
    preferred_journals: list[str] = []
    mesh_terms_extra: list[str] = []
    keywords_extra: list[str] = []


class ProfileOut(ProfileIn):
    pass


class DoctorIn(BaseModel):
    email: str
    name: str
    language: str = "fr"
    digest_frequency: str = Field(default="daily", pattern="^(daily|weekly)$")
    profile: ProfileIn | None = None


class DoctorOut(BaseModel):
    id: str
    email: str
    name: str
    language: str
    digest_frequency: str
    profile: ProfileOut | None = None


def _to_out(d: Doctor) -> DoctorOut:
    prof = None
    if d.profile is not None:
        prof = ProfileOut(
            specialty_main=d.profile.specialty_main,
            subspecialties=d.profile.subspecialties or [],
            pathologies=d.profile.pathologies or [],
            treatments=d.profile.treatments or [],
            study_types=d.profile.study_types or [],
            min_evidence_level=d.profile.min_evidence_level,
            preferred_journals=d.profile.preferred_journals or [],
            mesh_terms_extra=d.profile.mesh_terms_extra or [],
            keywords_extra=d.profile.keywords_extra or [],
        )
    return DoctorOut(
        id=str(d.id),
        email=d.email,
        name=d.name,
        language=d.language,
        digest_frequency=d.digest_frequency,
        profile=prof,
    )


def _get_doctor(session: Session, doctor_id: str) -> Doctor:
    try:
        did = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(400, "Identifiant médecin invalide")
    doctor = session.get(Doctor, did)
    if doctor is None:
        raise HTTPException(404, "Médecin introuvable")
    return doctor


# ---------- Endpoints ----------

@router.post("/doctors", response_model=DoctorOut, status_code=201)
def create_doctor(body: DoctorIn, session: Session = Depends(get_session)):
    if session.scalar(select(Doctor).where(Doctor.email == body.email)):
        raise HTTPException(409, "Un médecin avec cet email existe déjà")
    doctor = Doctor(
        email=body.email,
        name=body.name,
        language=body.language,
        digest_frequency=body.digest_frequency,
    )
    if body.profile is not None:
        doctor.profile = DoctorProfile(**body.profile.model_dump())
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return _to_out(doctor)


@router.get("/doctors", response_model=list[DoctorOut])
def list_doctors(session: Session = Depends(get_session)):
    doctors = session.scalars(select(Doctor).order_by(Doctor.created_at.desc())).all()
    return [_to_out(d) for d in doctors]


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: str, session: Session = Depends(get_session)):
    return _to_out(_get_doctor(session, doctor_id))


@router.put("/doctors/{doctor_id}/profile", response_model=DoctorOut)
def upsert_profile(doctor_id: str, body: ProfileIn, session: Session = Depends(get_session)):
    doctor = _get_doctor(session, doctor_id)
    if doctor.profile is None:
        doctor.profile = DoctorProfile(doctor_id=doctor.id, **body.model_dump())
    else:
        for field, value in body.model_dump().items():
            setattr(doctor.profile, field, value)
    session.commit()
    session.refresh(doctor)
    return _to_out(doctor)


@router.delete("/doctors/{doctor_id}", status_code=204)
def delete_doctor(doctor_id: str, session: Session = Depends(get_session)):
    doctor = _get_doctor(session, doctor_id)
    session.delete(doctor)
    session.commit()
