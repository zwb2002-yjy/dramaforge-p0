import { createRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  Button,
  Checkbox,
  Field,
  EmptyState,
  Input,
  PageHeader,
  Select,
  Tab,
  Tabs,
  Textarea,
} from "../../src/components/ui";

describe("shared UI contract", () => {
  it("keeps native labels, refs, validation and form values without accidental submission", () => {
    const submit = vi.fn();
    const inputRef = createRef<HTMLInputElement>();
    const selectRef = createRef<HTMLSelectElement>();
    const textRef = createRef<HTMLTextAreaElement>();
    const checkRef = createRef<HTMLInputElement>();
    render(
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit(new FormData(event.currentTarget));
        }}
      >
        <Field>
          作品名
          <Input
            ref={inputRef}
            name="title"
            required
            defaultValue="雨夜"
            aria-invalid="true"
            aria-describedby="title-error"
          />
        </Field>
        <p id="title-error">请核对名称</p>
        <Field>
          画幅
          <Select ref={selectRef} name="ratio" defaultValue="portrait">
            <option value="portrait">竖屏</option>
            <option value="landscape">横屏</option>
          </Select>
        </Field>
        <Field>
          故事
          <Textarea ref={textRef} name="story" defaultValue="两人在车站重逢" />
        </Field>
        <Field>
          <Checkbox ref={checkRef} name="confirm" defaultChecked />
          保留草稿
        </Field>
        <Button>展开选项</Button>
        <Button type="submit">保存</Button>
      </form>,
    );
    expect(inputRef.current).toBe(screen.getByLabelText("作品名"));
    expect(inputRef.current).toBeRequired();
    expect(inputRef.current).toHaveAccessibleDescription("请核对名称");
    expect(selectRef.current).toBe(screen.getByLabelText("画幅"));
    expect(textRef.current).toBe(screen.getByLabelText("故事"));
    expect(checkRef.current).toHaveClass("df-checkbox");
    expect(checkRef.current).not.toHaveClass("df-input");
    fireEvent.click(screen.getByRole("button", { name: "展开选项" }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(selectRef.current!, { target: { value: "landscape" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(Object.fromEntries(submit.mock.calls[0][0])).toEqual({
      title: "雨夜",
      ratio: "landscape",
      story: "两人在车站重逢",
      confirm: "on",
    });
  });

  it("preserves disabled form semantics", () => {
    render(
      <fieldset disabled>
        <Field>
          名称
          <Input />
        </Field>
        <Field>
          类型
          <Select>
            <option>短剧</option>
          </Select>
        </Field>
        <Field>
          故事
          <Textarea />
        </Field>
        <Field>
          <Checkbox />
          确认
        </Field>
        <Button>保存</Button>
      </fieldset>,
    );
    for (const name of ["名称", "类型", "故事", "确认"])
      expect(screen.getByLabelText(name)).toBeDisabled();
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("owns arrow/Home/End navigation once and skips disabled tabs", () => {
    const select = vi.fn();
    function Example() {
      const [active, setActive] = useState("progress");
      return (
        <Tabs label="制作内容">
          {["progress", "blocked", "settings"].map((key) => (
            <Tab
              key={key}
              active={active === key}
              disabled={key === "blocked"}
              onClick={() => {
                select(key);
                setActive(key);
              }}
            >
              {key}
            </Tab>
          ))}
        </Tabs>
      );
    }
    render(<Example />);
    const first = screen.getByRole("tab", { name: "progress" });
    const last = screen.getByRole("tab", { name: "settings" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(last).toHaveFocus();
    expect(last).toHaveAttribute("aria-selected", "true");
    expect(first).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(last, { key: "ArrowRight" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "End" });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: "Home" });
    expect(first).toHaveFocus();
    expect(select.mock.calls.map((call) => call[0])).toEqual([
      "settings",
      "progress",
      "settings",
      "progress",
    ]);
  });

  it("keeps notices and actions in the common page header", () => {
    render(
      <PageHeader title="剪辑交接" description="已确认的视频" actions={<Button>保存</Button>}>
        <p role="status">生产血缘只读</p>
      </PageHeader>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("剪辑交接");
    expect(screen.getByRole("status")).toHaveTextContent("生产血缘只读");
    expect(screen.getByRole("button", { name: "保存" })).toBeVisible();
  });
});

it("empty state keeps its title, explanation and explicit action accessible", () => {
  const action = vi.fn();
  render(
    <EmptyState
      title="开始你的故事"
      description="从一个想法开始"
      icon={<svg data-testid="empty-icon" />}
    >
      <Button onClick={action}>新建项目</Button>
    </EmptyState>,
  );
  expect(screen.getByRole("heading", { name: "开始你的故事" })).toBeInTheDocument();
  expect(screen.getByText("从一个想法开始")).toBeInTheDocument();
  expect(screen.getByTestId("empty-icon").parentElement).toHaveAttribute("aria-hidden", "true");
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "新建项目" }));
  expect(action).toHaveBeenCalledTimes(1);
});
