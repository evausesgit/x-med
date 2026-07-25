"""Modèles ORM : médecins + profil détaillé (pilote le digest personnalisé).

Schéma de référence : ARCHITECTURE.md § Schéma SQL (tables doctors / doctor_profiles).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Langues proposées par l'interface. Elles pilotent AUSSI la traduction
# automatique des titres/résumés : l'anglais est la langue des abstracts
# PubMed, donc l'afficher ne coûte aucun appel de traduction — c'est la
# langue principale du produit et le défaut des nouveaux comptes.
SUPPORTED_LANGUAGES = ("en", "fr")
DEFAULT_LANGUAGE = "en"
# Motif de validation Pydantic, dérivé de la liste (une seule source de vérité).
LANGUAGE_PATTERN = f"^({'|'.join(SUPPORTED_LANGUAGES)})$"


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # UID du compte Google (Firebase Auth) rattaché ; NULL tant que le médecin
    # ne s'est jamais connecté (profil créé à la main via l'annuaire).
    firebase_uid: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Langue de l'interface ET des traductions automatiques d'articles. Les
    # comptes créés avant l'anglais gardent la valeur 'fr' en base (cf.
    # migration 0011 : seul le DÉFAUT change, pas les lignes existantes).
    language: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=DEFAULT_LANGUAGE
    )
    digest_frequency: Mapped[str] = mapped_column(Text, nullable=False, server_default="daily")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    profile: Mapped["DoctorProfile | None"] = relationship(
        back_populates="doctor", uselist=False, cascade="all, delete-orphan"
    )


class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True
    )
    specialty_main: Mapped[str] = mapped_column(Text, nullable=False)
    subspecialties: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    pathologies: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    treatments: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    study_types: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    min_evidence_level: Mapped[int | None] = mapped_column(Integer)
    preferred_journals: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    mesh_terms_extra: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    keywords_extra: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    doctor: Mapped["Doctor"] = relationship(back_populates="profile")
