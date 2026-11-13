import { expect, type Locator } from "@playwright/test";

function sliderHandle(control: Locator) {
  return control
    .locator(
      "xpath=ancestor-or-self::*[contains(concat(' ', normalize-space(@class), ' '), ' ant-slider ')][1]",
    )
    .getByRole("slider");
}

export async function expectSliderValue(control: Locator, value: string) {
  await expect(sliderHandle(control)).toHaveAttribute("aria-valuenow", value);
}

/** Move the visible library rail, then use its keyboard for any subpixel rounding. */
export async function sliderValue(control: Locator, value: number, step: number) {
  const handle = sliderHandle(control);
  const min = Number(await handle.getAttribute("aria-valuemin"));
  const max = Number(await handle.getAttribute("aria-valuemax"));
  const root = control.locator(
    "xpath=ancestor-or-self::*[contains(concat(' ', normalize-space(@class), ' '), ' ant-slider ')][1]",
  );
  const bounds = (await root.boundingBox())!;
  await root.click({
    position: {
      x: Math.max(
        0.01,
        Math.min(bounds.width - 0.01, (bounds.width * (value - min)) / (max - min)),
      ),
      y: bounds.height / 2,
    },
  });
  const current = Number(await handle.getAttribute("aria-valuenow"));
  const steps = Math.round((value - current) / step);
  expect(Math.abs(steps)).toBeLessThan(2000);
  await handle.focus();
  for (let index = 0; index < Math.abs(steps); index++)
    await handle.press(steps > 0 ? "ArrowRight" : "ArrowLeft");
  await expectSliderValue(control, String(value));
}
