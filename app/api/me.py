"""Endpoints « mon profil » : le médecin rattaché au compte Google connecté.

L'identité vient du proxy Next (web/proxy.ts) qui vérifie l'ID token Firebase
et transmet les headers X-User-Uid / X-User-Email / X-User-Name — toujours
écrasés côté proxy, jamais repris du navigateur. Le rattachement se fait par
firebase_uid (stable même si l'email Google change), avec un repli par email
pour les profils saisis à la main avant l'arrivée de l'auth.

- POST /me/bootstrap : crée ou rattache le médecin (appelé au chargement de
  la page profil ; idempotent).
- GET  /me           : lecture pure, 404 si aucun médecin rattaché.
- PUT  /me/profile   : met à jour le profil du médecin connecté uniquement.
"""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.doctors import DoctorOut, ProfileIn, _to_out
from app.db import get_session
from app.models import Doctor, DoctorProfile

router = APIRouter()


class Identity(BaseModel):
    uid: str
    email: str
    name: str


def current_identity(
    x_user_uid: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
) -> Identity:
    if not x_user_uid or not x_user_email:
        # Appel direct sans passer par le proxy Next (dev, cron…).
        raise HTTPException(401, "Authentification requise.")
    return Identity(
        uid=x_user_uid,
        email=x_user_email.lower(),
        # Encodé côté proxy (encodeURIComponent) : les headers HTTP ne
        # transportent pas les accents de façon fiable.
        name=unquote(x_user_name or ""),
    )


def _find_doctor(session: Session, ident: Identity) -> Doctor | None:
    doctor = session.scalar(select(Doctor).where(Doctor.firebase_uid == ident.uid))
    if doctor is not None:
        return doctor
    # Repli : profil créé à la main avant l'auth, pas encore rattaché.
    return session.scalar(
        select(Doctor).where(
            func.lower(Doctor.email) == ident.email, Doctor.firebase_uid.is_(None)
        )
    )


@router.get("/me", response_model=DoctorOut)
def get_me(
    ident: Identity = Depends(current_identity),
    session: Session = Depends(get_session),
):
    doctor = _find_doctor(session, ident)
    if doctor is None:
        raise HTTPException(404, "Aucun profil rattaché à ce compte")
    return _to_out(doctor)


@router.post("/me/bootstrap", response_model=DoctorOut)
def bootstrap_me(
    ident: Identity = Depends(current_identity),
    session: Session = Depends(get_session),
):
    doctor = _find_doctor(session, ident)
    if doctor is None:
        # L'email est UNIQUE : s'il existe déjà, c'est qu'il est rattaché à un
        # AUTRE compte Google — on ne le vole pas.
        if session.scalar(select(Doctor).where(func.lower(Doctor.email) == ident.email)):
            raise HTTPException(409, "Cet email est déjà rattaché à un autre compte")
        doctor = Doctor(
            email=ident.email,
            firebase_uid=ident.uid,
            # Le nom Google sert de valeur initiale seulement ; il reste
            # éditable ensuite sans être resynchronisé.
            name=ident.name or ident.email,
        )
        session.add(doctor)
    elif doctor.firebase_uid is None:
        doctor.firebase_uid = ident.uid
    session.commit()
    session.refresh(doctor)
    return _to_out(doctor)


@router.put("/me/profile", response_model=DoctorOut)
def update_my_profile(
    body: ProfileIn,
    ident: Identity = Depends(current_identity),
    session: Session = Depends(get_session),
):
    doctor = _find_doctor(session, ident)
    if doctor is None:
        raise HTTPException(404, "Aucun profil rattaché à ce compte")
    if doctor.firebase_uid is None:
        doctor.firebase_uid = ident.uid
    if doctor.profile is None:
        doctor.profile = DoctorProfile(doctor_id=doctor.id, **body.model_dump())
    else:
        for field, value in body.model_dump().items():
            setattr(doctor.profile, field, value)
    session.commit()
    session.refresh(doctor)
    return _to_out(doctor)
