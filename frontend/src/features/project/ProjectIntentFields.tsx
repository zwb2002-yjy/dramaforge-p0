import { Col, Disclosure, Form, Input, Row, Select, Textarea } from "../../components/ui";
import { WORK_TYPE_LABELS, type ProjectIntentValues, type ProjectWorkType } from "./projectIntent";

export function ProjectIntentFields({
  expanded = false,
  allowUnconfirmed = false,
}: {
  expanded?: boolean;
  allowUnconfirmed?: boolean;
}) {
  const form = Form.useFormInstance<ProjectIntentValues>();
  const workType = Form.useWatch("workType", form) ?? "";
  const details = (
    <>
      <Form.Item
        label="想做什么"
        name="creativeGoal"
        rules={[
          {
            validator: async (_, value: string | undefined) => {
              if ([...(value ?? "")].length > 16000) throw new Error("创作目标最多16000字");
            },
          },
        ]}
      >
        <Textarea
          rows={3}
          maxLength={32000}
          aria-label="想做什么"
          placeholder="例如：介绍古城传统节庆，让观众愿意来体验。"
        />
      </Form.Item>
      <Form.Item
        label="给谁看"
        name="audience"
        rules={[
          {
            validator: async (_, value: string | undefined) => {
              if ([...(value ?? "")].length > 2000) throw new Error("受众描述最多2000字");
            },
          },
        ]}
      >
        <Input maxLength={4000} aria-label="给谁看" placeholder="例如：社区居民、游客或青少年" />
      </Form.Item>
      <Row gutter={["var(--df-space-4)", "var(--df-space-4)"]}>
        <Col xs={24} sm={12}>
          <Form.Item
            label="目标总时长（秒，可选）"
            name="duration"
            tooltip="这是整部作品的时长意图；具体镜头和生成参数会在创作中确认。"
            rules={[
              {
                validator: async (_, value: string | undefined) => {
                  const input = value?.trim() ?? "";
                  if (
                    input &&
                    (!/^\d+(?:\.\d{1,3})?$/.test(input) ||
                      Number(input) <= 0 ||
                      Number(input) >= 1000000000)
                  ) {
                    throw new Error("请输入大于0的秒数，最多保留3位小数");
                  }
                },
              },
            ]}
          >
            <Input aria-label="目标总时长" inputMode="decimal" placeholder="例如 60" />
          </Form.Item>
        </Col>
        {workType !== "animation_promo" && (
          <Col xs={24} sm={12}>
            <Form.Item
              label="计划集数（可选）"
              name="episodeCount"
              dependencies={["workType"]}
              rules={[
                {
                  validator: async (_, value: string | undefined) => {
                    const input = value?.trim() ?? "";
                    if (!input) return;
                    const number = Number(input);
                    if (
                      !/^\d+$/.test(input) ||
                      !Number.isInteger(number) ||
                      number < 1 ||
                      number > 2147483647
                    ) {
                      throw new Error("请输入有效的正整数集数");
                    }
                    const currentType = form.getFieldValue("workType");
                    if (currentType === "single_comic" && number !== 1)
                      throw new Error("单集漫剧只能填写1集");
                    if (currentType === "serial_comic" && number < 2)
                      throw new Error("连续漫剧至少计划2集");
                  },
                },
              ]}
            >
              <Input
                aria-label="计划集数"
                inputMode="numeric"
                placeholder={workType === "single_comic" ? "单集仅有一集" : "可稍后确定"}
              />
            </Form.Item>
          </Col>
        )}
      </Row>
    </>
  );
  return (
    <>
      <Form.Item
        label="作品类型"
        name="workType"
        rules={[{ required: !allowUnconfirmed, message: "请选择作品类型" }]}
      >
        <Select aria-label="作品类型">
          <option value="">{allowUnconfirmed ? "待确认作品类型" : "请选择作品类型"}</option>
          {(Object.keys(WORK_TYPE_LABELS) as ProjectWorkType[]).map((key) => (
            <option key={key} value={key}>
              {WORK_TYPE_LABELS[key]}
            </option>
          ))}
        </Select>
      </Form.Item>
      {expanded ? details : <Disclosure title="创作目标与计划（可选）">{details}</Disclosure>}
    </>
  );
}
