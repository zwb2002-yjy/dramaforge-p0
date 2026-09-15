import { ArrowUp, Check, Focus, Link2, Orbit, X } from "lucide-react";
import { useRef, useState, type PointerEvent, type ReactNode } from "react";

import { artifactContentUrl } from "../../lib/api";
import type { ShotLite } from "../shots/api";
import type { BindingLite } from "../scenes/api";
import "./resonance.css";
import { DirectorCompanion } from "./DirectorCompanion";

type Props = {
  projectId: string;
  shots: ShotLite[];
  selectedShotId: string | null;
  onSelectShot: (id: string) => void;
  onIntent: (instruction: string) => void;
  children: ReactNode;
  subjects?: BindingLite[];
  onOpenDirector?: () => void;
};

type Point = { x: number; y: number };
type Gesture = { start: Point; end: Point; source: string | null; pointerId: number };

function position(index: number): Point {
  return { x: 18 + (index % 3) * 32, y: 90 + Math.floor(index / 3) * 150 };
}

/** Spatial attention is local UI state. Only the explicit request in the
 * existing Director panel can invoke an Agent; these gestures never write facts. */
export function ResonanceStage({
  projectId,
  shots,
  selectedShotId,
  onSelectShot,
  onIntent,
  children,
  subjects = [],
  onOpenDirector,
}: Props) {
  const [worldOpen, setWorldOpen] = useState(false);
  const [groupMode, setGroupMode] = useState(false);
  const [attention, setAttention] = useState<string[]>([]);
  const [subjectAttention, setSubjectAttention] = useState<string[]>([]);
  const [instruction, setInstruction] = useState("");
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const suppressClick = useRef(false);
  const selected = shots.find((shot) => shot.id === selectedShotId);
  const identities = subjects.filter((subject) => subject.purpose === "identity");
  const height = Math.max(310, Math.ceil(shots.length / 3) * 150 + 30);
  const tetherTarget = gesture?.source
    ? shots.find((shot, index) => {
        const p = position(index);
        return (
          shot.id !== gesture.source &&
          Math.abs(gesture.end.x - p.x) < 12 &&
          Math.abs(gesture.end.y - p.y) < 55
        );
      })
    : undefined;

  function connectShots(source: ShotLite, target: ShotLite) {
    setAttention([source.id, target.id]);
    setInstruction(
      `让镜头 ${source.shot_number} 与镜头 ${target.shot_number} 的情绪和动作自然衔接。`,
    );
    input.current?.focus();
  }

  function point(event: PointerEvent<HTMLDivElement>): Point {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: ((event.clientX - rect.left) / rect.width) * 100, y: event.clientY - rect.top };
  }

  function toggleAttention(id: string) {
    setAttention((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  function finishGesture(event: PointerEvent<HTMLDivElement>) {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const end = point(event);
    const moved = Math.abs(end.x - gesture.start.x) > 2 || Math.abs(end.y - gesture.start.y) > 8;
    suppressClick.current = moved;
    if (moved && gesture.source) {
      const target = shots.find((_, index) => {
        const p = position(index);
        return Math.abs(end.x - p.x) < 12 && Math.abs(end.y - p.y) < 55;
      });
      const source = shots.find((shot) => shot.id === gesture.source);
      if (source && target && source.id !== target.id) {
        connectShots(source, target);
      }
    } else if (moved) {
      setAttention(
        shots
          .filter((_, index) => {
            const p = position(index);
            return (
              p.x >= Math.min(gesture.start.x, end.x) &&
              p.x <= Math.max(gesture.start.x, end.x) &&
              p.y >= Math.min(gesture.start.y, end.y) &&
              p.y <= Math.max(gesture.start.y, end.y)
            );
          })
          .map((shot) => shot.id),
      );
    }
    setGesture(null);
  }

  return (
    <section className="rs-stage" data-testid="resonance-stage" aria-label="镜头创作画布">
      <div className="rs-world-toolbar">
        <span className="rs-world-mark">
          <i aria-hidden="true" />
          {worldOpen ? "镜头关系图" : "此刻"}
        </span>
        {onOpenDirector && (
          <DirectorCompanion
            projectId={projectId}
            shotId={selectedShotId}
            onOpen={onOpenDirector}
          />
        )}
        <button
          type="button"
          aria-label={worldOpen ? "回到当前画面" : "展开镜头关系图"}
          aria-expanded={worldOpen}
          onClick={() => setWorldOpen((value) => !value)}
        >
          {worldOpen ? <Focus size={19} /> : <Orbit size={19} />}
        </button>
      </div>
      {identities.length > 0 && (
        <div className="rs-cast" aria-label="当前镜头身份参考">
          {identities.map((subject, index) => (
            <button
              key={subject.id}
              type="button"
              aria-label={`关注身份参考：${subject.label || `角色 ${index + 1}`}`}
              aria-pressed={subjectAttention.includes(subject.id)}
              onClick={() => {
                setSubjectAttention((current) =>
                  current.includes(subject.id)
                    ? current.filter((id) => id !== subject.id)
                    : [...current, subject.id],
                );
                input.current?.focus();
              }}
            >
              <span className="rs-cast-avatar" aria-hidden="true">
                {(subject.label || `${index + 1}`).slice(0, 1)}
              </span>
              <span>{subject.label || `角色参考 ${index + 1}`}</span>
            </button>
          ))}
        </div>
      )}
      <div className={worldOpen ? "rs-media is-away" : "rs-media"} hidden={worldOpen}>
        {children}
      </div>
      {worldOpen && (
        <div className="rs-world" data-testid="resonance-world">
          <div className="rs-world-actions">
            {attention.length === 2 && (
              <button
                type="button"
                onClick={() => {
                  const source = shots.find((shot) => shot.id === attention[0]);
                  const target = shots.find((shot) => shot.id === attention[1]);
                  if (source && target) connectShots(source, target);
                }}
              >
                <Link2 size={16} />
                衔接这两刻
              </button>
            )}
            <button
              type="button"
              aria-pressed={groupMode}
              onClick={() => setGroupMode((value) => !value)}
            >
              <Focus size={16} />
              共同关注
            </button>
            {attention.length > 0 && (
              <button type="button" aria-label="清除共同关注" onClick={() => setAttention([])}>
                <X size={16} />
              </button>
            )}
          </div>
          <div className="rs-map-scroll">
            <div
              className="rs-map"
              tabIndex={0}
              aria-label="镜头关系图选择区域"
              style={{ height }}
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                const node = (event.target as Element).closest<HTMLButtonElement>(
                  "[data-world-shot]",
                );
                // Touch scrolling remains native except on nodes or in explicit group mode.
                if (event.pointerType === "touch" && !node && !groupMode) return;
                const start = point(event);
                if (!node) event.currentTarget.focus({ preventScroll: true });
                suppressClick.current = false;
                setGesture({
                  start,
                  end: start,
                  source: node?.dataset.worldShot ?? null,
                  pointerId: event.pointerId,
                });
                (node ?? event.currentTarget).setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                if (gesture?.pointerId === event.pointerId)
                  setGesture({ ...gesture, end: point(event) });
              }}
              onPointerUp={finishGesture}
              onPointerCancel={() => {
                suppressClick.current = true;
                setGesture(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  suppressClick.current = true;
                  setGesture(null);
                  setAttention([]);
                }
              }}
              data-group-mode={groupMode}
            >
              <svg className="rs-threads" width="100%" height={height} aria-hidden="true">
                {shots.slice(1).map((shot, index) => {
                  const from = position(index);
                  const to = position(index + 1);
                  return (
                    <line key={shot.id} x1={`${from.x}%`} y1={from.y} x2={`${to.x}%`} y2={to.y} />
                  );
                })}
                {gesture &&
                  (gesture.source ? (
                    <line
                      className="rs-tether"
                      x1={`${gesture.start.x}%`}
                      y1={gesture.start.y}
                      x2={`${gesture.end.x}%`}
                      y2={gesture.end.y}
                    />
                  ) : (
                    <rect
                      className="rs-enclosure"
                      x={`${Math.min(gesture.start.x, gesture.end.x)}%`}
                      y={Math.min(gesture.start.y, gesture.end.y)}
                      width={`${Math.abs(gesture.end.x - gesture.start.x)}%`}
                      height={Math.abs(gesture.end.y - gesture.start.y)}
                      rx="28"
                    />
                  ))}
              </svg>
              {shots.map((shot, index) => {
                const p = position(index);
                const included = attention.includes(shot.id);
                return (
                  <button
                    type="button"
                    key={shot.id}
                    data-world-shot={shot.id}
                    data-tether-target={tetherTarget?.id === shot.id}
                    className={`rs-world-node${shot.id === selectedShotId ? " is-current" : ""}${included ? " is-included" : ""}`}
                    style={{ left: `${p.x}%`, top: p.y }}
                    aria-label={`${groupMode ? "共同关注" : "聚焦"}镜头 ${shot.shot_number}`}
                    aria-pressed={groupMode ? included : shot.id === selectedShotId}
                    onClick={(event) => {
                      if (suppressClick.current && event.detail !== 0) {
                        suppressClick.current = false;
                        return;
                      }
                      if (groupMode || event.shiftKey) toggleAttention(shot.id);
                      else {
                        onSelectShot(shot.id);
                        setWorldOpen(false);
                      }
                    }}
                  >
                    <span className="rs-node-orb">
                      {shot.formal_keyframe_artifact_id ? (
                        <img
                          draggable={false}
                          src={artifactContentUrl(projectId, shot.formal_keyframe_artifact_id)}
                          alt=""
                        />
                      ) : (
                        <span aria-hidden="true">{String(shot.shot_number).padStart(2, "0")}</span>
                      )}
                      {included && <Check className="rs-node-check" size={16} />}
                    </span>
                    <span className="rs-node-description">
                      {shot.visual_description || `镜头 ${shot.shot_number}`}
                    </span>
                  </button>
                );
              })}
              {shots.length === 0 && <p className="rs-empty">故事尚未展开</p>}
            </div>
          </div>
        </div>
      )}
      <form
        className="rs-intent"
        data-testid="resonance-intent"
        onSubmit={(event) => {
          event.preventDefault();
          if (!selected || !instruction.trim()) return;
          const focus = shots.filter((shot) => attention.includes(shot.id));
          const context = focus.length
            ? `参考本场景镜头 ${focus.map((shot) => shot.shot_number).join("、")}，为当前镜头 ${selected.shot_number} 提出建议：`
            : "";
          const people = identities.filter((subject) => subjectAttention.includes(subject.id));
          const subjectContext = people.length
            ? `关注当前镜头身份参考 ${people.map((subject) => `「${subject.label || subject.id}」`).join("、")}。`
            : "";
          onIntent(subjectContext + context + instruction.trim());
        }}
      >
        <span
          className="rs-intent-target"
          aria-label={selected ? `当前镜头 ${selected.shot_number}` : "尚未选择镜头"}
        >
          <i aria-hidden="true" />
          {selected ? String(selected.shot_number).padStart(2, "0") : "—"}
        </span>
        <input
          ref={input}
          aria-label="此刻的创作意图"
          placeholder="你想让这一刻发生什么？"
          value={instruction}
          disabled={!selected}
          onChange={(event) => setInstruction(event.target.value)}
          maxLength={4000}
        />
        <button
          type="submit"
          aria-label="与导演讨论这个意图"
          disabled={!selected || !instruction.trim()}
        >
          <ArrowUp size={20} />
        </button>
      </form>
      {attention.length > 0 && (
        <div className="rs-attention" role="status">
          共同关注 ·{" "}
          {shots
            .filter((shot) => attention.includes(shot.id))
            .map((shot) => `镜 ${shot.shot_number}`)
            .join(" / ")}
        </div>
      )}
    </section>
  );
}
