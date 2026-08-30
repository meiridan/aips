# Wizard imagery

Drop curated art at the exact paths below and it appears with no code change.
Anything missing falls back to a gradient (or, for the colour groups, the swatch
declared in `maya/companions/catalog.py`), so the wizard works without it.

Keep each file <= 80KB webp — the bundle is committed to git.

## Tiles (portrait, 3:4 — eye colour is square)

### style — בחירת סגנון

- `maya/media/tiles/style/realistic.webp` — ריאליסטי (photorealistic)
- `maya/media/tiles/style/anime.webp` — אנימה (anime-styled)

### ethnicity — בחירת מוצא

- `maya/media/tiles/ethnicity/caucasian.webp` — אירופאית (Caucasian)
- `maya/media/tiles/ethnicity/latina.webp` — לטינית (Latina)
- `maya/media/tiles/ethnicity/asian.webp` — אסייתית (Asian)
- `maya/media/tiles/ethnicity/arab.webp` — ערבייה (Arab)
- `maya/media/tiles/ethnicity/black.webp` — אפרו-אמריקאית (Black)

### hair_style — בחירת תסרוקת

- `maya/media/tiles/hair_style/straight.webp` — חלק (straight)
- `maya/media/tiles/hair_style/braided.webp` — צמות (braided)
- `maya/media/tiles/hair_style/bangs.webp` — פוני (with bangs)
- `maya/media/tiles/hair_style/curly.webp` — מתולתל (curly)
- `maya/media/tiles/hair_style/bun.webp` — אסוף (in a bun)
- `maya/media/tiles/hair_style/short.webp` — קצר (short)
- `maya/media/tiles/hair_style/long.webp` — ארוך (long)
- `maya/media/tiles/hair_style/ponytail.webp` — קוקו (in a ponytail)
- `maya/media/tiles/hair_style/pigtails.webp` — שתי צמות (in pigtails)

### hair_color — בחירת צבע שיער

- `maya/media/tiles/hair_color/blonde.webp` — בלונדיני (blonde)
- `maya/media/tiles/hair_color/brunette.webp` — חום (brunette)
- `maya/media/tiles/hair_color/black.webp` — שחור (black)
- `maya/media/tiles/hair_color/redhead.webp` — ג'ינג'י (red)
- `maya/media/tiles/hair_color/pink.webp` — ורוד (pink)
- `maya/media/tiles/hair_color/white.webp` — לבן (white)
- `maya/media/tiles/hair_color/blue.webp` — כחול (blue)
- `maya/media/tiles/hair_color/green.webp` — ירוק (green)
- `maya/media/tiles/hair_color/purple.webp` — סגול (purple)
- `maya/media/tiles/hair_color/multicolor.webp` — רב-גוני (multicolored)

### eye_color — בחירת צבע עיניים

- `maya/media/tiles/eye_color/brown.webp` — חום (brown)
- `maya/media/tiles/eye_color/blue.webp` — כחול (blue)
- `maya/media/tiles/eye_color/green.webp` — ירוק (green)
- `maya/media/tiles/eye_color/amber.webp` — ענבר (amber)
- `maya/media/tiles/eye_color/hazel.webp` — דבש (hazel)
- `maya/media/tiles/eye_color/violet.webp` — סגול (violet)

### body_type — בחירת מבנה גוף

- `maya/media/tiles/body_type/slim.webp` — רזה (slim)
- `maya/media/tiles/body_type/fit.webp` — אתלטית (fit and athletic)
- `maya/media/tiles/body_type/voluptuous.webp` — חטובה (voluptuous)
- `maya/media/tiles/body_type/curvy.webp` — מלאה (curvy)
- `maya/media/tiles/body_type/bbw.webp` — גדולה (full-figured)

### breast_size — בחירת מידת חזה

- `maya/media/tiles/breast_size/flat.webp` — שטוח (flat)
- `maya/media/tiles/breast_size/small.webp` — קטן (small)
- `maya/media/tiles/breast_size/medium.webp` — בינוני (medium)
- `maya/media/tiles/breast_size/large.webp` — גדול (large)
- `maya/media/tiles/breast_size/huge.webp` — ענק (very large)

### butt_size — בחירת מידת ישבן

- `maya/media/tiles/butt_size/skinny.webp` — רזה (slim)
- `maya/media/tiles/butt_size/athletic.webp` — אתלטי (athletic)
- `maya/media/tiles/butt_size/medium.webp` — בינוני (medium)
- `maya/media/tiles/butt_size/large.webp` — גדול (large)
- `maya/media/tiles/butt_size/xlarge.webp` — גדול במיוחד (extra large)

## Avatars (portrait, 3:4)

Resolved by `maya/companions/avatars.py`, most specific first:

1. `maya/media/avatars/{style}/{ethnicity}_{hair_color}.webp`
2. `maya/media/avatars/{style}/{ethnicity}.webp`
3. `maya/media/avatars/{style}/default.webp`

Ship tier 2 first — that is 2 styles x 5 ethnicities = 10 files:

- `maya/media/avatars/realistic/caucasian.webp`
- `maya/media/avatars/realistic/latina.webp`
- `maya/media/avatars/realistic/asian.webp`
- `maya/media/avatars/realistic/arab.webp`
- `maya/media/avatars/realistic/black.webp`
- `maya/media/avatars/anime/caucasian.webp`
- `maya/media/avatars/anime/latina.webp`
- `maya/media/avatars/anime/asian.webp`
- `maya/media/avatars/anime/arab.webp`
- `maya/media/avatars/anime/black.webp`

## Presets (portrait 3:4, gallery 3:4)

The nine ready-made companions on the opening gallery (`PRESETS` in
`maya/companions/catalog.py`). `portrait.webp` is the grid tile and becomes
the companion's avatar once she is created; `1`–`4` are the profile-screen
carousel. Every one of these falls back to a gradient when missing, so the
gallery is usable before the art lands.

Optionally add `voice.mp3` (a few seconds, her `voice_line` read aloud) beside
the images — e.g. `maya/media/presets/maya/voice.mp3`. The profile's voice-preview
button plays the recording when the file exists and otherwise speaks
`voice_line` with the browser's own Hebrew speech synthesis, so the button works
before any audio is recorded.

### maya — מאיה (מאיה — האסטרטגית היצירתית)

- `maya/media/presets/maya/portrait.webp`
- `maya/media/presets/maya/1.webp`
- `maya/media/presets/maya/2.webp`
- `maya/media/presets/maya/3.webp`
- `maya/media/presets/maya/4.webp`

### elena — אלנה (אלנה — ההרפתקנית)

- `maya/media/presets/elena/portrait.webp`
- `maya/media/presets/elena/1.webp`
- `maya/media/presets/elena/2.webp`
- `maya/media/presets/elena/3.webp`
- `maya/media/presets/elena/4.webp`

### yuki — יוקי (יוקי — הנשמה השקטה)

- `maya/media/presets/yuki/portrait.webp`
- `maya/media/presets/yuki/1.webp`
- `maya/media/presets/yuki/2.webp`
- `maya/media/presets/yuki/3.webp`
- `maya/media/presets/yuki/4.webp`

### amira — אמירה (אמירה — הרופאה שתמיד עונה)

- `maya/media/presets/amira/portrait.webp`
- `maya/media/presets/amira/1.webp`
- `maya/media/presets/amira/2.webp`
- `maya/media/presets/amira/3.webp`
- `maya/media/presets/amira/4.webp`

### zara — זארה (זארה — זו שמובילה)

- `maya/media/presets/zara/portrait.webp`
- `maya/media/presets/zara/1.webp`
- `maya/media/presets/zara/2.webp`
- `maya/media/presets/zara/3.webp`
- `maya/media/presets/zara/4.webp`

### noa — נועה (נועה — השכנה מלמעלה)

- `maya/media/presets/noa/portrait.webp`
- `maya/media/presets/noa/1.webp`
- `maya/media/presets/noa/2.webp`
- `maya/media/presets/noa/3.webp`
- `maya/media/presets/noa/4.webp`

### sofia — סופיה (סופיה — הרומנטיקה חשוכת המרפא)

- `maya/media/presets/sofia/portrait.webp`
- `maya/media/presets/sofia/1.webp`
- `maya/media/presets/sofia/2.webp`
- `maya/media/presets/sofia/3.webp`
- `maya/media/presets/sofia/4.webp`

### rin — רין (רין — הלהב החד)

- `maya/media/presets/rin/portrait.webp`
- `maya/media/presets/rin/1.webp`
- `maya/media/presets/rin/2.webp`
- `maya/media/presets/rin/3.webp`
- `maya/media/presets/rin/4.webp`

### lior — ליאור (ליאור — זו שמפתה)

- `maya/media/presets/lior/portrait.webp`
- `maya/media/presets/lior/1.webp`
- `maya/media/presets/lior/2.webp`
- `maya/media/presets/lior/3.webp`
- `maya/media/presets/lior/4.webp`
