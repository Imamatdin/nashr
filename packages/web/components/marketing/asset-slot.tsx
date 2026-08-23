// Asset slots. Every screenshot the founder still owes has a frame standing in
// for it, and the frame says in plain Uzbek what the image will show.
//
// Deliberately NOT a mock browser window: fake traffic lights over a fake
// address bar are a drawing of a screenshot, which is worse than an empty frame
// that admits what it is. When the file lands the same component renders it and
// nothing around it moves.

import Image from "next/image";

export interface AssetSlotProps {
  /** What the finished image shows, in the reader language. */
  label: string;
  /** Where the file goes, for the founder. */
  note?: string;
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
