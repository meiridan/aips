"""The wizard's answers, validated and rendered into a persona description.

`PersonaSpec` is what the creation wizard POSTs. Validation is membership in
:mod:`maya.companions.catalog` rather than duplicated ``Literal`` unions, so
adding an option to the catalog automatically makes it submittable.

`to_persona_description` renders the spec into the English paragraph stored as
``companion.personality["description"]`` — the one field the Phase-3 prompt
reads (see ``maya.conversation.prompt_builder.build_phase3``). That is why the
whole wizard shapes the companion without touching the prompt template.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from maya.companions import catalog

# Wizard field → catalog group. Every one of these is a single-choice group.
_SINGLE_FIELDS: dict[str, str] = {
    "style": "style",
    "ethnicity": "ethnicity",
    "hair_style": "hair_style",
    "hair_color": "hair_color",
    "eye_color": "eye_color",
    "body_type": "body_type",
    "breast_size": "breast_size",
    "butt_size": "butt_size",
    "personality": "personality",
    "relationship": "relationship",
    "occupation": "occupation",
    "clothing": "clothing",
    "voice_style": "voice_style",
}

MAX_EXTRA_DETAILS = 500


class PersonaSpec(BaseModel):
    """One completed run of the creation wizard."""

    name: str = Field(min_length=1, max_length=40)
    age: int = Field(ge=catalog.AGE_MIN, le=catalog.AGE_MAX)

    style: str
    ethnicity: str
    hair_style: str
    hair_color: str
    eye_color: str
    body_type: str
    breast_size: str
    butt_size: str

    personality: str
    relationship: str
    occupation: str
    clothing: str
    voice_style: str
    hobbies: list[str] = Field(default_factory=list, max_length=8)

    extra_details: str | None = Field(default=None, max_length=MAX_EXTRA_DETAILS)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @model_validator(mode="after")
    def _check_catalog_membership(self) -> PersonaSpec:
        for field, group_id in _SINGLE_FIELDS.items():
            value = getattr(self, field)
            group = catalog.GROUPS[group_id]
            if value not in group.ids():
                raise ValueError(f"unknown {field}: {value!r}")
        valid_hobbies = catalog.GROUPS["hobbies"].ids()
        for hobby in self.hobbies:
            if hobby not in valid_hobbies:
                raise ValueError(f"unknown hobby: {hobby!r}")
        return self

    # ── derived values ────────────────────────────────────────────────────
    def template_id(self) -> str:
        """The existing maya.companions.templates archetype this maps onto."""
        opt = catalog.option("personality", self.personality)
        return str((opt.extra.get("template_id") if opt else None) or "flirt")

    def traits(self) -> list[str]:
        opt = catalog.option("personality", self.personality)
        return list(opt.extra.get("traits", [])) if opt else []

    def tone(self) -> str:
        opt = catalog.option("personality", self.personality)
        return str((opt.extra.get("tone") if opt else None) or "light")


def _f(group: str, value: str) -> str:
    return catalog.fragment(group, value)


def to_persona_description(spec: PersonaSpec) -> str:
    """Render the spec as the English persona paragraph fed to the LLM."""
    appearance = (
        f"{spec.name} is a {spec.age}-year-old {_f('ethnicity', spec.ethnicity)} woman "
        f"({_f('style', spec.style)}), {_f('body_type', spec.body_type)}, with "
        f"{_f('hair_style', spec.hair_style)} {_f('hair_color', spec.hair_color)} hair "
        f"and {_f('eye_color', spec.eye_color)} eyes. She is "
        f"{_f('breast_size', spec.breast_size)}-chested with "
        f"{_f('butt_size', spec.butt_size)} hips. "
        f"She usually wears {_f('clothing', spec.clothing)}."
    )

    character = (
        f"She is {_f('personality', spec.personality)}. "
        f"She works as {_f('occupation', spec.occupation)}. "
        f"She is {_f('relationship', spec.relationship)}. "
        f"She speaks {_f('voice_style', spec.voice_style)}."
    )

    if spec.hobbies:
        joined = ", ".join(_f("hobbies", h) for h in spec.hobbies)
        character += f" She is into {joined}."

    traits = spec.traits()
    if traits:
        character += f" Core traits: {', '.join(traits)}."

    parts = [appearance, character]
    if spec.extra_details and spec.extra_details.strip():
        parts.append(f"Also true about her: {spec.extra_details.strip()}")
    return "\n".join(parts)


def personality_blob(spec: PersonaSpec, template: Any) -> dict[str, Any]:
    """The ``companions.personality`` JSONB written at genesis for this spec.

    Keeps the template metadata genesis already stored, but replaces
    ``description`` with the spec-derived paragraph and keeps the raw spec so the
    wizard can be re-opened prefilled.
    """
    return {
        "template_id": template.id,
        "name": template.name,
        "description": to_persona_description(spec),
        "traits": spec.traits() or list(template.traits),
        "baseline_tone": spec.tone() or template.baseline_tone,
        "spec": spec.model_dump(),
    }
