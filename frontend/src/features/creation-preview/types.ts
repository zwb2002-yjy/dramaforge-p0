export type PreviewStage = {
  id: string;
  label: string;
  caption: string;
  state: "done" | "active" | "upcoming";
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
