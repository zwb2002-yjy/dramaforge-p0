import { fireEvent, within, waitFor } from "@testing-library/react";
import { expect } from "vitest";

export function openSelect(control: Element) {
  const ancestors: Element[] = [];
  for (let parent = control.parentElement; parent; parent = parent.parentElement) {
    if (parent.classList.contains("ant-collapse-content-hidden")) ancestors.unshift(parent);
  }
  for (const panel of ancestors) {
    const header = panel.parentElement?.querySelector(".ant-collapse-header");
    if (header) fireEvent.click(header);
  }
  const root = control.closest(".ant-select") ?? control;
  if (root.querySelector('[aria-expanded="true"]')) return;
  fireEvent.mouseDown(root.querySelector("input") ?? root);
}

export function expectSelectValue(control: Element, value: string) {
  expect(control.closest(".ant-select") ?? control).toHaveAttribute("data-selected-value", value);
}

function popupFor(control: Element) {
  const root = control.closest(".ant-select") ?? control;
  const input = root.querySelector('[role="combobox"]');
  const listId = input?.getAttribute("aria-controls");
  const popup = listId
    ? document.getElementById(listId)?.closest<HTMLElement>(".ant-select-dropdown")
    : null;
  if (!popup) throw new Error("The control's popup is not open");
  return popup;
}

export async function findSelectOption(control: Element, name: string | RegExp) {
  await waitFor(() =>
    expect(control.closest(".ant-select")?.querySelector("input") ?? control).not.toBeDisabled(),
  );
  openSelect(control);
  return within(popupFor(control)).findByRole("option", { name });
}

export function selectOptions(control: Element) {
  openSelect(control);
  return Array.from(popupFor(control).querySelectorAll<HTMLElement>("[data-option-value]")).map(
    (node) => ({
      value: node.dataset.optionValue,
      label: node.textContent ?? "",
      disabled: node.closest('[aria-disabled="true"]') !== null,
    }),
  );
}

export function getSelectOption(control: Element, name: string | RegExp) {
  openSelect(control);
  return within(popupFor(control)).getByRole("option", { name });
}

/** Exercise the visible library popup, including its real disabled/selection behavior. */
export async function selectValue(control: Element, value: string) {
  await waitFor(() =>
    expect(control.closest(".ant-select")?.querySelector("input") ?? control).not.toBeDisabled(),
  );
  openSelect(control);
  const content = await waitFor(() => {
    const option = Array.from(
      popupFor(control).querySelectorAll<HTMLElement>("[data-option-value]"),
    ).find((node) => node.dataset.optionValue === value);
    if (!option) throw new Error("Select option is unavailable: " + value);
    expect(option.closest('[role="option"]')).not.toHaveAttribute("aria-disabled", "true");
    return option;
  });
  fireEvent.click(
    content.closest("[role=option]") ?? content.closest(".ant-select-item-option") ?? content,
  );
}
