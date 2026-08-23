// Asset slots. Every screenshot the founder still owes has a designed frame
// standing in for it: the frame is the final chrome, the hatched interior says
// in Uzbek what the image will show. When the file lands, the same component
// renders it — nothing around it moves.

import Image from "next/image";

export interface AssetSlotProps {
  /** What the finished image shows, in the reader language. */
  label: string;
  /** Where the file goes, for the founder. Rendered small, under the label. */
  note?: string;
  /** Fake address bar text — only for the browser variant. */
  url?: string;
  variant?: "browser" | "plate";
  /** Aspect ratio of the interior, e.g. "16 / 9". */
  ratio?: string;
  /** When present the slot renders the real asset instead of the placeholder. */
  src?: string;
  alt?: string;
  width?: number;
  height?: number;
  priority?: boolean;
  caption?: string;
}

export function AssetSlot({
  label,
  note,
  url,
  variant = "browser",
  ratio = "16 / 9",
  src,
  alt,
  width = 1600,
  height = 900,
  priority = false,
  caption,
}: AssetSlotProps) {
  return (
    <figure className="mkt-slot-figure-wrap">
      <div className="mkt-slot">
        {variant === "browser" ? (
          <div className="mkt-slot-bar">
            <span className="mkt-slot-dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            <span className="mkt-slot-url">{url ?? "nashr.uz"}</span>
          </div>
        ) : null}

        {src ? (
          <Image
            className="mkt-slot-figure"
            src={src}
            alt={alt ?? label}
            width={width}
            height={height}
            priority={priority}
            sizes="(max-width: 1128px) 100vw, 1080px"
          />
        ) : (
          <div className="mkt-slot-body" style={{ aspectRatio: ratio }}>
            <span className="mkt-slot-tag">Asset</span>
            <p className="mkt-slot-label">{label}</p>
            {note ? <p className="mkt-slot-note">{note}</p> : null}
          </div>
        )}
      </div>
      {caption ? <figcaption className="mkt-caption">{caption}</figcaption> : null}
    </figure>
  );
}

export default AssetSlot;
