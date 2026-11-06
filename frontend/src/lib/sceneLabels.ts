const TIME_OF_DAY_LABELS: Record<string, string> = {
  dawn: "拂晓",
  sunrise: "日出",
  morning: "清晨",
  day: "白天",
  daytime: "白天",
  noon: "中午",
  afternoon: "下午",
  "golden hour": "黄金时刻",
  sunset: "日落",
  dusk: "黄昏",
  evening: "傍晚",
  "blue hour": "蓝调时刻",
  night: "夜晚",
  midnight: "午夜",
};

export function timeOfDayLabel(value: string | null | undefined): string {
  if (!value?.trim()) return "—";
  const raw = value.trim();
  const normalized = raw.toLowerCase().replaceAll(/[_-]+/g, " ");
  const known = TIME_OF_DAY_LABELS[normalized];
  if (known) return known;
  // Chinese wording written by a creator passes through; an ASCII token is a
  // stored contract value and must not reach an ordinary surface.
  return /^\p{ASCII}+$/u.test(raw) ? "时段待确认" : raw;
}
