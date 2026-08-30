"""Catalog integrity + PersonaSpec validation and rendering."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maya.companions import catalog
from maya.companions.persona_spec import (
    PersonaSpec,
    personality_blob,
    to_persona_description,
)
from maya.companions.templates import TEMPLATES, get_template


def _spec(**overrides: object) -> PersonaSpec:
    base: dict = {
        "name": "מאיה",
        "age": 24,
        "style": "realistic",
        "ethnicity": "arab",
        "hair_style": "long",
        "hair_color": "blue",
        "eye_color": "hazel",
        "body_type": "curvy",
        "breast_size": "large",
        "butt_size": "large",
        "personality": "caregiver",
        "relationship": "girlfriend",
        "occupation": "nurse",
        "clothing": "cheerleader",
        "voice_style": "soft",
        "hobbies": ["yoga", "cooking"],
    }
    base.update(overrides)
    return PersonaSpec(**base)


# ───────────────────────────────── catalog ──────────────────────────────────


def test_every_option_has_both_languages():
    for gid, group in catalog.GROUPS.items():
        assert group.he.strip(), f"group {gid} has no Hebrew title"
        assert group.options, f"group {gid} is empty"
        for opt in group.options:
            assert opt.he.strip(), f"{gid}.{opt.id} has no Hebrew label"
            assert opt.en.strip(), f"{gid}.{opt.id} has no English fragment"


def test_option_ids_unique_within_group():
    for gid, group in catalog.GROUPS.items():
        ids = [o.id for o in group.options]
        assert len(ids) == len(set(ids)), f"duplicate ids in {gid}"


def test_tile_groups_carry_assets_and_emoji_groups_carry_emoji():
    for gid, group in catalog.GROUPS.items():
        for opt in group.options:
            if group.kind == "tiles":
                assert opt.asset and opt.asset.startswith(catalog.TILE_ROOT), gid
            else:
                assert opt.emoji, f"{gid}.{opt.id} has no emoji"


def test_personalities_map_to_real_templates():
    for opt in catalog.PERSONALITY.options:
        template_id = opt.extra["template_id"]
        assert template_id in TEMPLATES, f"{opt.id} → unknown template {template_id}"
        assert opt.extra["traits"], opt.id
        assert opt.extra["tone"], opt.id


def test_steps_reference_real_groups():
    for step in catalog.STEPS:
        for gid in step["groups"]:
            assert gid in catalog.GROUPS, f"step {step['id']} → unknown group {gid}"


def test_every_group_appears_in_exactly_one_step():
    seen = [gid for step in catalog.STEPS for gid in step["groups"]]
    assert sorted(seen) == sorted(catalog.GROUPS)


def test_as_dict_is_json_serializable():
    import json

    payload = json.loads(json.dumps(catalog.as_dict()))
    assert payload["age"]["min"] == catalog.AGE_MIN
    assert len(payload["steps"]) == 6
    assert payload["strings"]["submit"]


# ──────────────────────────────── PersonaSpec ────────────────────────────────


def test_valid_spec_round_trips():
    spec = _spec()
    assert PersonaSpec(**spec.model_dump()) == spec


@pytest.mark.parametrize(
    "overrides",
    [
        {"ethnicity": "martian"},
        {"personality": "nonexistent"},
        {"hobbies": ["yoga", "spelunking"]},
        {"age": 17},
        {"age": 99},
        {"name": "   "},
    ],
)
def test_invalid_spec_rejected(overrides):
    with pytest.raises(ValidationError):
        _spec(**overrides)


def test_name_is_stripped():
    assert _spec(name="  מאיה  ").name == "מאיה"


def test_template_and_traits_come_from_catalog():
    spec = _spec(personality="caregiver")
    assert spec.template_id() == "devoted"
    assert "nurturing" in spec.traits()
    assert spec.tone() == "tender"


def test_description_mentions_every_choice():
    text = to_persona_description(_spec())
    for fragment in ("24-year-old", "Arab", "long", "blue", "hazel", "curvy", "nurse"):
        assert fragment in text, fragment
    assert "yoga" in text and "cooking" in text


def test_extra_details_are_appended():
    text = to_persona_description(_spec(extra_details="היא שונאת בוקר"))
    assert "היא שונאת בוקר" in text


def test_personality_blob_overrides_template_description():
    spec = _spec()
    blob = personality_blob(spec, get_template(spec.template_id()))
    assert blob["template_id"] == "devoted"
    assert blob["description"] == to_persona_description(spec)
    assert blob["spec"]["ethnicity"] == "arab"


def test_colour_groups_carry_swatches():
    """Hair/eye colour tiles must render meaningfully before the art is curated."""
    for group in (catalog.HAIR_COLOR, catalog.EYE_COLOR):
        for opt in group.options:
            assert opt.color, f"{group.id}.{opt.id} has no swatch"


# ───────────────────────────────── presets ──────────────────────────────────


def test_every_preset_spec_is_a_valid_persona_spec():
    """A typo in PRESETS fails here, not at POST /api/companion."""
    for preset in catalog.PRESETS:
        spec = PersonaSpec(name=preset.name, preset=preset.id, **preset.spec)
        assert spec.name == preset.name
        assert spec.preset == preset.id


def test_preset_ids_are_unique():
    ids = [p.id for p in catalog.PRESETS]
    assert len(ids) == len(set(ids))


def test_presets_carry_hebrew_copy_and_asset_paths():
    for preset in catalog.PRESETS:
        assert preset.name.strip(), f"{preset.id} has no name"
        assert preset.tagline.strip(), f"{preset.id} has no tagline"
        assert preset.bio.strip(), f"{preset.id} has no bio"
        assert preset.voice_line.strip(), f"{preset.id} has no voice line"
        assert preset.portrait() == f"{catalog.PRESET_ROOT}/{preset.id}/portrait.webp"
        assert len(preset.gallery()) == catalog.GALLERY_SHOTS
        assert preset.voice() == f"{catalog.PRESET_ROOT}/{preset.id}/voice.mp3"


def test_preset_taglines_do_not_repeat_the_name():
    """The gallery renders name and tagline together, so the tagline is the
    trait alone — "מאיה — מאיה — ..." otherwise."""
    for preset in catalog.PRESETS:
        assert not preset.tagline.startswith(preset.name), f"{preset.id} repeats her name"


def test_preset_filters_are_real_single_choice_groups():
    """The gallery filters with `spec[group] == option`, which a multi-select
    group would silently never match."""
    for gid in catalog.PRESET_FILTERS:
        group = catalog.GROUPS.get(gid)
        assert group is not None, f"{gid} is not a catalog group"
        assert not group.multi, f"{gid} is multi-select and cannot be a filter"
        for preset in catalog.PRESETS:
            value = preset.spec.get(gid)
            assert isinstance(value, str), f"{preset.id} has no {gid} to filter on"
            assert catalog.option(gid, value) is not None


def test_preset_lookup():
    assert catalog.preset(catalog.PRESETS[0].id) is catalog.PRESETS[0]
    assert catalog.preset("nope") is None


def test_unknown_preset_is_rejected():
    with pytest.raises(ValidationError):
        _spec(preset="definitely-not-a-preset")


def test_preset_is_optional():
    """A wizard-built companion carries no preset id."""
    assert _spec().preset is None


def test_preset_descriptions_render():
    """Every ready-made companion produces a usable persona paragraph."""
    for preset in catalog.PRESETS:
        text = to_persona_description(
            PersonaSpec(name=preset.name, preset=preset.id, **preset.spec)
        )
        assert preset.name in text
        assert "She is" in text


# ──────────────────────────── avatar resolution ─────────────────────────────


def test_preset_portrait_beats_the_generic_avatar(tmp_path, monkeypatch):
    from maya.companions import avatars

    monkeypatch.setattr(avatars, "PRESET_DIR", tmp_path / "presets")
    monkeypatch.setattr(avatars, "AVATAR_DIR", tmp_path / "avatars")
    (tmp_path / "presets" / "maya").mkdir(parents=True)
    (tmp_path / "presets" / "maya" / "portrait.webp").write_bytes(b"x")
    (tmp_path / "avatars" / "realistic").mkdir(parents=True)
    (tmp_path / "avatars" / "realistic" / "arab.webp").write_bytes(b"x")

    assert avatars.resolve_avatar(_spec(preset="maya")) == "/media/presets/maya/portrait.webp"


def test_missing_preset_portrait_falls_back_to_the_old_chain(tmp_path, monkeypatch):
    from maya.companions import avatars

    monkeypatch.setattr(avatars, "PRESET_DIR", tmp_path / "presets")
    monkeypatch.setattr(avatars, "AVATAR_DIR", tmp_path / "avatars")
    (tmp_path / "avatars" / "realistic").mkdir(parents=True)
    (tmp_path / "avatars" / "realistic" / "arab.webp").write_bytes(b"x")

    assert avatars.resolve_avatar(_spec(preset="maya")) == "/media/avatars/realistic/arab.webp"


def test_bare_media_directory_still_resolves_to_none(tmp_path, monkeypatch):
    from maya.companions import avatars

    monkeypatch.setattr(avatars, "PRESET_DIR", tmp_path / "presets")
    monkeypatch.setattr(avatars, "AVATAR_DIR", tmp_path / "avatars")
    assert avatars.resolve_avatar(_spec(preset="maya")) is None
