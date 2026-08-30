import { useCallback, useEffect, useRef, useState } from "react";

import type { Preset } from "../types";

export type VoiceState = "idle" | "playing" | "unsupported";

/** Plays a character's voice sample on the profile screen.
 *
 *  Two sources, in order: the curated recording at `preset.voice`, and — when
 *  that file has not been recorded yet, which is the normal case today — the
 *  browser speaking `preset.voice_line` itself. A 404 on the recording is
 *  therefore not an error path but the expected one, the same way a missing
 *  portrait falls back to a gradient.
 *
 *  `unsupported` means neither source worked (no audio file, no speech
 *  synthesis), which is what the UI shows a note for instead of a dead button.
 */
export function useVoicePreview(preset: Preset) {
  const [state, setState] = useState<VoiceState>("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speaking = useRef(false);

  const stop = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (speaking.current) {
      window.speechSynthesis?.cancel();
      speaking.current = false;
    }
    setState((current) => (current === "playing" ? "idle" : current));
  }, []);

  // A sample still talking after the user has left the profile is a bug you
  // hear rather than see.
  useEffect(() => stop, [stop, preset.id]);

  const speak = useCallback(() => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth || typeof SpeechSynthesisUtterance === "undefined") {
      setState("unsupported");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(preset.voice_line);
    utterance.lang = "he-IL";
    utterance.onend = () => {
      speaking.current = false;
      setState("idle");
    };
    utterance.onerror = () => {
      speaking.current = false;
      setState("unsupported");
    };
    speaking.current = true;
    synth.speak(utterance);
    setState("playing");
  }, [preset.voice_line]);

  const play = useCallback(() => {
    const audio = new Audio(preset.voice);
    audioRef.current = audio;
    audio.onended = () => {
      audioRef.current = null;
      setState("idle");
    };
    // No recording for her yet — read the line out loud instead.
    audio.onerror = () => {
      audioRef.current = null;
      speak();
    };
    const started = audio.play();
    if (started && typeof started.then === "function") {
      started.then(() => setState("playing")).catch(() => {
        audioRef.current = null;
        speak();
      });
    } else {
      setState("playing");
    }
  }, [preset.voice, speak]);

  return { state, play, stop };
}
