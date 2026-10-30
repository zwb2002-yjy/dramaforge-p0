import { useEffect, useRef, useState } from "react";
import { Film } from "lucide-react";
import { artifactVideoFrameUrl } from "../../lib/api";
import { timelineCopy as copy } from "./timelineCopy";

/** Only sample visible clips; never load a video player for each timeline cell. */
export function EditingClipThumbnail({
  projectId,
  artifactId,
  label,
}: {
  projectId: string;
  artifactId: string | null;
  label: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const src = artifactId ? artifactVideoFrameUrl(projectId, artifactId, "start") : null;
  useEffect(() => {
    if (!ref.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return (
    <span className="editing-clip-thumbnail" ref={ref} title={copy.thumbnailNotice}>
      {visible && src && failedUrl !== src ? (
        <img
          draggable={false}
          src={src}
          alt={`${label} · ${copy.sourceFrame}`}
          decoding="async"
          onError={() => setFailedUrl(src)}
        />
      ) : (
        <span className="editing-thumbnail-placeholder">
          <Film aria-hidden="true" size={20} />
          {failedUrl === src && src && <small>{copy.thumbnailFailed}</small>}
        </span>
      )}
    </span>
  );
}
