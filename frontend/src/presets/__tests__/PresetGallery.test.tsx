import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import type { Catalog, Preset } from "../../types";
import PresetGallery from "../PresetGallery";
import PresetProfile from "../PresetProfile";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, createCompanion: vi.fn() };
});

const api = await import("../../api");
const createCompanion = vi.mocked(api.createCompanion);

const strings = new Proxy({} as Record<string, string>, {
  get: (_t, key: string) => `[${key}]`,
  has: () => true,
});

function makePreset(n: number): Preset {
  return {
    id: `p${n}`,
    name: `דמות ${n}`,
    tagline: n === 3 ? "הרקדנית" : `הכינוי ${n}`,
    bio: `ביוגרפיה של דמות ${n}`,
    voice_line: `היי, אני דמות ${n}.`,
    badge: n === 1 ? "trending" : null,
    spec: {
      age: 24 + n,
      style: n === 3 ? "anime" : "realistic",
      ethnicity: "arab",
      hair_style: "long",
      hair_color: "blue",
      eye_color: "hazel",
      body_type: "curvy",
      breast_size: "large",
      butt_size: "large",
      personality: "caregiver",
      relationship: "girlfriend",
      occupation: "nurse",
      clothing: "dress",
      voice_style: "soft",
      hobbies: ["yoga"],
    },
    portrait: `/media/presets/p${n}/portrait.webp`,
    gallery: [`/media/presets/p${n}/1.webp`, `/media/presets/p${n}/2.webp`],
    voice: `/media/presets/p${n}/voice.mp3`,
  };
}

const PRESETS = Array.from({ length: 9 }, (_, i) => makePreset(i + 1));

const USER = { id: "u1", email: "dev@local.test", name: "Dev", email_verified: true };

function group(id: string, he: string, options: [string, string][]) {
  return {
    id,
    he,
    kind: "emoji" as const,
    multi: false,
    options: options.map(([oid, label]) => ({
      id: oid,
      he: label,
      en: oid,
      asset: null,
      emoji: "✨",
      color: null,
      extra: {},
    })),
  };
}

const catalog: Catalog = {
  groups: {
    style: group("style", "בחירת סגנון", [
      ["realistic", "ריאליסטי"],
      ["anime", "אנימה"],
    ]),
    personality: group("personality", "בחירת אישיות", [["caregiver", "מטפחת"]]),
    relationship: group("relationship", "בחירת סוג קשר", [["girlfriend", "בת זוג"]]),
    occupation: group("occupation", "בחירת עיסוק", [["nurse", "אחות"]]),
    voice_style: group("voice_style", "בחירת סגנון דיבור", [["soft", "רכה"]]),
    clothing: group("clothing", "בחירת לבוש", [["dress", "שמלה"]]),
    hobbies: group("hobbies", "בחירת תחביבים", [["yoga", "יוגה"]]),
  },
  age: { he: "בחירת גיל", min: 18, max: 55, default: 24 },
  steps: [],
  presets: PRESETS,
  preset_filters: ["style"],
  strings,
  auth: { google: false },
};

// Block body on purpose: an implicit return hands vitest the mock function
// itself, which it then calls as a teardown hook.
beforeEach(() => {
  createCompanion.mockResolvedValue({ ok: true, first_message: "היי" });
});
afterEach(cleanup);

describe("PresetGallery", () => {
  it("renders every ready-made companion plus the build-your-own tile", () => {
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    for (const preset of PRESETS) {
      expect(screen.getByText(preset.name)).toBeTruthy();
    }
    expect(screen.getByText("[preset_custom]")).toBeTruthy();
  });

  it("shows a badge only where the catalog set one", () => {
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    expect(screen.getAllByText("[badge_trending]")).toHaveLength(1);
    expect(screen.queryByText("[badge_new]")).toBeNull();
  });

  it("opens the character that was tapped", () => {
    const onOpen = vi.fn();
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={onOpen} onCustom={() => {}} onLogout={() => {}} />,
    );
    fireEvent.click(screen.getByText(PRESETS[2].name));
    expect(onOpen).toHaveBeenCalledWith(PRESETS[2]);
  });

  it("routes the custom tile to the wizard", () => {
    const onCustom = vi.fn();
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={onCustom} onLogout={() => {}} />,
    );
    fireEvent.click(screen.getByText("[preset_custom]"));
    expect(onCustom).toHaveBeenCalled();
  });

  it("signs out from the header avatar's menu", () => {
    const onLogout = vi.fn();
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={onLogout} />,
    );
    // The avatar carries the account, so logout lives behind it rather than
    // taking up a slot in the top bar.
    expect(screen.queryByText("[logout]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dev" }));
    fireEvent.click(screen.getByText("[logout]"));
    expect(onLogout).toHaveBeenCalled();
  });

  it("drops the avatar menu entirely in single-user mode", () => {
    // No onLogout means no login flow, so the menu would open on nothing.
    render(<PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} />);
    expect(screen.queryByRole("button", { name: "Dev" })).toBeNull();
    expect(screen.queryByText("[logout]")).toBeNull();
  });

  it("shows the account initial on the avatar", () => {
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "Dev" }).textContent).toBe("D");
  });

  function search(value: string) {
    fireEvent.click(screen.getByRole("button", { name: "[preset_search]" }));
    fireEvent.change(screen.getByLabelText("[preset_search]"), { target: { value } });
  }

  it("narrows the grid to characters matching the search text", () => {
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    search("הרקדנית");
    expect(screen.getByText(PRESETS[2].name)).toBeTruthy();
    expect(screen.queryByText(PRESETS[0].name)).toBeNull();
    // The wizard tile is not a search result.
    expect(screen.queryByText("[preset_custom]")).toBeNull();
  });

  it("says so when nothing matches, and recovers when the search closes", () => {
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    search("אין דמות כזאת");
    expect(screen.getByText("[preset_no_results]")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "[preset_search_close]" }));
    expect(screen.queryByText("[preset_no_results]")).toBeNull();
    expect(screen.getByText(PRESETS[0].name)).toBeTruthy();
  });

  it("filters by a catalog group and clears back to everyone", () => {
    render(
      <PresetGallery catalog={catalog} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    fireEvent.click(screen.getByText("אנימה"));
    expect(screen.getByText(PRESETS[2].name)).toBeTruthy();
    expect(screen.queryByText(PRESETS[0].name)).toBeNull();

    fireEvent.click(screen.getByText("[preset_filter_clear]"));
    expect(screen.getByText(PRESETS[0].name)).toBeTruthy();
  });

  it("offers only filter options some character actually has", () => {
    const oneStyle = {
      ...catalog,
      presets: catalog.presets.map((p) => ({ ...p, spec: { ...p.spec, style: "realistic" } })),
    };
    render(
      <PresetGallery catalog={oneStyle} user={USER} onOpen={() => {}} onCustom={() => {}} onLogout={() => {}} />,
    );
    expect(screen.getByText("ריאליסטי")).toBeTruthy();
    expect(screen.queryByText("אנימה")).toBeNull();
  });
});

describe("PresetProfile", () => {
  function renderProfile(onboarded = false, onStarted = vi.fn()) {
    render(
      <PresetProfile
        catalog={catalog}
        preset={PRESETS[0]}
        onboarded={onboarded}
        onBack={() => {}}
        onStarted={onStarted}
      />,
    );
    return onStarted;
  }

  it("shows the biography and the character's own details", () => {
    renderProfile();
    expect(screen.getByText(PRESETS[0].bio)).toBeTruthy();
    expect(screen.getByText("מטפחת")).toBeTruthy();
    expect(screen.getByText("אחות")).toBeTruthy();
    expect(screen.getByText("25")).toBeTruthy();
    expect(screen.getByText(/יוגה/)).toBeTruthy();
  });

  it("creates the companion from the preset's own spec and enters chat", async () => {
    const onStarted = renderProfile();
    fireEvent.click(screen.getByText("[preset_start]"));

    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    const [spec, reset] = createCompanion.mock.calls[0];
    expect(spec.preset).toBe("p1");
    expect(spec.name).toBe(PRESETS[0].name);
    expect(spec.occupation).toBe("nurse");
    expect(reset).toBe(false);
  });

  it("warns and passes reset=true when she already exists", async () => {
    const onStarted = renderProfile(true);
    expect(screen.getByText(/\[recreate_warning\]/)).toBeTruthy();

    fireEvent.click(screen.getByText("[preset_start]"));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(createCompanion.mock.calls[0][1]).toBe(true);
  });

  it("surfaces a failed creation instead of entering chat", async () => {
    createCompanion.mockRejectedValue(new ApiError(500, "boom"));
    const onStarted = renderProfile();

    fireEvent.click(screen.getByText("[preset_start]"));
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    expect(onStarted).not.toHaveBeenCalled();
  });
});

describe("PresetProfile voice preview", () => {
  class FakeUtterance {
    lang = "";
    onend: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(public text: string) {}
  }

  function renderProfile() {
    render(
      <PresetProfile
        catalog={catalog}
        preset={PRESETS[0]}
        onboarded={false}
        onBack={() => {}}
        onStarted={() => {}}
      />,
    );
  }

  afterEach(() => vi.unstubAllGlobals());

  it("plays the curated recording when one exists", async () => {
    const pause = vi.fn();
    let src = "";
    vi.stubGlobal(
      "Audio",
      class {
        pause = pause;
        onended: (() => void) | null = null;
        onerror: (() => void) | null = null;
        constructor(url: string) {
          src = url;
        }
        play() {
          return Promise.resolve();
        }
      },
    );
    renderProfile();

    fireEvent.click(screen.getByText(/\[preset_voice\]/));
    await waitFor(() => expect(screen.getByText(/\[preset_voice_stop\]/)).toBeTruthy());
    expect(src).toBe(PRESETS[0].voice);

    fireEvent.click(screen.getByText(/\[preset_voice_stop\]/));
    expect(pause).toHaveBeenCalled();
    expect(screen.getByText(/\[preset_voice\]/)).toBeTruthy();
  });

  it("speaks her line when no recording has been curated yet", async () => {
    // The normal case today: /media/presets/<id>/voice.mp3 is a 404.
    vi.stubGlobal(
      "Audio",
      class {
        pause = vi.fn();
        onended: (() => void) | null = null;
        onerror: (() => void) | null = null;
        play() {
          return Promise.reject(new Error("404"));
        }
      },
    );
    const speak = vi.fn();
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);

    renderProfile();
    fireEvent.click(screen.getByText(/\[preset_voice\]/));

    await waitFor(() => expect(speak).toHaveBeenCalled());
    const utterance = speak.mock.calls[0][0] as FakeUtterance;
    expect(utterance.text).toBe(PRESETS[0].voice_line);
    expect(utterance.lang).toBe("he-IL");
    expect(screen.getByText(/\[preset_voice_stop\]/)).toBeTruthy();
  });

  it("disables the button when the browser can do neither", async () => {
    vi.stubGlobal(
      "Audio",
      class {
        pause = vi.fn();
        onended: (() => void) | null = null;
        onerror: (() => void) | null = null;
        play() {
          return Promise.reject(new Error("404"));
        }
      },
    );
    vi.stubGlobal("speechSynthesis", undefined);
    vi.stubGlobal("SpeechSynthesisUtterance", undefined);

    renderProfile();
    fireEvent.click(screen.getByText(/\[preset_voice\]/));

    await waitFor(() => expect(screen.getByText("[preset_voice_unavailable]")).toBeTruthy());
    expect(screen.getByRole("button", { name: /preset_voice/ }).hasAttribute("disabled")).toBe(true);
  });
});
