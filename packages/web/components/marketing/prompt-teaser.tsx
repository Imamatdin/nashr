"use client";

// The hero composer. A marketing-local twin of the app's PromptBar — same
// shapes (bordered surface, tall composer, ink send square), none of its
// dependencies, so the landing never drags app modules across the boundary.
//
// It is a real <form>: with JavaScript off it still submits to the login door
// with /new as the return, and only the typed topic is lost. With JavaScript
// on, the topic rides along in the return path.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { APP, startHref } from "./links";

// TODO(W): /new reads ?lang= today but not ?topic= (app/new/page.tsx). Until it
// does, the typed topic reaches the app in two carriers and is consumed by
// neither: the returnTo path (/new?topic=…) and this sessionStorage key.
const TOPIC_KEY = "nashr.topic";

// Short enough to sit on one line beside the hero: the chip is a starting
// point, not the topic itself.
const EXAMPLES = [
  "Orol dengizi qurishi",
  "Yoritish davri",
  "Fermentlar kinetikasi",
];

export function PromptTeaser() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const trimmed = topic.trim();

  function go(next: string): void {
    const value = next.trim();
    if (!value) return;
    try {
      window.sessionStorage.setItem(TOPIC_KEY, value);
    } catch {
      // Private-mode storage denial must not block the door.
    }
    router.push(startHref(value));
  }

  return (
    <form
      className="mkt-prompt"
      action={APP.login}
      method="get"
      onSubmit={(event) => {
        if (!trimmed) return;
        event.preventDefault();
        go(trimmed);
      }}
    >
      <input type="hidden" name="returnTo" value={APP.create} />

      <div className="mkt-prompt-box">
        <textarea
          className="mkt-prompt-input"
          name="topic"
          rows={2}
          maxLength={600}
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              go(topic);
            }
          }}
          placeholder="Mavzuni yozing yoki manbangizni tasvirlang…"
          aria-label="Taqdimot mavzusi"
        />
        <div className="mkt-prompt-foot">
          <span className="mkt-prompt-hint">Manbalarni keyingi qadamda biriktirasiz</span>
          <button
            type="submit"
            className="mkt-prompt-send"
            data-armed={trimmed ? "true" : "false"}
            aria-label="Davom etish"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>

      <div className="mkt-prompt-examples">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="mkt-prompt-example"
            onClick={() => {
              setTopic(example);
              go(example);
            }}
          >
            {example}
          </button>
        ))}
      </div>
    </form>
  );
}

export default PromptTeaser;
