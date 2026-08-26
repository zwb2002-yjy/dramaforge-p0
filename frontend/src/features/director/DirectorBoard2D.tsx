/**
 * DirectorBoard2D (P8-01 / 03 §72).
 *
 * Lightweight SVG director canvas: characters, camera, scene objects,
 * orientation, action path, gaze and composition bounds. Writes
 * blocking_2d (Scene.design_state) + director_state (Shot).
 */

export interface BoardElement {
  kind: "character" | "camera" | "object";
  name: string;
  x: number; // normalized 0..1
  y: number;
  orientation?: number; // degrees
  path?: Array<{ x: number; y: number }>;
  gazeTo?: string | null;
}

export interface DirectorBoard2DProps {
  elements: BoardElement[];
  compositionBounds?: { x: number; y: number; width: number; height: number };
  onChange?: (elements: BoardElement[]) => void;
}

const WIDTH = 600;
const HEIGHT = 400;

function toPx(value: number) {
  return value * WIDTH;
}

function toPxY(value: number) {
  return value * HEIGHT;
}

export function DirectorBoard2D({ elements, compositionBounds, onChange }: DirectorBoard2DProps) {
  return (
    <svg
      data-testid="director-board-2d"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full rounded border bg-gray-50"
      onClick={(event) => {
        if (!onChange) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width;
        const y = (event.clientY - rect.top) / rect.height;
        onChange([
          ...elements,
          { kind: "camera", name: `camera-${elements.length + 1}`, x, y },
        ]);
      }}
    >
      {compositionBounds ? (
        <rect
          data-testid="composition-bounds"
          x={toPx(compositionBounds.x)}
          y={toPxY(compositionBounds.y)}
          width={toPx(compositionBounds.width)}
          height={toPxY(compositionBounds.height)}
          fill="none"
          stroke="dashed"
          strokeWidth={1.5}
          className="stroke-sky-500"
        />
      ) : null}
      {elements.map((element, index) => {
        const cx = toPx(element.x);
        const cy = toPxY(element.y);
        return (
          <g key={`${element.kind}-${element.name}-${index}`} data-testid={`board-${element.kind}`}>
            <circle
              cx={cx}
              cy={cy}
              r={element.kind === "camera" ? 10 : 14}
              fill={
                element.kind === "camera"
                  ? "none"
                  : element.kind === "character"
                    ? "#dbeafe"
                    : "#fef3c7"
              }
              stroke={element.kind === "camera" ? "#2563eb" : "#b45309"}
              strokeWidth={2}
            />
            {element.path && element.path.length > 1 ? (
              <polyline
                points={element.path.map((p) => `${toPx(p.x)},${toPxY(p.y)}`).join(" ")}
                fill="none"
                stroke="#dc2626"
                strokeDasharray="4 3"
              />
            ) : null}
            <text x={cx} y={cy + (element.kind === "camera" ? 26 : -18)} textAnchor="middle" fontSize={11}>
              {element.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
