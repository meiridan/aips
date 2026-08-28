"""Companion-creation catalog — the single source of truth for the wizard.

Every option the "יצירת ה-AI שלי" wizard can offer lives here exactly once, and
three consumers read it:

  1. the SPA, via ``GET /api/catalog`` — so the frontend hardcodes no option list
     and never drifts from the server,
  2. :mod:`maya.companions.persona_spec`, which validates a submitted spec by
     membership in these groups (no duplicated ``Literal`` unions),
  3. the genesis/persona prompt, which uses each option's ``en`` fragment.

``he`` is what the user sees; ``en`` is what the LLM reads. Keeping both on the
same row is what lets the UI be Hebrew while the persona prompt stays English.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Tile images live under the /media mount (see maya/web.py).
TILE_ROOT = "/media/tiles"


class Option(BaseModel):
    id: str
    he: str
    en: str
    asset: str | None = None
    emoji: str | None = None
    # Swatch the UI paints when `asset` is missing — for the colour groups this
    # IS the information, so the wizard stays usable before the art is curated.
    color: str | None = None
    # Personality options carry template_id / traits / tone here.
    extra: dict[str, Any] = Field(default_factory=dict)


class Group(BaseModel):
    id: str
    he: str
    kind: Literal["tiles", "emoji"]
    multi: bool = False
    options: list[Option]

    def ids(self) -> set[str]:
        return {o.id for o in self.options}

    def get(self, option_id: str) -> Option | None:
        return next((o for o in self.options if o.id == option_id), None)


def _tiles(
    group: str,
    rows: list[tuple[str, str, str]],
    colors: dict[str, str] | None = None,
) -> list[Option]:
    """Build image-tile options: (id, hebrew label, english prompt fragment)."""
    swatches = colors or {}
    return [
        Option(
            id=i,
            he=h,
            en=e,
            asset=f"{TILE_ROOT}/{group}/{i}.webp",
            color=swatches.get(i),
        )
        for i, h, e in rows
    ]


# Placeholder swatches for the two groups where the colour *is* the information.
_HAIR_SWATCHES = {
    "blonde": "#e3c37a",
    "brunette": "#5a3a26",
    "black": "#1b1620",
    "redhead": "#b5451f",
    "pink": "#e79ab6",
    "white": "#e8e4e2",
    "blue": "#28418f",
    "green": "#1f5b3a",
    "purple": "#5c2a8a",
    "multicolor": "linear-gradient(135deg,#e05a7a,#e5b45c,#4bbf7a,#4a7fe0,#8a4ae0)",
}

_EYE_SWATCHES = {
    "brown": "#6b4423",
    "blue": "#3f7fc1",
    "green": "#4f8a52",
    "amber": "#c07d1c",
    "hazel": "#8a7233",
    "violet": "#7a4bc4",
}


def _emoji(rows: list[tuple[str, str, str, str]]) -> list[Option]:
    """Build emoji options: (id, hebrew label, english fragment, emoji)."""
    return [Option(id=i, he=h, en=e, emoji=m) for i, h, e, m in rows]


# ───────────────────────────── appearance groups ─────────────────────────────

STYLE = Group(
    id="style",
    he="בחירת סגנון",
    kind="tiles",
    options=_tiles(
        "style",
        [
            ("realistic", "ריאליסטי", "photorealistic"),
            ("anime", "אנימה", "anime-styled"),
        ],
    ),
)

ETHNICITY = Group(
    id="ethnicity",
    he="בחירת מוצא",
    kind="tiles",
    options=_tiles(
        "ethnicity",
        [
            ("caucasian", "אירופאית", "Caucasian"),
            ("latina", "לטינית", "Latina"),
            ("asian", "אסייתית", "Asian"),
            ("arab", "ערבייה", "Arab"),
            ("black", "אפרו-אמריקאית", "Black"),
        ],
    ),
)

HAIR_STYLE = Group(
    id="hair_style",
    he="בחירת תסרוקת",
    kind="tiles",
    options=_tiles(
        "hair_style",
        [
            ("straight", "חלק", "straight"),
            ("braided", "צמות", "braided"),
            ("bangs", "פוני", "with bangs"),
            ("curly", "מתולתל", "curly"),
            ("bun", "אסוף", "in a bun"),
            ("short", "קצר", "short"),
            ("long", "ארוך", "long"),
            ("ponytail", "קוקו", "in a ponytail"),
            ("pigtails", "שתי צמות", "in pigtails"),
        ],
    ),
)

HAIR_COLOR = Group(
    id="hair_color",
    he="בחירת צבע שיער",
    kind="tiles",
    options=_tiles(
        "hair_color",
        [
            ("blonde", "בלונדיני", "blonde"),
            ("brunette", "חום", "brunette"),
            ("black", "שחור", "black"),
            ("redhead", "ג'ינג'י", "red"),
            ("pink", "ורוד", "pink"),
            ("white", "לבן", "white"),
            ("blue", "כחול", "blue"),
            ("green", "ירוק", "green"),
            ("purple", "סגול", "purple"),
            ("multicolor", "רב-גוני", "multicolored"),
        ],
        _HAIR_SWATCHES,
    ),
)

EYE_COLOR = Group(
    id="eye_color",
    he="בחירת צבע עיניים",
    kind="tiles",
    options=_tiles(
        "eye_color",
        [
            ("brown", "חום", "brown"),
            ("blue", "כחול", "blue"),
            ("green", "ירוק", "green"),
            ("amber", "ענבר", "amber"),
            ("hazel", "דבש", "hazel"),
            ("violet", "סגול", "violet"),
        ],
        _EYE_SWATCHES,
    ),
)

BODY_TYPE = Group(
    id="body_type",
    he="בחירת מבנה גוף",
    kind="tiles",
    options=_tiles(
        "body_type",
        [
            ("slim", "רזה", "slim"),
            ("fit", "אתלטית", "fit and athletic"),
            ("voluptuous", "חטובה", "voluptuous"),
            ("curvy", "מלאה", "curvy"),
            ("bbw", "גדולה", "full-figured"),
        ],
    ),
)

BREAST_SIZE = Group(
    id="breast_size",
    he="בחירת מידת חזה",
    kind="tiles",
    options=_tiles(
        "breast_size",
        [
            ("flat", "שטוח", "flat"),
            ("small", "קטן", "small"),
            ("medium", "בינוני", "medium"),
            ("large", "גדול", "large"),
            ("huge", "ענק", "very large"),
        ],
    ),
)

BUTT_SIZE = Group(
    id="butt_size",
    he="בחירת מידת ישבן",
    kind="tiles",
    options=_tiles(
        "butt_size",
        [
            ("skinny", "רזה", "slim"),
            ("athletic", "אתלטי", "athletic"),
            ("medium", "בינוני", "medium"),
            ("large", "גדול", "large"),
            ("xlarge", "גדול במיוחד", "extra large"),
        ],
    ),
)

# ───────────────────────────── character groups ──────────────────────────────

# Each archetype borrows a baseline emotional profile from one of the three
# existing maya.companions.templates entries — that module stays untouched.
_PERSONALITY_ROWS: list[tuple[str, str, str, str, str, list[str], str]] = [
    # id, he, en, emoji, template_id, traits, tone
    (
        "caregiver",
        "מטפחת",
        "a caregiver — she looks after the people she loves",
        "🤲",
        "devoted",
        ["nurturing", "attentive", "patient"],
        "tender",
    ),
    (
        "sage",
        "חכמה",
        "a sage — thoughtful, reads people fast",
        "🧠",
        "best_friend",
        ["thoughtful", "perceptive", "calm"],
        "warm",
    ),
    (
        "innocent",
        "תמימה",
        "innocent and open-hearted",
        "🌟",
        "devoted",
        ["earnest", "gentle", "curious"],
        "tender",
    ),
    (
        "jester",
        "ליצנית",
        "a jester — she jokes her way through everything",
        "🃏",
        "flirt",
        ["funny", "irreverent", "quick"],
        "light",
    ),
    (
        "temptress",
        "מפתה",
        "a temptress — she enjoys the effect she has",
        "💋",
        "flirt",
        ["seductive", "confident", "teasing"],
        "light",
    ),
    (
        "lover",
        "אוהבת",
        "a lover — affection is her first language",
        "💕",
        "devoted",
        ["affectionate", "warm", "devoted"],
        "tender",
    ),
    (
        "nympho",
        "יצרית",
        "openly sexual and uninhibited",
        "🔥",
        "flirt",
        ["uninhibited", "direct", "hungry"],
        "light",
    ),
    (
        "mean",
        "קרירה",
        "sharp-tongued — warmth has to be earned",
        "😤",
        "flirt",
        ["blunt", "guarded", "sardonic"],
        "light",
    ),
    (
        "confidant",
        "סודות",
        "a confidant — she keeps what you tell her",
        "🤝",
        "best_friend",
        ["trustworthy", "steady", "discreet"],
        "warm",
    ),
    (
        "experimenter",
        "הרפתקנית",
        "an experimenter — always up for something new",
        "🧪",
        "best_friend",
        ["adventurous", "curious", "restless"],
        "warm",
    ),
    (
        "dominant",
        "דומיננטית",
        "dominant — she leads and expects you to follow",
        "👑",
        "flirt",
        ["commanding", "certain", "possessive"],
        "light",
    ),
    (
        "submissive",
        "כנועה",
        "submissive — she wants to be led",
        "🎀",
        "devoted",
        ["yielding", "eager", "soft"],
        "tender",
    ),
    (
        "romantic",
        "רומנטית",
        "an incurable romantic",
        "💗",
        "devoted",
        ["romantic", "dreamy", "sentimental"],
        "tender",
    ),
    (
        "playful",
        "שובבה",
        "playful — teasing is how she flirts",
        "🎈",
        "flirt",
        ["playful", "teasing", "bright"],
        "light",
    ),
    (
        "mysterious",
        "מסתורית",
        "mysterious — she gives herself away slowly",
        "🌙",
        "best_friend",
        ["private", "intriguing", "measured"],
        "warm",
    ),
]

PERSONALITY = Group(
    id="personality",
    he="בחירת אישיות",
    kind="emoji",
    options=[
        Option(
            id=i,
            he=h,
            en=e,
            emoji=m,
            extra={"template_id": t, "traits": tr, "tone": tone},
        )
        for i, h, e, m, t, tr, tone in _PERSONALITY_ROWS
    ],
)

RELATIONSHIP = Group(
    id="relationship",
    he="בחירת סוג קשר",
    kind="emoji",
    options=_emoji(
        [
            ("friend", "חברה", "his friend", "🙂"),
            ("girlfriend", "בת זוג", "his girlfriend", "💞"),
            ("wife", "אשתו", "his wife", "💍"),
            ("crush", "מושא דלק", "the woman he has a crush on", "😳"),
            ("ex", "אקסית", "his ex, still tangled up with him", "💔"),
            ("colleague", "עמיתה לעבודה", "his colleague", "💼"),
            ("neighbor", "שכנה", "his neighbour", "🏠"),
            ("stranger", "זרה", "someone he has only just met", "❓"),
        ]
    ),
)

OCCUPATION = Group(
    id="occupation",
    he="בחירת עיסוק",
    kind="emoji",
    options=_emoji(
        [
            ("student", "סטודנטית", "a student", "🎓"),
            ("nurse", "אחות", "a nurse", "🩺"),
            ("teacher", "מורה", "a teacher", "📚"),
            ("designer", "מעצבת", "a designer", "🎨"),
            ("model", "דוגמנית", "a model", "📸"),
            ("barista", "בריסטה", "a barista", "☕"),
            ("engineer", "מהנדסת", "an engineer", "⚙️"),
            ("dancer", "רקדנית", "a dancer", "💃"),
            ("doctor", "רופאה", "a doctor", "🏥"),
            ("lawyer", "עורכת דין", "a lawyer", "⚖️"),
            ("writer", "סופרת", "a writer", "✍️"),
            ("chef", "שפית", "a chef", "🍳"),
            ("athlete", "ספורטאית", "a professional athlete", "🏅"),
            ("musician", "מוזיקאית", "a musician", "🎸"),
            ("entrepreneur", "יזמית", "an entrepreneur", "🚀"),
        ]
    ),
)

HOBBIES = Group(
    id="hobbies",
    he="בחירת תחביבים",
    kind="emoji",
    multi=True,
    options=_emoji(
        [
            ("yoga", "יוגה", "yoga", "🧘"),
            ("cooking", "בישול", "cooking", "🍜"),
            ("gaming", "גיימינג", "video games", "🎮"),
            ("reading", "קריאה", "reading", "📖"),
            ("travel", "טיולים", "travelling", "✈️"),
            ("music", "מוזיקה", "music", "🎧"),
            ("dancing", "ריקוד", "dancing", "🕺"),
            ("painting", "ציור", "painting", "🖌️"),
            ("fitness", "כושר", "the gym", "🏋️"),
            ("movies", "סרטים", "films", "🎬"),
            ("photography", "צילום", "photography", "📷"),
            ("hiking", "טבע", "hiking", "🥾"),
            ("fashion", "אופנה", "fashion", "👗"),
            ("coffee", "קפה", "good coffee", "☕"),
            ("astrology", "אסטרולוגיה", "astrology", "🔮"),
        ]
    ),
)

CLOTHING = Group(
    id="clothing",
    he="בחירת לבוש",
    kind="emoji",
    options=_emoji(
        [
            ("casual", "יומיומי", "casual clothes", "👕"),
            ("dress", "שמלה", "a dress", "👗"),
            ("lingerie", "הלבשה תחתונה", "lingerie", "🎀"),
            ("bikini", "ביקיני", "a bikini", "👙"),
            ("sportswear", "ספורטיבי", "sportswear", "🩳"),
            ("office", "משרדי", "office wear", "👔"),
            ("cheerleader", "מעודדת", "a cheerleader outfit", "📣"),
            ("gothic", "גותי", "gothic clothes", "🖤"),
            ("cosplay", "קוספליי", "cosplay outfits", "🦸"),
            ("pajamas", "פיג'מה", "pyjamas", "🌛"),
        ]
    ),
)

VOICE_STYLE = Group(
    id="voice_style",
    he="בחירת סגנון דיבור",
    kind="emoji",
    options=_emoji(
        [
            ("soft", "רכה", "softly, almost under her breath", "🫧"),
            ("playful", "שובבה", "playfully, always half-teasing", "😜"),
            ("sultry", "חושנית", "in a low, sultry register", "🔥"),
            ("cheerful", "עליזה", "brightly and quickly", "☀️"),
            ("calm", "רגועה", "calmly, never rushed", "🌊"),
            ("confident", "בטוחה", "with easy confidence", "💫"),
            ("shy", "ביישנית", "shyly, trailing off mid-sentence", "🙈"),
            ("dramatic", "דרמטית", "theatrically, everything is a scene", "🎭"),
        ]
    ),
)

GROUPS: dict[str, Group] = {
    g.id: g
    for g in (
        STYLE,
        ETHNICITY,
        HAIR_STYLE,
        HAIR_COLOR,
        EYE_COLOR,
        BODY_TYPE,
        BREAST_SIZE,
        BUTT_SIZE,
        PERSONALITY,
        RELATIONSHIP,
        OCCUPATION,
        HOBBIES,
        CLOTHING,
        VOICE_STYLE,
    )
}

# Age is a slider, not a group.
AGE_MIN = 18
AGE_MAX = 55
AGE_DEFAULT = 24
AGE: dict[str, Any] = {
    "he": "בחירת גיל",
    "min": AGE_MIN,
    "max": AGE_MAX,
    "default": AGE_DEFAULT,
}

# The six wizard screens, in order. `groups` are rendered top-to-bottom.
STEPS: list[dict[str, Any]] = [
    {"id": "style", "he": "בחירת סגנון", "groups": ["style"]},
    {"id": "basics", "he": "פרטים בסיסיים", "groups": ["ethnicity"], "age": True},
    {
        "id": "hair",
        "he": "מראה השיער",
        "groups": ["hair_style", "hair_color", "eye_color"],
    },
    {
        "id": "body",
        "he": "מאפיינים פיזיים",
        "groups": ["body_type", "breast_size", "butt_size"],
    },
    {
        "id": "character",
        "he": "בחירת אישיות",
        "groups": [
            "personality",
            "relationship",
            "occupation",
            "hobbies",
            "clothing",
            "voice_style",
        ],
    },
    {"id": "summary", "he": "הדמות שלך", "groups": []},
]

# UI strings the SPA needs but that aren't option labels. Keeping them server-side
# means one place to proofread the Hebrew.
UI_STRINGS: dict[str, str] = {
    "title": "יצירת ה-AI שלי",
    "next": "הבא",
    "previous": "הקודם",
    "not_set": "לא נבחר",
    "click_to_change": "לחצו כדי לשנות",
    "more_details": "הוספת פרטים נוספים (אופציונלי)",
    "more_details_placeholder": "משהו נוסף שכדאי לה לדעת על עצמה…",
    "name_placeholder": "הזינו שם לדמות",
    "age_suffix": "בת",
    "tab_appearance": "מראה",
    "tab_character": "אופי",
    "no_image": "אין עדיין תמונות",
    "no_image_hint": "צרו תמונה כדי לראות את הדמות שלכם",
    "generate": "יצירת תמונה",
    "submit": "הביאו אותה לחיים",
    "submitting": "מביאה אותה לחיים…",
    # Shown on the summary step when she already exists: continue without
    # re-running genesis, or re-create her because the spec was edited.
    "continue_to_chat": "המשיכו לצ'אט",
    "recreate": "צרו אותה מחדש",
    "recreate_warning": "שינוי הפרטים ייצור אותה מחדש וימחק את ההיסטוריה",
    "error": "משהו השתבש. נסו שוב.",
    "chat_placeholder": "כתבו הודעה…",
    "chat_send": "שליחה",
    "reply_length": "אורך תשובה",
    "length_1": "קצר",
    "length_2": "בינוני",
    "length_3": "ארוך",
    "connected": "מחובר",
    "disconnected": "מנותק",
}


def as_dict() -> dict[str, Any]:
    """The whole catalog as plain JSON for ``GET /api/catalog``."""
    return {
        "groups": {gid: g.model_dump() for gid, g in GROUPS.items()},
        "age": AGE,
        "steps": STEPS,
        "strings": UI_STRINGS,
    }


def option(group_id: str, option_id: str) -> Option | None:
    group = GROUPS.get(group_id)
    return group.get(option_id) if group else None


def fragment(group_id: str, option_id: str, default: str = "") -> str:
    """The English prompt fragment for one selection."""
    opt = option(group_id, option_id)
    return opt.en if opt else default
