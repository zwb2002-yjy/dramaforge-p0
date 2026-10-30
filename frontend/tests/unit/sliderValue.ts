import { fireEvent } from "@testing-library/react";

/** Exercise the library's pointer handling with a measurable rail in jsdom. */
export function sliderValue(control: HTMLElement, value: number) {
  const root = control.closest<HTMLElement>(".ant-slider") ?? control;
  const handle = root.matches('[role="slider"]')
    ? root
    : root.querySelector<HTMLElement>('[role="slider"]')!;
  const min = Number(handle.getAttribute("aria-valuemin"));
  const max = Number(handle.getAttribute("aria-valuemax"));
  root.getBoundingClientRect = () => ({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 1000,
    bottom: 10,
    width: 1000,
    height: 10,
    toJSON: () => ({}),
  });
  fireEvent.mouseDown(root, { clientX: ((value - min) / (max - min)) * 1000, clientY: 5 });
  fireEvent.mouseUp(document);
}
