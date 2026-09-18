import type { CSSProperties } from "react";
import { ArrowDown, ArrowUp, Copy, Trash2 } from "lucide-react";
import type { DesignDeck, DesignPalette, DesignSlide } from "@/lib/api";
import type { DesignerCopy } from "./presentation-designer-copy";

export function SlideRail({
  deck,
  selected,
  label,
  onSelect,
}: {
  deck: DesignDeck;
  selected: string;
  label: string;
  onSelect: (id: string) => void;
}) {
  const palette = deck.design.palette;
  return (
    <aside className="designer-slides">
      <strong>
        {label} · {deck.slides.length}
      </strong>
      {deck.slides.map((slide, index) => (
        <button
          key={slide.slide_id}
          data-active={slide.slide_id === selected}
          onClick={() => onSelect(slide.slide_id)}
        >
          <span>{index + 1}</span>
          <div
            style={{
              background: palette.background,
              color: palette.text,
              borderColor: palette.surface,
            }}
          >
            <b>{slide.content.title}</b>
          </div>
        </button>
      ))}
    </aside>
  );
}

export function SlideCanvas({
  deck,
  slide,
  mode,
  htmlUrl,
  previewLabel,
  onTitle,
}: {
  deck: DesignDeck;
  slide: DesignSlide;
  mode: "canvas" | "preview";
  htmlUrl: string;
  previewLabel: string;
  onTitle: (title: string) => void;
}) {
  const palette = deck.design.palette;
  if (mode === "preview")
    return (
      <main className="designer-stage">
        <iframe src={htmlUrl} sandbox="allow-scripts" title={previewLabel} />
      </main>
    );
  const style = {
    "--deck-bg": palette.background,
    "--deck-surface": palette.surface,
    "--deck-text": palette.text,
    "--deck-accent": slide.accent_override ?? palette.accent,
    "--deck-muted": palette.text_secondary,
    "--deck-heading": deck.design.heading_font,
    "--deck-body": deck.design.body_font,
  } as CSSProperties;
  return (
    <main className="designer-stage">
      <div className="designer-canvas" style={style}>
        {slide.content.background_url && (
          <img src={slide.content.background_url} alt="" />
        )}
        <div className="designer-slide-type">
          {slide.slide_type.replaceAll("_", " ")}
        </div>
        <h2
          contentEditable
          suppressContentEditableWarning
          onBlur={(event) => onTitle(event.currentTarget.textContent ?? "")}
        >
          {slide.content.title}
        </h2>
        {slide.content.subtitle && (
          <p className="designer-subtitle">{slide.content.subtitle}</p>
        )}
        {slide.content.quote_text ? (
          <blockquote>
            “{slide.content.quote_text}”
            <small>{slide.content.quote_attribution}</small>
          </blockquote>
        ) : (
          <>
            {slide.content.body_text && (
              <p className="designer-body">{slide.content.body_text}</p>
            )}
            {slide.content.bullets && (
              <ul>
                {slide.content.bullets.map((bullet, index) => (
                  <li key={index}>{bullet}</li>
                ))}
              </ul>
            )}
            {slide.content.stats && (
              <div className="designer-stats">
                {slide.content.stats.map((stat, index) => (
                  <div key={index}>
                    <b>
                      {stat.value}
                      {stat.unit}
                    </b>
                    <span>{stat.label}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

export function PropertiesPanel({
  deck,
  slide,
  copy,
  onSlide,
  onDeck,
  onMove,
  onDuplicate,
  onRemove,
}: {
  deck: DesignDeck;
  slide: DesignSlide;
  copy: DesignerCopy;
  onSlide: (patch: Record<string, unknown>) => void;
  onDeck: (deck: DesignDeck) => void;
  onMove: (delta: -1 | 1) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const palette = deck.design.palette;
  return (
    <aside className="designer-properties">
      <strong>{copy.properties}</strong>
      <label>
        {copy.title}
        <textarea
          value={slide.content.title}
          onChange={(event) => onSlide({ title: event.target.value })}
        />
      </label>
      <label>
        {copy.subtitle}
        <textarea
          value={slide.content.subtitle ?? ""}
          onChange={(event) =>
            onSlide({ subtitle: event.target.value || null })
          }
        />
      </label>
      <label>
        {copy.body}
        <textarea
          value={slide.content.body_text ?? ""}
          onChange={(event) =>
            onSlide({ body_text: event.target.value || null })
          }
        />
      </label>
      <label>
        {copy.bullets}
        <textarea
          value={(slide.content.bullets ?? []).join("\n")}
          onChange={(event) =>
            onSlide({
              bullets: event.target.value
                ? event.target.value.split("\n")
                : null,
            })
          }
        />
      </label>
      <label>
        {copy.notes}
        <textarea
          value={slide.content.speaker_notes ?? ""}
          onChange={(event) =>
            onSlide({ speaker_notes: event.target.value || null })
          }
        />
      </label>
      <div className="designer-slide-actions">
        <button aria-label={copy.up} onClick={() => onMove(-1)}>
          <ArrowUp size={15} />
        </button>
        <button aria-label={copy.down} onClick={() => onMove(1)}>
          <ArrowDown size={15} />
        </button>
        <button aria-label={copy.duplicate} onClick={onDuplicate}>
          <Copy size={15} />
        </button>
        <button aria-label={copy.delete} onClick={onRemove}>
          <Trash2 size={15} />
        </button>
      </div>
      <strong>{copy.palette}</strong>
      {(Object.keys(palette) as Array<keyof DesignPalette>).map((key) => (
        <label className="designer-color" key={key}>
          <span>{key.replace("_", " ")}</span>
          <input
            type="color"
            value={palette[key]}
            onChange={(event) =>
              onDeck({
                ...deck,
                design: {
                  ...deck.design,
                  palette: { ...palette, [key]: event.target.value },
                },
              })
            }
          />
          <code>{palette[key]}</code>
        </label>
      ))}
      <label>
        {copy.headingFont}
        <input
          value={deck.design.heading_font}
          onChange={(event) =>
            onDeck({
              ...deck,
              design: { ...deck.design, heading_font: event.target.value },
            })
          }
        />
      </label>
      <label>
        {copy.bodyFont}
        <input
          value={deck.design.body_font}
          onChange={(event) =>
            onDeck({
              ...deck,
              design: { ...deck.design, body_font: event.target.value },
            })
          }
        />
      </label>
    </aside>
  );
}
