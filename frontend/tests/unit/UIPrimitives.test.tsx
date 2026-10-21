import { createRef, useState } from "react";
import type { GetRef } from "antd";
import { selectValue } from "./selectValue";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  Button,
  Checkbox,
  Drawer,
  Field,
  Fieldset,
  EmptyState,
  Input,
  InputNumber,
  PageHeader,
  Select,
  Slider,
  SegmentedControl,
  Tabs,
  Textarea,
} from "../../src/components/ui";

describe("shared UI contract", () => {
  it("keeps native labels, refs, validation and form values without accidental submission", async () => {
    const submit = vi.fn();
    const inputRef = createRef<HTMLInputElement>();
    const selectRef = createRef<GetRef<typeof Select>>();
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
    expect(selectRef.current?.nativeElement).toContainElement(screen.getByLabelText("画幅"));
    expect(textRef.current).toBe(screen.getByLabelText("故事"));
    expect(checkRef.current).toHaveAttribute("type", "checkbox");
    fireEvent.click(screen.getByRole("button", { name: "展开选项" }));
    expect(submit).not.toHaveBeenCalled();
    await selectValue(screen.getByLabelText("画幅"), "landscape");
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
      <Fieldset disabled>
        <Field>
          名称
          <Input disabled={false} />
        </Field>
        <Fieldset disabled={false}>
          <Field>
            类型
            <Select disabled={false} name="kind" defaultValue="短剧">
              <option>短剧</option>
            </Select>
          </Field>
        </Fieldset>
        <Field>
          故事
          <Textarea disabled={false} />
        </Field>
        <Field>
          <Checkbox disabled={false} />
          确认
        </Field>
        <Field>
          时长
          <InputNumber disabled={false} />
        </Field>
        <Slider disabled={false} ariaLabelForHandle="音量" />
        <Button disabled={false}>保存</Button>
      </Fieldset>,
    );
    for (const name of ["名称", "类型", "故事", "确认", "时长"])
      expect(screen.getByLabelText(name)).toBeDisabled();
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByRole("slider", { name: "音量" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByLabelText("类型").closest(".ant-select")).toHaveClass("ant-select-disabled");
    fireEvent.mouseDown(screen.getByLabelText("类型").closest(".ant-select")!);
    expect(screen.queryByRole("option", { name: "短剧" })).not.toBeInTheDocument();
  });

  it("owns arrow/Home/End navigation once and skips disabled tabs", () => {
    const select = vi.fn();
    function Example() {
      const [active, setActive] = useState("progress");
      return (
        <Tabs
          label="制作内容"
          activeKey={active}
          onChange={(key) => {
            select(key);
            setActive(key);
          }}
          items={["progress", "blocked", "settings"].map((key) => ({
            key,
            label: key,
            disabled: key === "blocked",
            children: <p>{key} panel</p>,
          }))}
        />
      );
    }
    render(<Example />);
    const first = screen.getByRole("tab", { name: "progress" });
    const last = screen.getByRole("tab", { name: "settings" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight", code: "ArrowRight" });
    expect(last).toHaveFocus();
    expect(last).toHaveAttribute("aria-selected", "false");
    fireEvent.keyDown(last, { key: "Enter", code: "Enter" });
    expect(last).toHaveAttribute("aria-selected", "true");
    expect(first).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(last, { key: "ArrowRight", code: "ArrowRight" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "Enter", code: "Enter" });
    fireEvent.keyDown(first, { key: "End", code: "End" });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: "Enter", code: "Enter" });
    fireEvent.keyDown(last, { key: "Home", code: "Home" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "Enter", code: "Enter" });
    expect(select.mock.calls.map((call) => call[0])).toEqual([
      "settings",
      "progress",
      "settings",
      "progress",
    ]);
  });

  it("changes one segmented choice with keyboard or pointer without submitting its form", () => {
    const submit = vi.fn();
    function Example() {
      const [value, setValue] = useState("all");
      return (
        <form onSubmit={submit}>
          <SegmentedControl
            label="场景状态筛选"
            value={value}
            onChange={setValue}
            options={[
              { value: "all", label: "全部" },
              { value: "pending", label: "待处理", disabled: true },
              { value: "risk", label: "风险" },
            ]}
          />
        </form>
      );
    }
    render(<Example />);
    const all = screen.getByRole("radio", { name: "全部" });
    const risk = screen.getByRole("radio", { name: "风险" });
    all.focus();
    fireEvent.keyDown(all, { key: "ArrowRight" });
    expect(risk).toBeChecked();
    expect(all).not.toBeChecked();
    fireEvent.keyDown(risk, { key: "ArrowLeft" });
    expect(all).toBeChecked();
    fireEvent.click(risk);
    expect(risk).toBeChecked();
    expect(submit).not.toHaveBeenCalled();
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

it("drawer traps focus, supports Escape, and renders overlay content", () => {
  const close = vi.fn();
  function DrawerExample() {
    return (
      <Drawer open={true} onClose={close} title="侧滑抽屉" testId="test-drawer">
        <p>抽屉内容</p>
        <Button onClick={close}>完成</Button>
      </Drawer>
    );
  }
  render(<DrawerExample />);
  expect(screen.getByTestId("test-drawer")).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("侧滑抽屉");
  expect(screen.getByText("抽屉内容")).toBeInTheDocument();

  // Test close button
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  expect(close).toHaveBeenCalledTimes(1);

  // Test escape key
  fireEvent.keyDown(document, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(2);
});
