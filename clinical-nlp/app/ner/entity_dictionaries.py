"""Curated term lists for dictionary/keyword-based NER.

These are intentionally small (~20-30 per category) — this is a hackathon
starter set, not exhaustive clinical coverage. They cover the kinds of
headline terms that show up in routine clinical text and that scispaCy
+ bc5cdr alone tend to miss (e.g. allergy phrasings, procedure verbs,
short lab names).

Each entry is a (surface_form, canonical_term) tuple. The dictionary
matcher in app/ner/dictionary.py uses the surface_form for case-insensitive
whole-word matching; the canonical_term is what we put on the entity's
`.text` (or kept as surface_text — see dictionary.py).

Person B owns this file. Do NOT route these through db/seeds — those
files belong to other team members and contain different data.
"""

from __future__ import annotations

# Canonical entity_type values used by the hybrid NER. These mirror the
# seven categories from the brief. Person B does NOT enforce an enum
# here — app/validation/validator.py does the enum check downstream,
# since ClinicalEvent.entity_type is currently a free str.
ENTITY_TYPE_DISEASE = "Disease"
ENTITY_TYPE_SYMPTOM = "Symptom"
ENTITY_TYPE_MEDICATION = "Medication"
ENTITY_TYPE_ALLERGY = "Allergy"
ENTITY_TYPE_PROCEDURE = "Procedure"
ENTITY_TYPE_LAB = "LaboratoryFinding"
ENTITY_TYPE_DOSAGE = "Dosage"
ENTITY_TYPE_ROUTE = "Route"


# ---- Symptoms (~25) ----
SYMPTOM_TERMS: tuple[tuple[str, str], ...] = (
    ("fever", "fever"),
    ("pyrexia", "fever"),
    ("chills", "chills"),
    ("cough", "cough"),
    ("shortness of breath", "shortness of breath"),
    ("dyspnea", "dyspnea"),
    ("dyspnoea", "dyspnea"),
    ("chest pain", "chest pain"),
    ("headache", "headache"),
    ("nausea", "nausea"),
    ("vomiting", "vomiting"),
    ("diarrhea", "diarrhea"),
    ("fatigue", "fatigue"),
    ("dizziness", "dizziness"),
    ("syncope", "syncope"),
    ("palpitations", "palpitations"),
    ("abdominal pain", "abdominal pain"),
    ("back pain", "back pain"),
    ("sore throat", "sore throat"),
    ("rash", "rash"),
    ("pruritus", "pruritus"),
    ("edema", "edema"),
    ("oedema", "edema"),
    ("weight loss", "weight loss"),
    ("night sweats", "night sweats"),
    ("insomnia", "insomnia"),
    ("anxiety", "anxiety"),
    ("depression", "depression"),
)


# ---- Allergies (~20) ----
ALLERGY_TERMS: tuple[tuple[str, str], ...] = (
    ("penicillin", "penicillin allergy"),
    ("amoxicillin", "penicillin allergy"),
    ("sulfa", "sulfa allergy"),
    ("sulfonamide", "sulfa allergy"),
    ("aspirin", "aspirin allergy"),
    ("nsaid", "nsaid allergy"),
    ("ibuprofen", "nsaid allergy"),
    ("latex", "latex allergy"),
    ("peanut", "peanut allergy"),
    ("shellfish", "shellfish allergy"),
    ("egg", "egg allergy"),
    ("soy", "soy allergy"),
    ("wheat", "wheat allergy"),
    ("dairy", "dairy allergy"),
    ("milk", "milk allergy"),
    ("contrast dye", "contrast dye allergy"),
    ("iodine", "iodine allergy"),
    ("codeine", "codeine allergy"),
    ("morphine", "opioid allergy"),
    ("tape", "adhesive allergy"),
    ("bee sting", "bee sting allergy"),
)


# ---- Procedures (~20) ----
PROCEDURE_TERMS: tuple[tuple[str, str], ...] = (
    ("ecg", "electrocardiogram"),
    ("ekg", "electrocardiogram"),
    ("electrocardiogram", "electrocardiogram"),
    ("echocardiogram", "echocardiogram"),
    ("echo", "echocardiogram"),
    ("x-ray", "x-ray"),
    ("xray", "x-ray"),
    ("ct scan", "ct scan"),
    ("ct", "ct scan"),
    ("mri", "mri"),
    ("ultrasound", "ultrasound"),
    ("colonoscopy", "colonoscopy"),
    ("endoscopy", "endoscopy"),
    ("bronchoscopy", "bronchoscopy"),
    ("biopsy", "biopsy"),
    ("surgery", "surgery"),
    ("appendectomy", "appendectomy"),
    ("cholecystectomy", "cholecystectomy"),
    ("cardiac catheterization", "cardiac catheterization"),
    ("dialysis", "dialysis"),
    ("intubation", "intubation"),
    ("vaccination", "vaccination"),
    ("blood transfusion", "blood transfusion"),
)


# ---- Laboratory findings (~25) ----
LAB_TERMS: tuple[tuple[str, str], ...] = (
    ("glucose", "blood glucose"),
    ("blood glucose", "blood glucose"),
    ("hba1c", "hemoglobin a1c"),
    ("hemoglobin a1c", "hemoglobin a1c"),
    ("cholesterol", "total cholesterol"),
    ("ldl", "ldl cholesterol"),
    ("hdl", "hdl cholesterol"),
    ("triglycerides", "triglycerides"),
    ("creatinine", "serum creatinine"),
    ("bun", "blood urea nitrogen"),
    ("hemoglobin", "hemoglobin"),
    ("haemoglobin", "hemoglobin"),
    ("wbc", "white blood cell count"),
    ("rbc", "red blood cell count"),
    ("platelet count", "platelet count"),
    ("inr", "inr"),
    ("pt", "prothrombin time"),
    ("ptt", "partial thromboplastin time"),
    ("troponin", "troponin"),
    ("bnp", "bnp"),
    ("potassium", "serum potassium"),
    ("sodium", "serum sodium"),
    ("tsh", "thyroid stimulating hormone"),
    ("tsh level", "thyroid stimulating hormone"),
    ("urinalysis", "urinalysis"),
    ("urine culture", "urine culture"),
)


# ---- Routes (controlled vocabulary for Route NER) ----
ROUTE_TERMS: tuple[str, ...] = (
    "oral",
    "orally",
    "po",
    "iv",
    "intravenous",
    "intravenously",
    "im",
    "intramuscular",
    "intramuscularly",
    "sc",
    "subcutaneous",
    "subcutaneously",
    "sl",
    "sublingual",
    "sublingually",
    "topical",
    "topically",
    "inhaled",
    "inhalation",
    "nebulized",
    "rectal",
    "pr",
    "ophthalmic",
    "otic",
    "nasal",
    "transdermal",
)


__all__ = [
    "ALLERGY_TERMS",
    "ENTITY_TYPE_ALLERGY",
    "ENTITY_TYPE_DISEASE",
    "ENTITY_TYPE_DOSAGE",
    "ENTITY_TYPE_LAB",
    "ENTITY_TYPE_MEDICATION",
    "ENTITY_TYPE_PROCEDURE",
    "ENTITY_TYPE_ROUTE",
    "ENTITY_TYPE_SYMPTOM",
    "LAB_TERMS",
    "PROCEDURE_TERMS",
    "ROUTE_TERMS",
    "SYMPTOM_TERMS",
]
