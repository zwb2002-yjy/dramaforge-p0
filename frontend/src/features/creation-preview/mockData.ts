export type PreviewStage = {
  id: string;
  label: string;
  caption: string;
  state: "active" | "upcoming";
};

export type StoryDirection = {
  id: string;
  image: string;
  number: string;
  title: string;
  premise: string;
  tone: string;
  ending: string;
};

export type MoodReference = {
  id: string;
  image: string;
  alt: string;
};

export const previewStages: PreviewStage[] = [
  { id: "story", label: "创作方案", caption: "确定故事方向", state: "active" },
  { id: "shooting", label: "拍摄方案", caption: "人物与分镜", state: "upcoming" },
  { id: "trial", label: "代表镜头试拍", caption: "先看真实效果", state: "upcoming" },
  { id: "production", label: "正式生产", caption: "完成与交付", state: "upcoming" },
];

export const storyDirections: StoryDirection[] = [
  {
    id: "rain-stop",
    image: "/demo/story-v2/direction-01.jpg",
    number: "01",
    title: "雨停之前",
    premise: "一对多年未见的父女，在末班车到站前决定是否重新走进彼此的生活。",
    tone: "克制而温暖",
    ending: "和解",
  },
  {
    id: "last-letter",
    image: "/demo/story-v2/direction-02.jpg",
    number: "02",
    title: "凌晨来信",
    premise: "母亲误收一封写给女儿的辞职信，也第一次看见她藏起来的疲惫。",
    tone: "冷静而锋利",
    ending: "开放",
  },
  {
    id: "empty-seat",
    image: "/demo/story-v2/direction-03.jpg",
    number: "03",
    title: "空着的座位",
    premise: "旧友在深夜餐馆重逢，一把始终空着的椅子逼他们说出共同的秘密。",
    tone: "悬念与释然",
    ending: "反转",
  },
];

export const moodReferences: MoodReference[] = [
  { id: "rain-city", image: "/demo/mood-v2/rain-city.jpg", alt: "雨夜城市车窗" },
  { id: "portrait", image: "/demo/mood-v2/portrait.jpg", alt: "低照度人物侧影" },
  { id: "corridor", image: "/demo/mood-v2/corridor.jpg", alt: "列车内部纵深" },
  { id: "street", image: "/demo/mood-v2/street.jpg", alt: "雨后街道" },
  { id: "window", image: "/demo/mood-v2/window.jpg", alt: "空咖啡馆暖光" },
];

export const constraints = ["真人写实", "15–30 秒", "9:16 竖屏", "双人对白"];
