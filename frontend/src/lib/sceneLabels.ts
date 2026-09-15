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
  const normalized = value.trim().toLowerCase().replaceAll(/[_-]+/g, " ");
  return TIME_OF_DAY_LABELS[normalized] ?? value.trim();
}
