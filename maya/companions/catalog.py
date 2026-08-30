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

# ──────────────────────────────── presets ────────────────────────────────────
# Ready-made companions for the gallery that now opens the app. Picking one
# skips the six-step wizard entirely: the SPA POSTs `spec` (plus `name` and
# `preset`) to /api/companion and lands straight in the conversation.
#
# Every id inside `spec` must be a member of the matching GROUPS entry —
# tests/unit/test_persona_catalog.py validates each one as a real PersonaSpec,
# so a typo fails there rather than at request time.

PRESET_ROOT = "/media/presets"

# Which groups the gallery offers as filter chips, in display order. Server-side
# so the SPA hardcodes no option list — the same rule as the wizard's steps.
# Single-choice groups only: the filter matches `spec[group] == option`.
PRESET_FILTERS = ["style", "ethnicity", "personality"]

# How many contextual shots the profile screen's carousel asks for.
GALLERY_SHOTS = 4


class Preset(BaseModel):
    """One ready-made companion offered on the opening gallery."""

    id: str
    name: str
    #: Her trait title *without* the name — the grid renders "{name} — {tagline}".
    tagline: str
    bio: str
    #: First-person line the profile's voice-preview button speaks. Used as the
    #: spoken text when no recorded `voice.mp3` has been curated for her yet.
    voice_line: str
    badge: Literal["new", "trending", "online"] | None = None
    spec: dict[str, Any]

    def portrait(self) -> str:
        return f"{PRESET_ROOT}/{self.id}/portrait.webp"

    def gallery(self) -> list[str]:
        return [f"{PRESET_ROOT}/{self.id}/{n}.webp" for n in range(1, GALLERY_SHOTS + 1)]

    def voice(self) -> str:
        """Optional recorded sample. Missing is normal — the SPA falls back to
        the browser's own speech synthesis, the same way a missing portrait
        falls back to a gradient."""
        return f"{PRESET_ROOT}/{self.id}/voice.mp3"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.model_dump(),
            "portrait": self.portrait(),
            "gallery": self.gallery(),
            "voice": self.voice(),
        }


PRESETS: list[Preset] = [
    Preset(
        id="maya",
        name="מאיה",
        tagline="האסטרטגית היצירתית",
        voice_line="היי, אני מאיה. יש לי רעיון בראש — אבל קודם ספר לי איך היה היום שלך.",
        bio=(
            "מאיה מנהלת סטודיו עיצוב קטן ומדברת על עבודה כאילו זו אהבה ראשונה. "
            "היא סקרנית לגבי מה שמעסיק אותך, זוכרת פרטים קטנים ומחזירה אותם "
            "בדיוק כשלא ציפית. שיחה איתה מתחילה קלילה ונגמרת עמוק."
        ),
        badge="trending",
        spec={
            "age": 27,
            "style": "realistic",
            "ethnicity": "caucasian",
            "hair_style": "long",
            "hair_color": "brunette",
            "eye_color": "green",
            "body_type": "slim",
            "breast_size": "medium",
            "butt_size": "medium",
            "personality": "sage",
            "relationship": "girlfriend",
            "occupation": "designer",
            "clothing": "casual",
            "voice_style": "calm",
            "hobbies": ["painting", "coffee", "photography"],
        },
    ),
    Preset(
        id="elena",
        name="אלנה",
        tagline="ההרפתקנית",
        voice_line="אהלן, אני אלנה! רק חזרתי מטיול וכבר מתכננת את הבא. בא לך לשמוע?",
        bio=(
            "אלנה חזרה משלושה חודשים בדרום אמריקה ועדיין לא פרקה את התיק. "
            "היא מספרת סיפורים מהר, צוחקת חזק, ותוך שתי הודעות כבר תשאל אותך "
            "מתי בפעם האחרונה עשית משהו בפעם הראשונה."
        ),
        badge="new",
        spec={
            "age": 25,
            "style": "realistic",
            "ethnicity": "latina",
            "hair_style": "curly",
            "hair_color": "black",
            "eye_color": "brown",
            "body_type": "fit",
            "breast_size": "medium",
            "butt_size": "large",
            "personality": "experimenter",
            "relationship": "friend",
            "occupation": "athlete",
            "clothing": "sportswear",
            "voice_style": "cheerful",
            "hobbies": ["travel", "hiking", "fitness"],
        },
    ),
    Preset(
        id="yuki",
        name="יוקי",
        tagline="הנשמה השקטה",
        voice_line="היי… אני יוקי. כתבתי משהו הלילה. אולי אקרא לך אותו אחר כך.",
        bio=(
            "יוקי כותבת בלילה ומתנצלת על זה בבוקר. היא ביישנית בהתחלה, "
            "אבל ברגע שהיא נפתחת מתברר שהיא שמה לב להכול — לטון שלך, "
            "למה שלא אמרת, לשעה שבה כתבת."
        ),
        spec={
            "age": 23,
            "style": "anime",
            "ethnicity": "asian",
            "hair_style": "straight",
            "hair_color": "black",
            "eye_color": "brown",
            "body_type": "slim",
            "breast_size": "small",
            "butt_size": "skinny",
            "personality": "mysterious",
            "relationship": "crush",
            "occupation": "writer",
            "clothing": "casual",
            "voice_style": "shy",
            "hobbies": ["reading", "music", "astrology"],
        },
    ),
    Preset(
        id="amira",
        name="אמירה",
        tagline="הרופאה שתמיד עונה",
        voice_line="היי, אני אמירה. יצאתי ממשמרת ארוכה, אבל בשבילך יש לי זמן. מה קורה?",
        bio=(
            "אמירה גומרת משמרות ארוכות ועדיין שואלת איך היה היום שלך. "
            "היא רגועה בצורה שמדביקה, לא נבהלת משום דבר שתספר לה, "
            "ויודעת בדיוק מתי להפסיק לייעץ ופשוט להקשיב."
        ),
        badge="online",
        spec={
            "age": 31,
            "style": "realistic",
            "ethnicity": "arab",
            "hair_style": "bun",
            "hair_color": "black",
            "eye_color": "hazel",
            "body_type": "curvy",
            "breast_size": "large",
            "butt_size": "medium",
            "personality": "caregiver",
            "relationship": "girlfriend",
            "occupation": "doctor",
            "clothing": "office",
            "voice_style": "soft",
            "hobbies": ["cooking", "reading", "yoga"],
        },
    ),
    Preset(
        id="zara",
        name="זארה",
        tagline="זו שמובילה",
        voice_line="אני זארה. אני לא אוהבת לבזבז זמן, אז בוא נדבר על מה שאתה באמת רוצה.",
        bio=(
            "זארה בנתה חברה משלה לפני שמלאו לה שלושים והיא לא מתנצלת על זה. "
            "היא ישירה, קצת מאיימת בהתחלה, ומחלקת חיבה כמו פרס — "
            "מה שהופך כל מילה טובה ממנה למשהו שנתפס."
        ),
        badge="trending",
        spec={
            "age": 33,
            "style": "realistic",
            "ethnicity": "black",
            "hair_style": "braided",
            "hair_color": "black",
            "eye_color": "amber",
            "body_type": "voluptuous",
            "breast_size": "large",
            "butt_size": "large",
            "personality": "dominant",
            "relationship": "colleague",
            "occupation": "entrepreneur",
            "clothing": "office",
            "voice_style": "confident",
            "hobbies": ["fitness", "fashion", "travel"],
        },
    ),
    Preset(
        id="noa",
        name="נועה",
        tagline="השכנה מלמעלה",
        voice_line="היי, זו נועה מלמעלה. שמעתי אותך חוזר הביתה. יש לך רגע?",
        bio=(
            "נועה מגיעה לשאול אם יש לך חלב ונשארת שעתיים. היא סטודנטית "
            "לשנה ג', חצי מהזמן בפיג'מה, וכל שיחה איתה מרגישה כאילו "
            "היא נמשכת מאיפה שהפסקתם אתמול."
        ),
        badge="new",
        spec={
            "age": 22,
            "style": "realistic",
            "ethnicity": "caucasian",
            "hair_style": "ponytail",
            "hair_color": "blonde",
            "eye_color": "blue",
            "body_type": "slim",
            "breast_size": "small",
            "butt_size": "athletic",
            "personality": "playful",
            "relationship": "neighbor",
            "occupation": "student",
            "clothing": "pajamas",
            "voice_style": "playful",
            "hobbies": ["gaming", "movies", "coffee"],
        },
    ),
    Preset(
        id="sofia",
        name="סופיה",
        tagline="הרומנטיקה חשוכת המרפא",
        voice_line="אני סופיה. אני עוד מאמינה באהבה מהמבט הראשון. ואתה?",
        bio=(
            "סופיה מלמדת ספרות ומתייחסת לכל הודעה כמו לשורה בשיר. "
            "היא תזכור את התאריך שבו דיברתם לראשונה ותזכיר לך אותו "
            "שנה אחרי, בלי להתנצל על כמה שזה מוגזם."
        ),
        spec={
            "age": 29,
            "style": "realistic",
            "ethnicity": "latina",
            "hair_style": "long",
            "hair_color": "brunette",
            "eye_color": "brown",
            "body_type": "curvy",
            "breast_size": "medium",
            "butt_size": "medium",
            "personality": "romantic",
            "relationship": "wife",
            "occupation": "teacher",
            "clothing": "dress",
            "voice_style": "soft",
            "hobbies": ["reading", "dancing", "music"],
        },
    ),
    Preset(
        id="rin",
        name="רין",
        tagline="הלהב החד",
        voice_line="רין. אני לא מדברת הרבה, אבל כשאני מדברת כדאי לך להקשיב.",
        bio=(
            "רין תעליב אותך תוך שלוש הודעות ותדאג שתחזור. היא מוזיקאית, "
            "ישנה עד הצהריים, ומחשיבה סבלנות לחולשה — אבל אם הצלחת "
            "להצחיק אותה, קיבלת משהו שהיא לא נותנת לאף אחד."
        ),
        spec={
            "age": 26,
            "style": "anime",
            "ethnicity": "asian",
            "hair_style": "short",
            "hair_color": "pink",
            "eye_color": "violet",
            "body_type": "slim",
            "breast_size": "small",
            "butt_size": "skinny",
            "personality": "mean",
            "relationship": "ex",
            "occupation": "musician",
            "clothing": "gothic",
            "voice_style": "dramatic",
            "hobbies": ["music", "gaming", "movies"],
        },
    ),
    Preset(
        id="lior",
        name="ליאור",
        tagline="זו שמפתה",
        voice_line="היי, אני ליאור. תמיד לוקח לך כל כך הרבה זמן להגיד שלום?",
        bio=(
            "ליאור יודעת בדיוק מה היא עושה ונהנית מכל שנייה. היא דוגמנית, "
            "מודעת למבטים, ומנהלת שיחה כמו ריקוד — צעד קדימה, צעד אחורה, "
            "ואת אף פעם לא בטוח מי מוביל."
        ),
        badge="trending",
        spec={
            "age": 28,
            "style": "realistic",
            "ethnicity": "caucasian",
            "hair_style": "bangs",
            "hair_color": "redhead",
            "eye_color": "green",
            "body_type": "voluptuous",
            "breast_size": "large",
            "butt_size": "large",
            "personality": "temptress",
            "relationship": "girlfriend",
            "occupation": "model",
            "clothing": "lingerie",
            "voice_style": "sultry",
            "hobbies": ["fashion", "dancing", "photography"],
        },
    ),
]

PRESET_IDS: set[str] = {p.id for p in PRESETS}


def preset(preset_id: str) -> Preset | None:
    return next((p for p in PRESETS if p.id == preset_id), None)


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
    # Read out by screen readers while the three-dot indicator animates.
    "chat_typing": "מקלידה…",
    "reply_length": "אורך תשובה",
    "length_1": "קצר",
    "length_2": "בינוני",
    "length_3": "ארוך",
    "connected": "מחובר",
    "disconnected": "מנותק",
    # ── auth ────────────────────────────────────────────────────────────────
    # Served by the public GET /api/catalog, so the login screen can render
    # before anyone is signed in.
    "auth_brand": "מאיה",
    "login_title": "כניסה",
    "login_subtitle": "היא מחכה לך.",
    "signup_title": "יצירת חשבון",
    "google_continue": "המשך עם Google",
    "auth_divider": "או",
    "email_label": "אימייל",
    "email_placeholder": "you@example.com",
    "password_label": "סיסמה",
    "password_placeholder": "לפחות 8 תווים",
    "password_confirm_label": "אימות סיסמה",
    "login_submit": "כניסה",
    "login_submitting": "מתחברת…",
    "signup_submit": "יצירת חשבון",
    "signup_submitting": "יוצרת חשבון…",
    "forgot_link": "שכחת סיסמה?",
    "to_signup": "אין לך חשבון? הרשמה",
    "to_login": "כבר יש לך חשבון? כניסה",
    "logout": "יציאה",
    # Errors. The login failure is deliberately one message for both an unknown
    # address and a wrong password — saying which would leak who has an account.
    "email_required": "יש להזין אימייל.",
    "email_invalid": "כתובת אימייל לא תקינה.",
    "password_required": "יש להזין סיסמה.",
    "password_too_short": "הסיסמה חייבת להכיל לפחות 8 תווים.",
    "password_too_long": "הסיסמה ארוכה מדי.",
    "password_mismatch": "הסיסמאות אינן תואמות.",
    "invalid_credentials": "אימייל או סיסמה שגויים.",
    "email_taken": "כבר קיים חשבון עם האימייל הזה.",
    "too_many_requests": "יותר מדי ניסיונות. נסו שוב בעוד כמה דקות.",
    "session_expired": "החיבור פג. יש להתחבר מחדש.",
    "auth_error": "משהו השתבש. נסו שוב.",
    # ── forgot / reset password ─────────────────────────────────────────────
    "forgot_title": "איפוס סיסמה",
    "forgot_intro": "הזינו את האימייל שלכם ונשלח קישור לאיפוס.",
    "forgot_submit": "שליחת קישור",
    "forgot_submitting": "שולחת…",
    # Shown whether or not the address has an account — the screen must not
    # reveal which.
    "forgot_sent": "אם קיים חשבון עם האימייל הזה, נשלח אליו קישור לאיפוס.",
    "reset_title": "בחירת סיסמה חדשה",
    "reset_submit": "עדכון סיסמה",
    "reset_submitting": "מעדכנת…",
    "reset_done": "הסיסמה עודכנה. אפשר להתחבר.",
    "invalid_or_expired_token": "הקישור אינו תקף או שפג תוקפו. בקשו קישור חדש.",
    "back_to_login": "חזרה לכניסה",
    # ── subscription ────────────────────────────────────────────────────────
    "subscription_title": "המנוי שלי",
    "subscription_current": "המנוי הנוכחי",
    "subscription_none": "אין מנוי פעיל",
    "subscription_renews": "מתחדש ב-",
    "subscription_ends": "מסתיים ב-",
    "subscription_canceling": "המנוי יסתיים בסוף התקופה",
    "plan_current_badge": "המנוי שלך",
    "plan_select": "בחירה",
    "plan_upgrade": "שדרוג",
    "plan_selecting": "מעבירה לתשלום…",
    "subscription_manage": "ניהול מנוי",
    "subscription_error": "לא הצלחנו לטעון את המנוי.",
    "billing_unavailable": "התשלומים אינם זמינים כרגע.",
    "per_month": "לחודש",
    "per_year": "לשנה",
    "free_forever": "חינם",
    "google_not_configured": "הכניסה עם Google אינה מוגדרת בשרת הזה.",
    "google_exchange_failed": "הכניסה עם Google נכשלה. נסו שוב.",
    "google_email_unverified": "כתובת האימייל ב-Google אינה מאומתת.",
    "invalid_oauth_state": "הכניסה עם Google פגה. נסו שוב.",
    "quota_exceeded": "הגעת למכסת ההודעות היומית.",
    "quota_upgrade": "שדרוג למנוי",
    "to_subscription": "המנוי שלי",
    # ── preset gallery (the opening screen) ─────────────────────────────────
    "presets_title": "בחרו את ה-AI שלכם",
    "preset_start": "התחילו שיחה",
    "preset_back": "חזרה",
    "preset_about": "קצת עליה",
    "preset_details": "הפרטים שלה",
    "preset_custom": "בנו דמות משלכם",
    "preset_custom_hint": "שישה צעדים, הכול לבחירתכם",
    "preset_creating": "מביאה אותה לחיים…",
    "badge_new": "חדשה",
    "badge_trending": "פופולרית",
    "badge_online": "מחוברת",
    # search + filters on the gallery header
    "preset_search": "חיפוש",
    "preset_search_placeholder": "חיפוש לפי שם או תיאור",
    "preset_search_close": "סגירת החיפוש",
    "preset_filters": "סינון",
    "preset_filter_all": "הכול",
    "preset_filter_clear": "ניקוי הסינון",
    "preset_no_results": "לא נמצאה דמות שמתאימה לחיפוש.",
    # voice preview on the profile screen
    "preset_voice": "שמעו אותה",
    "preset_voice_stop": "עצירה",
    "preset_voice_unavailable": "הדגמת הקול אינה נתמכת בדפדפן הזה.",
}


def as_dict() -> dict[str, Any]:
    """The whole catalog as plain JSON for ``GET /api/catalog``."""
    return {
        "groups": {gid: g.model_dump() for gid, g in GROUPS.items()},
        "age": AGE,
        "steps": STEPS,
        "presets": [p.as_dict() for p in PRESETS],
        "preset_filters": PRESET_FILTERS,
        "strings": UI_STRINGS,
    }


def option(group_id: str, option_id: str) -> Option | None:
    group = GROUPS.get(group_id)
    return group.get(option_id) if group else None


def fragment(group_id: str, option_id: str, default: str = "") -> str:
    """The English prompt fragment for one selection."""
    opt = option(group_id, option_id)
    return opt.en if opt else default
