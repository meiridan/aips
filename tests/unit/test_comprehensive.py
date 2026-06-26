"""Comprehensive deterministic unit suite (100+ cases) across the codebase.

No network, no DB — pure logic. Covers memory namespacing & config parsing,
prompt building, LLM tier resolution & schema validation, settings defaults,
ORM model shape, orchestrator constants, and leak-detection helpers.

Run:  uv run pytest tests/unit/test_comprehensive.py -v
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

# ───────────────────────── memory: _scope namespacing ─────────────────────────


@pytest.mark.parametrize("seed", range(8))
def test_scope_namespacing(seed):
    from maya.memory.service import _scope

    uid, cid = uuid.uuid4(), uuid.uuid4()
    s = _scope(uid, cid)
    assert s == {"user_id": str(uid), "agent_id": str(cid)}
    assert isinstance(s["user_id"], str) and isinstance(s["agent_id"], str)


# ───────────────────────── memory: _parse_db_url ─────────────────────────

_DB_CASES = [
    ("postgresql+asyncpg://u:p@h:5433/db", "u", "p", "h", 5433, "db"),
    ("postgresql://alice:secret@db.host:5432/maya", "alice", "secret", "db.host", 5432, "maya"),
    ("postgresql+asyncpg://postgres:postgres@localhost:5432/maya", "postgres", "postgres", "localhost", 5432, "maya"),
    ("postgresql+asyncpg://neon:pw@ep.neon.tech:5432/neondb", "neon", "pw", "ep.neon.tech", 5432, "neondb"),
    ("", "postgres", "postgres", "localhost", 5432, "maya"),
    ("postgresql+asyncpg://x:y@host:1/onechar", "x", "y", "host", 1, "onechar"),
    ("postgresql://USER:Pa55@10.0.0.1:6543/prod", "USER", "Pa55", "10.0.0.1", 6543, "prod"),
    ("postgresql+asyncpg://a:b@c:5432/maya?ssl=require", "a", "b", "c", 5432, "maya"),
]


@pytest.mark.parametrize("url,user,pw,host,port,dbname", _DB_CASES)
def test_parse_db_url(monkeypatch, url, user, pw, host, port, dbname):
    monkeypatch.setenv("DATABASE_URL", url)
    from maya.memory.config import _parse_db_url

    got = _parse_db_url()
    assert got["user"] == user
    assert got["password"] == pw
    assert got["host"] == host
    assert got["port"] == port
    assert got["dbname"] == dbname


@pytest.mark.parametrize("missing", ["user", "password", "host", "port", "dbname"])
def test_parse_db_url_keys_present(monkeypatch, missing):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    from maya.memory.config import _parse_db_url

    assert missing in _parse_db_url()


# ───────────────────────── memory: build_mem0_config ─────────────────────────


@pytest.fixture()
def _cfg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/maya")
    from maya.memory.config import build_mem0_config

    return build_mem0_config()


def test_cfg_vector_provider(_cfg):
    assert _cfg["vector_store"]["provider"] == "pgvector"


def test_cfg_collection_name(_cfg):
    assert _cfg["vector_store"]["config"]["collection_name"] == "maya_memories"


def test_cfg_embedding_dims(_cfg):
    assert _cfg["vector_store"]["config"]["embedding_model_dims"] == 1536


def test_cfg_llm_provider(_cfg):
    assert _cfg["llm"]["provider"] == "openai"


def test_cfg_llm_model(_cfg):
    assert _cfg["llm"]["config"]["model"] == "gpt-4o-mini"


def test_cfg_embedder_model(_cfg):
    assert _cfg["embedder"]["config"]["model"] == "text-embedding-3-small"


def test_cfg_version(_cfg):
    assert _cfg["version"] == "v1.1"


def test_cfg_db_merged(_cfg):
    vc = _cfg["vector_store"]["config"]
    assert vc["host"] == "h" and vc["dbname"] == "maya" and vc["port"] == 5432


# ───────────────────────── prompt_builder: format_memories ─────────────────────────

_EMPTY = "(nothing yet — this is a new conversation)"


def test_format_memories_empty():
    from maya.conversation.prompt_builder import format_memories

    assert format_memories([]) == _EMPTY


def test_format_memories_all_blank_text():
    from maya.conversation.prompt_builder import format_memories

    assert format_memories([{"text": "  "}, {"text": ""}]) == _EMPTY


def test_format_memories_single_plain():
    from maya.conversation.prompt_builder import format_memories

    assert format_memories([{"text": "likes coffee"}]) == "- likes coffee"


@pytest.mark.parametrize("score,frag", [
    (0.5, "(relevance: 0.50)"),
    (0.375, "(relevance: 0.38)"),
    (1.0, "(relevance: 1.00)"),
    (0, "(relevance: 0.00)"),
    (0.999, "(relevance: 1.00)"),
])
def test_format_memories_score(score, frag):
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "x", "score": score}])
    assert frag in out


@pytest.mark.parametrize("score", ["high", None, "0.5", [], {}])
def test_format_memories_nonnumeric_score_omitted(score):
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "x", "score": score}])
    assert "relevance" not in out


def test_format_memories_timestamp():
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "x", "created_at": "2026-06-23T08:46:34Z"}])
    assert "[stored: 2026-06-23 08:46:34]" in out


def test_format_memories_no_timestamp_when_missing():
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "x"}])
    assert "stored" not in out


def test_format_memories_multiple_lines():
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "a"}, {"text": "b"}, {"text": "c"}])
    assert out.count("\n") == 2
    assert out.splitlines() == ["- a", "- b", "- c"]


def test_format_memories_skips_blank_among_valid():
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "a"}, {"text": ""}, {"text": "b"}])
    assert out == "- a\n- b"


def test_format_memories_rtl_text_preserved():
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "שם המשתמש עידן"}])
    assert "עידן" in out


def test_format_memories_strips_whitespace():
    from maya.conversation.prompt_builder import format_memories

    assert format_memories([{"text": "  hi  "}]) == "- hi"


def test_format_memories_score_and_timestamp_order():
    from maya.conversation.prompt_builder import format_memories

    out = format_memories([{"text": "x", "score": 0.5, "created_at": "2026-01-01T00:00:00"}])
    assert out.index("relevance") < out.index("stored")


# ───────────────────────── prompt_builder: build_basic ─────────────────────────


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


def test_build_basic_returns_list():
    from maya.conversation.prompt_builder import build_basic

    assert isinstance(build_basic([], []), list)


def test_build_basic_first_is_system():
    from maya.conversation.prompt_builder import build_basic

    out = build_basic([], [])
    assert out[0]["role"] == "system"


def test_build_basic_includes_memories_block():
    from maya.conversation.prompt_builder import build_basic

    out = build_basic([{"text": "loves dogs"}], [])
    assert "loves dogs" in out[0]["content"]


def test_build_basic_empty_memories_placeholder():
    from maya.conversation.prompt_builder import build_basic

    out = build_basic([], [])
    assert _EMPTY in out[0]["content"]


@pytest.mark.parametrize("n", [0, 1, 2, 5, 10])
def test_build_basic_message_count(n):
    from maya.conversation.prompt_builder import build_basic

    msgs = [_msg("user", f"m{i}") for i in range(n)]
    out = build_basic([], msgs)
    assert len(out) == n + 1  # +1 system


def test_build_basic_preserves_roles():
    from maya.conversation.prompt_builder import build_basic

    msgs = [_msg("user", "hi"), _msg("assistant", "hey")]
    out = build_basic([], msgs)
    assert [m["role"] for m in out[1:]] == ["user", "assistant"]


def test_build_basic_preserves_content():
    from maya.conversation.prompt_builder import build_basic

    out = build_basic([], [_msg("user", "specific text 123")])
    assert out[1]["content"] == "specific text 123"


# ───────────────────────── prompt_builder: system template ─────────────────────────


@pytest.mark.parametrize("needle", [
    "Maya", "warm", "remember", "character", "{memories}",
])
def test_system_template_contains(needle):
    from maya.conversation.prompt_builder import SYSTEM_PROMPT_TEMPLATE

    assert needle in SYSTEM_PROMPT_TEMPLATE


def test_system_template_formats():
    from maya.conversation.prompt_builder import SYSTEM_PROMPT_TEMPLATE

    out = SYSTEM_PROMPT_TEMPLATE.format(memories="X")
    assert "{memories}" not in out and "X" in out


# ───────────────────────── llm: tier resolution ─────────────────────────


@pytest.mark.parametrize("tier", ["main", "cheap", "fast"])
def test_llm_known_tiers(tier):
    from maya.llm.service import LLMService

    assert tier in LLMService()._tiers


@pytest.mark.parametrize("tier", ["main", "cheap", "fast"])
def test_llm_tier_nonempty(tier):
    from maya.llm.service import LLMService

    assert len(LLMService()._tiers[tier]) >= 1


def test_llm_main_primary_is_grok():
    from maya.llm.service import LLMService

    assert LLMService()._tiers["main"][0] == "xai/grok-3"


def test_llm_main_has_fallbacks():
    from maya.llm.service import LLMService

    assert len(LLMService()._tiers["main"]) >= 2


@pytest.mark.parametrize("tier", ["unknown", "", "MAIN", "premium"])
def test_llm_unknown_tier_lookup_none(tier):
    from maya.llm.service import LLMService

    assert LLMService()._tiers.get(tier) is None


def test_llm_custom_tiers_injection():
    from maya.llm.service import LLMService

    svc = LLMService(tier_models={"x": ["m1"]})
    assert svc._tiers == {"x": ["m1"]}


# ───────────────────────── llm: _validate_schema ─────────────────────────


@pytest.mark.parametrize("data,required,ok", [
    ({"a": 1}, ["a"], True),
    ({"a": 1, "b": 2}, ["a", "b"], True),
    ({"a": 1}, [], True),
    ({}, [], True),
    ({"a": 1}, ["b"], False),
    ({"a": 1}, ["a", "b"], False),
    ({}, ["a"], False),
    ({"x": None}, ["x"], True),
])
def test_validate_schema(data, required, ok):
    from maya.llm.service import LLMService

    if ok:
        LLMService._validate_schema(data, {"required": required})
    else:
        with pytest.raises(ValueError):
            LLMService._validate_schema(data, {"required": required})


def test_validate_schema_no_required_key():
    from maya.llm.service import LLMService

    LLMService._validate_schema({"a": 1}, {})  # no "required" → passes


# ───────────────────────── config: settings ─────────────────────────


def _settings():
    from maya.config import Settings

    return Settings(_env_file=None)


@pytest.mark.parametrize("attr,val", [
    ("redis_url", ""),
    ("environment", "local"),
    ("litellm_log", "ERROR"),
    ("upstash_redis_rest_url", ""),
    ("upstash_redis_rest_token", ""),
    ("xai_api_key", ""),
    ("openai_api_key", ""),
    ("anthropic_api_key", ""),
    ("maya_user_id", None),
    ("maya_companion_id", None),
])
def test_settings_field_defaults(attr, val):
    # Declared field defaults, independent of .env / OS env.
    from maya.config import Settings

    assert Settings.model_fields[attr].default == val


def test_settings_database_url_default():
    from maya.config import Settings

    assert "localhost:5432/maya" in Settings.model_fields["database_url"].default


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    from maya.config import Settings

    assert Settings(_env_file=None).environment == "prod"


def test_settings_ignores_extra(monkeypatch):
    monkeypatch.setenv("TOTALLY_UNKNOWN_VAR", "x")
    _settings()  # extra="ignore" → no error


# ───────────────────────── db: model shape ─────────────────────────


@pytest.mark.parametrize("model,table", [
    ("User", "users"),
    ("Companion", "companions"),
    ("Message", "messages"),
    ("Memory", "memories"),
    ("LLMCall", "llm_calls"),
])
def test_model_tablenames(model, table):
    import maya.db.models as m

    assert getattr(m, model).__tablename__ == table


@pytest.mark.parametrize("col", ["id", "companion_id", "user_id", "role", "content", "metadata", "created_at"])
def test_message_columns(col):
    from maya.db.models import Message

    assert col in Message.__table__.columns.keys()


@pytest.mark.parametrize("col", ["id", "name", "description", "timezone", "created_at"])
def test_user_columns(col):
    from maya.db.models import User

    assert col in User.__table__.columns.keys()


@pytest.mark.parametrize("col", ["id", "user_id", "name", "template_id", "created_at"])
def test_companion_columns(col):
    from maya.db.models import Companion

    assert col in Companion.__table__.columns.keys()


def test_message_role_attr_maps_to_metadata_column():
    from maya.db.models import Message

    # attribute is `extra`, DB column is `metadata`
    assert "metadata" in Message.__table__.columns.keys()
    assert hasattr(Message, "extra")


def test_llmcall_cost_columns():
    from maya.db.models import LLMCall

    cols = LLMCall.__table__.columns.keys()
    for c in ("model", "tier", "input_tokens", "output_tokens", "cost_usd", "latency_ms", "success", "purpose"):
        assert c in cols


# ───────────────────────── orchestrator: constants ─────────────────────────


def test_recent_limit_enlarged():
    from maya.conversation.orchestrator import RECENT_LIMIT

    assert RECENT_LIMIT == 30


def test_memory_limit_enlarged():
    from maya.conversation.orchestrator import MEMORY_LIMIT

    assert MEMORY_LIMIT == 15


def test_orchestrator_exports():
    from maya.conversation import orchestrator as o

    assert hasattr(o, "Orchestrator")
    assert callable(o.Orchestrator)


def test_web_imports_shared_constants():
    # regression: web prod path must use the shared constants, not hardcoded 3/10
    import maya.web as w
    from maya.conversation.orchestrator import MEMORY_LIMIT, RECENT_LIMIT

    assert w.RECENT_LIMIT == RECENT_LIMIT == 30
    assert w.MEMORY_LIMIT == MEMORY_LIMIT == 15


# ───────────────────────── leak-detection helper (regression logic) ─────────────────────────

MAYA_LEAK_TOKENS = ["yaheli", "ofri", "dor", "har adar", "divorced", "blonde", "45"]


def _leaked(mem_texts):
    blob = " ".join(t.lower() for t in mem_texts)
    return [t for t in MAYA_LEAK_TOKENS if t in blob]


@pytest.mark.parametrize("texts,expect", [
    (["User works at Radware"], []),
    (["User name is Idan"], []),
    (["User has kids Arbel, Kinneret, Marom"], []),
    (["User is 45 years old"], ["45"]),
    (["User lived in Har Adar"], ["har adar"]),
    (["User has children Yaheli, Ofri, Dor"], ["yaheli", "ofri", "dor"]),
    (["User is divorced and blonde"], ["divorced", "blonde"]),
    (["Idan works at Radware", "User likes coffee"], []),
])
def test_leak_detection(texts, expect):
    assert _leaked(texts) == expect


def test_clean_user_memory_has_no_leak():
    clean = ["User name is Idan", "Works at Radware", "Wife named Reut",
             "Kids Arbel, Kinneret, Marom", "Loves spicy hamburgers"]
    assert _leaked(clean) == []
