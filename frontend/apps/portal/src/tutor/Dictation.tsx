import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useEffect, useRef, useState } from "react";

/** The parts of the Web Speech API we use (not in TypeScript's DOM types yet). */
interface SpeechResult {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}
interface SpeechEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<SpeechResult>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type RecognitionClass = new () => Recognition;

function speechRecognition(): RecognitionClass | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionClass;
    webkitSpeechRecognition?: RecognitionClass;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Voice-to-text for a report field (G4, FR-16-3) with the browser's speech recognition
 * (Chrome, Edge, Safari). Where the browser has none the button isn't shown: the phone
 * keyboard's own dictation still works. Speech is processed by the browser's service,
 * never by TutorTrack. Finished phrases are appended to the field. */
export function DictationButton({
  value,
  onChange,
  disabled,
  fieldLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  fieldLabel: string;
}) {
  const { t, i18n } = useTranslation();
  const [listening, setListening] = useState(false);
  const [problem, setProblem] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const latest = useRef(value);
  latest.current = value;

  useEffect(() => () => recognition.current?.stop(), []);

  const Engine = speechRecognition();
  if (!Engine) return null;

  const toggle = () => {
    if (listening) {
      recognition.current?.stop();
      return;
    }
    setProblem("");
    const engine = new Engine();
    engine.lang = i18n.language || "en-GB";
    engine.continuous = true;
    engine.interimResults = false;
    engine.onresult = (event) => {
      let heard = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result?.isFinal) heard += result[0].transcript;
      }
      heard = heard.trim();
      if (!heard) return;
      const current = latest.current;
      const next = current && !/\s$/.test(current) ? `${current} ${heard}` : `${current}${heard}`;
      latest.current = next;
      onChange(next);
    };
    engine.onerror = (event) => {
      setProblem(
        event.error === "not-allowed" || event.error === "service-not-allowed"
          ? t("dictation.blocked")
          : t("dictation.failed"),
      );
    };
    engine.onend = () => setListening(false);
    recognition.current = engine;
    try {
      engine.start();
      setListening(true);
    } catch {
      setProblem(t("dictation.failed"));
    }
  };

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant={listening ? "danger" : "ghost"}
        aria-pressed={listening}
        disabled={disabled}
        onClick={toggle}
      >
        {listening ? t("dictation.stop") : t("dictation.start")}
        {/* The field's name is part of the button's text, not an aria-label, so the
            field's own label still finds just the field. */}
        <span className="sr-only"> {fieldLabel}</span>
      </Button>
      <span role="status" aria-live="polite" className="text-xs text-muted-foreground">
        {listening ? t("dictation.listening") : problem}
      </span>
    </span>
  );
}
