import {
  Button as AntButton,
  Card as AntCard,
  Checkbox as AntCheckbox,
  Empty,
  Input as AntInput,
  InputNumber as AntInputNumber,
  Radio as AntRadio,
  Segmented,
  Slider as AntSlider,
  Select as AntSelect,
  Tabs as AntTabs,
  Tag,
  Typography,
  Form,
  ConfigProvider,
  type SelectProps as AntSelectProps,
  type GetRef,
  type CheckboxProps,
  type RadioProps,
  type TabsProps,
  type InputNumberProps,
  type GetProps,
  type ButtonProps as AntButtonProps,
} from "antd";
import {
  Children,
  cloneElement,
  createContext,
  forwardRef,
  isValidElement,
  useId,
  useContext,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type FieldsetHTMLAttributes,
  type LabelHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

const classes = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");
const FieldsetDisabled = createContext(false);
const useDisabled = (disabled?: boolean) => useContext(FieldsetDisabled) || disabled;
type ButtonTone = "default" | "primary" | "accent" | "ghost" | "danger";
type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "color"> &
  Pick<AntButtonProps, "block" | "size"> & { tone?: ButtonTone };

/** Product action tones map to the library, with no independent button recipe. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, tone = "default", type = "button", ...props },
  ref,
) {
  const disabled = useDisabled(props.disabled);
  return (
    <AntButton
      {...props}
      disabled={disabled}
      ref={ref}
      htmlType={type}
      autoInsertSpace={false}
      type={
        tone === "primary" || tone === "accent" ? "primary" : tone === "ghost" ? "text" : "default"
      }
      danger={tone === "danger"}
      color={tone === "accent" ? "gold" : undefined}
      variant={tone === "accent" ? "solid" : undefined}
      className={classes("df-action", className)}
    />
  );
});

export function Card({
  className,
  selected = false,
  hidden,
  style,
  ...props
}: HTMLAttributes<HTMLElement> & { selected?: boolean }) {
  return (
    <AntCard
      role={props["aria-label"] ? "region" : "article"}
      size="small"
      className={classes("df-card", className)}
      data-selected={selected}
      hidden={hidden}
      style={{ minWidth: 0, ...style, ...(hidden ? { display: "none" } : {}) }}
      {...props}
    />
  );
}

export function PageHeader({
  title,
  eyebrow,
  description,
  actions,
  children,
  className,
  ...props
}: HTMLAttributes<HTMLElement> & {
  title: string;
  eyebrow?: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className={classes("df-page-header", className)} {...props}>
      <div className="df-page-header-copy">
        {eyebrow && <Typography.Text type="secondary">{eyebrow}</Typography.Text>}
        <Typography.Title level={1}>{title}</Typography.Title>
        {description && (
          <Typography.Paragraph className="df-page-description" type="secondary">
            {description}
          </Typography.Paragraph>
        )}
        {children}
      </div>
      {actions && <div className="df-page-header-actions">{actions}</div>}
    </header>
  );
}

export const Input = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "prefix"> & { prefix?: ReactNode; suffix?: ReactNode }
>(function Input({ size, ...props }, ref) {
  const disabled = useDisabled(props.disabled);
  return (
    <AntInput
      {...props}
      disabled={disabled}
      htmlSize={size}
      status={
        props["aria-invalid"] === true || props["aria-invalid"] === "true" ? "error" : undefined
      }
      ref={(instance) => {
        if (typeof ref === "function") ref(instance?.input ?? null);
        else if (ref) ref.current = instance?.input ?? null;
      }}
    />
  );
});

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea(props, ref) {
  const disabled = useDisabled(props.disabled);
  return (
    <AntInput.TextArea
      {...props}
      disabled={disabled}
      ref={(instance) => {
        const input = instance?.resizableTextArea?.textArea ?? null;
        if (typeof ref === "function") ref(input);
        else if (ref) ref.current = input;
      }}
    />
  );
});

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps & { type?: "checkbox" }>(
  function Checkbox(props, ref) {
    const disabled = useDisabled(props.disabled);
    return (
      <AntCheckbox
        {...props}
        disabled={disabled}
        value={props.value ?? "on"}
        ref={(instance) => {
          if (typeof ref === "function") ref(instance?.input ?? null);
          else if (ref) ref.current = instance?.input ?? null;
        }}
      />
    );
  },
);

export const Radio = forwardRef<HTMLInputElement, RadioProps & { type?: "radio" }>(
  function Radio(props, ref) {
    const disabled = useDisabled(props.disabled);
    return (
      <AntRadio
        {...props}
        disabled={disabled}
        ref={(instance) => {
          if (typeof ref === "function") ref(instance?.input ?? null);
          else if (ref) ref.current = instance?.input ?? null;
        }}
      />
    );
  },
);

/** Native form serialization and library popup controls share the same disabled scope. */
export function Fieldset({ disabled, ...props }: FieldsetHTMLAttributes<HTMLFieldSetElement>) {
  const effectiveDisabled = useDisabled(disabled);
  return (
    <FieldsetDisabled.Provider value={Boolean(effectiveDisabled)}>
      <ConfigProvider componentDisabled={effectiveDisabled}>
        <fieldset disabled={effectiveDisabled} {...props} />
      </ConfigProvider>
    </FieldsetDisabled.Provider>
  );
}

export const InputNumber = forwardRef<GetRef<typeof AntInputNumber>, InputNumberProps<number>>(
  function InputNumber(props, ref) {
    const disabled = useDisabled(props.disabled);
    return <AntInputNumber {...props} disabled={disabled} ref={ref} />;
  },
);

export const Slider = forwardRef<GetRef<typeof AntSlider>, GetProps<typeof AntSlider>>(
  function Slider(props, ref) {
    const groupDisabled = useContext(FieldsetDisabled);
    return <AntSlider {...props} disabled={groupDisabled || props.disabled} ref={ref} />;
  },
);

/** Labels are semantic layout around library controls, never a second control runtime. */
export function Field({
  className,
  layout = "stacked",
  children,
  htmlFor,
  ...props
}: Omit<LabelHTMLAttributes<HTMLLabelElement>, "onReset"> & { layout?: "stacked" | "inline" }) {
  const generatedId = useId();
  const nodes = Children.toArray(children);
  const controlIndex = nodes.findIndex(
    (node) =>
      isValidElement(node) &&
      [Input, InputNumber, Select, Textarea, Checkbox, Radio, Slider, "input"].includes(
        node.type as typeof Input,
      ),
  );
  const control = nodes[controlIndex];
  if (!isValidElement<{ id?: string; children?: ReactNode }>(control)) {
    return (
      <Form.Item
        className={className}
        htmlFor={htmlFor}
        label={htmlFor ? children : undefined}
        colon={false}
      >
        {!htmlFor && children}
      </Form.Item>
    );
  }
  const label = nodes.filter((_, index) => index !== controlIndex);
  const id = control.props.id ?? htmlFor ?? generatedId;
  const checkable = control.type === Checkbox || control.type === Radio;
  return (
    <Form.Item
      {...props}
      className={className}
      layout={layout === "inline" ? "horizontal" : "vertical"}
      label={checkable ? undefined : <>{label}</>}
      htmlFor={id}
      colon={false}
    >
      {cloneElement(control, { id, ...(checkable ? { children: <>{label}</> } : {}) })}
    </Form.Item>
  );
}

type OptionNode = {
  value?: string | number;
  disabled?: boolean;
  label?: ReactNode;
  children?: ReactNode;
};
type SelectRef = GetRef<typeof AntSelect>;
type OptionData = NonNullable<AntSelectProps<string>["options"]>[number];
function optionData(children: ReactNode): AntSelectProps<string>["options"] {
  return Children.toArray(children).flatMap<OptionData>((node) => {
    if (!isValidElement<OptionNode>(node)) return [];
    const { value, disabled, label, children: content } = node.props;
    if (node.type === "optgroup") return [{ label, options: optionData(content) }];
    return [{ value: String(value ?? content ?? ""), label: content, disabled }];
  });
}
type SelectProps = Omit<
  AntSelectProps<string>,
  "value" | "defaultValue" | "onChange" | "children"
> & {
  value?: string | number;
  defaultValue?: string | number;
  children?: ReactNode;
  name?: string;
  required?: boolean;
  onChange?: (value: string) => void;
};
/** Declarative options are data only; Ant Design owns the popup and keyboard behavior. */
export const Select = forwardRef<SelectRef, SelectProps>(function Select(
  { children, value, defaultValue, onChange, options, name, required, disabled, style, ...props },
  ref,
) {
  const generatedId = useId();
  const [local, setLocal] = useState(defaultValue === undefined ? undefined : String(defaultValue));
  const effectiveDisabled = useDisabled(disabled);
  const current = value === undefined ? local : String(value);
  return (
    <>
      <AntSelect
        {...props}
        id={props.id ?? generatedId}
        ref={ref}
        value={current}
        options={options ?? optionData(children)}
        data-selected-value={current ?? ""}
        virtual={false}
        style={{ width: "100%", minWidth: 0, ...style }}
        disabled={effectiveDisabled}
        aria-required={required || undefined}
        showSearch={{ optionFilterProp: "label" }}
        optionRender={(option) => (
          <span data-option-value={String(option.value)}>{option.label}</span>
        )}
        onChange={(next) => {
          setLocal(next);
          onChange?.(next);
        }}
      />
      {name && (
        <input type="hidden" name={name} value={current ?? ""} disabled={effectiveDisabled} />
      )}
    </>
  );
});

/** A named work region; Ant Design owns tabs, panels and their ARIA relationship. */
export function Tabs({ label, ...props }: TabsProps & { label: string }) {
  return (
    <section aria-label={label}>
      <AntTabs {...props} />
    </section>
  );
}

export function SegmentedControl<Value extends string>({
  label,
  value,
  options,
  onChange,
  className,
  ...props
}: Omit<HTMLAttributes<HTMLDivElement>, "onChange" | "children" | "defaultValue"> & {
  label: string;
  value: Value;
  disabled?: boolean;
  options: ReadonlyArray<{ value: Value; label: ReactNode; disabled?: boolean }>;
  onChange: (value: Value) => void;
}) {
  const disabled = useDisabled(props.disabled);
  return (
    <Segmented<Value>
      {...props}
      disabled={disabled}
      className={className}
      aria-label={label}
      value={value}
      options={[...options]}
      onChange={onChange}
    />
  );
}

type BadgeTone = "default" | "success" | "warning" | "danger" | "info" | "selected";
export function Badge({
  tone = "default",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  const colors: Record<BadgeTone, string | undefined> = {
    default: undefined,
    success: "success",
    warning: "warning",
    danger: "error",
    info: "processing",
    selected: "cyan",
  };
  return <Tag color={colors[tone]} {...props} />;
}

export function EmptyState({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Empty
      image={icon ? <span aria-hidden="true">{icon}</span> : Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <>
          <Typography.Title level={3}>{title}</Typography.Title>
          {description && <Typography.Text type="secondary">{description}</Typography.Text>}
        </>
      }
    >
      {children}
    </Empty>
  );
}

export { Disclosure } from "./Disclosure";
export { Dialog } from "./Dialog";
export { Drawer } from "./Drawer";
export { SectionHeader, MetadataList, RecordList, RecordItem } from "./DataDisplay";
export { UiProvider } from "./UiProvider";
export { ActionLink } from "./ActionLink";
export { AntButton as ExternalLink };
export {
  Alert,
  Descriptions,
  Dropdown,
  Popconfirm,
  Progress,
  Skeleton,
  Space,
  Spin,
  Statistic,
  Table,
  Tooltip,
  Upload,
  Form,
  Row,
  Col,
  Flex,
} from "antd";
