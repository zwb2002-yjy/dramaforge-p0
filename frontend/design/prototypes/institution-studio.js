/* Standalone D6 interaction prototype. Synthetic in-memory data only; no network APIs. */
(() => {
  "use strict";
  const h = React.createElement;
  const { useState, useRef } = React;
  const {
    Button,
    Card,
    Tag,
    Input,
    Select,
    Radio,
    Modal,
    Drawer,
    Tabs,
    Form,
    Alert,
    Empty,
    Checkbox,
    Collapse,
    ConfigProvider,
    App: AntApp,
  } = antd;
  const css = getComputedStyle(document.documentElement),
    t = (n) => css.getPropertyValue("--df-" + n).trim();
  const px = (n) => parseFloat(t(n)) * (t(n).endsWith("rem") ? 16 : 1);
  const theme = {
    algorithm: antd.theme.darkAlgorithm,
    token: {
      colorPrimary: t("verdigris"),
      colorInfo: t("verdigris"),
      colorBgBase: t("surface-0"),
      colorBgContainer: t("surface-1"),
      colorBgElevated: t("surface-2"),
      colorText: t("text-primary"),
      colorTextSecondary: t("text-secondary"),
      colorBorder: t("border"),
      colorWarning: t("warning"),
      colorError: t("danger"),
      fontFamily: t("font-sans"),
      fontSize: px("text-base"),
      controlHeight: px("control-height"),
      borderRadius: px("radius-control"),
      borderRadiusLG: px("radius-container"),
      motion: false,
    },
    components: {
      Button: { primaryColor: t("text-inverse") },
      Card: { bodyPadding: px("space-4") },
    },
  };
  const row = (...x) => h("div", { className: "row" }, ...x),
    stack = (...x) => h("div", { className: "stack" }, ...x),
    note = (x) => h("p", { className: "subtle" }, x);
  const btn = (text, fn, props = {}) => h(Button, { onClick: fn, ...props }, text),
    box = (title, body, props = {}) => h(Card, { title, ...props }, body);
  const field = (label, child) => h(Form.Item, { label }, child);
  const projects = [
    {
      id: "film",
      title: "青溪古桥 · 让记忆继续",
      type: "动画宣传片",
      goal: "面向游客介绍古桥的文化价值",
      length: "90 秒 · 16:9",
    },
    {
      id: "single",
      title: "桥边的守望",
      type: "单集漫剧",
      goal: "讲述年轻人与修桥人的完整故事",
      length: "3 分钟 · 9:16",
    },
    {
      id: "series",
      title: "青溪记事",
      type: "多集连续漫剧",
      goal: "用两代人的故事讲述守护与传承",
      length: "2 集 · 每集 3 分钟",
    },
  ];
  const nav = [
    ["home", "项目概览"],
    ["files", "项目资料"],
    ["research", "文化研究"],
    ["story", "故事与内容"],
    ["characters", "人物形象"],
    ["scenes", "场景环境"],
    ["images", "图片素材"],
    ["videos", "视频素材"],
    ["public", "公共资产"],
    ["delivery", "成片交付"],
  ];
  const models = [
    {
      id: "img-a",
      kind: "image",
      name: "画境 A（示例）",
      scene: "人物与环境设定",
      resolution: ["1024×1024", "1536×1024"],
      references: 3,
    },
    {
      id: "img-b",
      kind: "image",
      name: "画境 B（示例）",
      scene: "单参考图快速构图",
      resolution: ["1024×1024"],
      references: 1,
    },
    {
      id: "vid-a",
      kind: "video",
      name: "流影 A（示例）",
      scene: "首尾帧连续画面",
      resolution: ["720p", "1080p"],
      durations: [5, 10],
      references: 2,
      firstLast: true,
    },
    {
      id: "vid-b",
      kind: "video",
      name: "流影 B（示例）",
      scene: "文字短片段",
      resolution: ["720p"],
      durations: [5],
      references: 0,
      firstLast: false,
    },
    {
      id: "speech-a",
      kind: "voice",
      name: "清声 A（示例）",
      scene: "中文叙事配音",
      voices: ["温和", "清晰"],
    },
    {
      id: "speech-b",
      kind: "voice",
      name: "清声 B（示例）",
      scene: "角色对白",
      voices: ["青年", "长者"],
    },
  ];
  const kindName = { image: "图片", video: "视频", voice: "语音" };
  const initial = (id) => ({
    files: false,
    research: "青溪古桥连接村落与集市，承载共同记忆。",
    rev: 1,
    history: [],
    knowledge: null,
    defaults: { image: "", video: "", voice: "" },
    configRev: 1,
    candidates: [0, 1, 2].map((i) => ({
      id: "demo-" + id + "-" + i,
      kind: "image",
      episode: "1",
      title: ["古桥 · 清晨微光", "古桥 · 柔和暮色", "古桥 · 节庆氛围"][i],
      summary: "保留古桥形制与温暖的地方文化氛围。",
      variant: i,
      model: "img-a",
    })),
    adopted: [],
    stories: {},
    links: [],
    variants: [],
    formal: {},
    reviewed: {},
    edit: {},
    exports: {},
    paused: false,
    messages: [
      {
        id: "welcome-" + id,
        role: "assistant",
        episode: "1",
        body: "这里准备了三份合成构图示例。你可以直接选择比较，也可以告诉我想修改的表情、光线或整体氛围。",
        results: ["demo-" + id + "-0"],
      },
    ],
    constraints: "人物：年轻来访者与修桥人；场景：青溪古桥；风格：温暖写实。",
  });
  function Art({ variant = 0, label = "合成构图示意 · 非生成媒体" }) {
    return h(
      "div",
      { className: "art" },
      h(
        "svg",
        { viewBox: "0 0 640 360", role: "img", "aria-label": "古桥构图示意" },
        h("rect", { width: 640, height: 360, fill: t("surface-2") }),
        h("path", { d: "M0 200L130 90 260 200 420 60 640 200V360H0Z", fill: t("surface-3") }),
        h("path", { d: "M0 290Q320 240 640 290V360H0Z", fill: t("verdigris-tint") }),
        h("path", {
          d:
            variant % 2
              ? "M60 250Q300 45 580 250L580 277Q300 80 60 277Z"
              : "M90 230Q320 45 550 230L550 258Q320 85 90 258Z",
          fill: t("brass-dim"),
        }),
        h("circle", { cx: variant % 2 ? 160 : 510, cy: 75, r: 24, fill: t("brass-tint") }),
      ),
      h("span", { className: "art-label" }, label),
    );
  }
  function Studio() {
    const { message, modal } = AntApp.useApp();
    const [all, setAll] = useState(Object.fromEntries(projects.map((p) => [p.id, initial(p.id)]))),
      [pid, setPid] = useState("film"),
      [ep, setEp] = useState("1");
    const [view, setView] = useState("home"),
      [selected, setSelected] = useState(null),
      [compare, setCompare] = useState(false),
      [text, setText] = useState("");
    const [researchDraft, setResearchDraft] = useState(null),
      [editDraft, setEditDraft] = useState(null),
      [scenario, setScenario] = useState("normal");
    const [settings, setSettings] = useState(null),
      [connections, setConnections] = useState(false),
      [modelDraft, setModelDraft] = useState({});
    const [task, setTask] = useState(null),
      [request, setRequest] = useState(null),
      [sourceOpen, setSourceOpen] = useState(false),
      [leftOpen, setLeftOpen] = useState(false),
      [chatOpen, setChatOpen] = useState(false);
    const chatRef = useRef(null),
      seq = useRef(0);
    const p = projects.find((x) => x.id === pid),
      s = all[pid],
      episode = pid === "series" ? ep : "1";
    const patch = (x) => setAll((old) => ({ ...old, [pid]: { ...old[pid], ...x } }));
    const mutate = (fn) => {
      if (scenario === "offline") {
        message.error("离线：操作未保存，输入仍保留。恢复连接后请明确重试。");
        return;
      }
      if (scenario === "conflict") {
        message.warning("版本已变化：输入保留，请核对新旧内容。");
        return;
      }
      fn();
    };
    const dirty = researchDraft !== null || editDraft !== null;
    function navigate(fn) {
      if (!dirty) {
        fn();
        return;
      }
      modal.confirm({
        title: "保留还是放弃未保存修改？",
        content: "继续编辑不会离开。放弃仅清除本次未保存输入。",
        okText: "放弃并离开",
        cancelText: "继续编辑",
        onOk: () => {
          setResearchDraft(null);
          setEditDraft(null);
          fn();
        },
      });
    }
    function go(v) {
      navigate(() => {
        setView(v);
        setLeftOpen(false);
        setSelected(null);
        setCompare(false);
      });
    }
    function confirm(title, content, fn, label = "确认") {
      modal.confirm({
        title,
        content,
        okText: label,
        cancelText: "返回修改",
        onOk: () => mutate(fn),
      });
    }
    const current = s.candidates.filter((x) => x.episode === episode),
      visible = current.filter((x) =>
        view === "audio"
          ? x.kind === "voice"
          : view === "story"
            ? x.kind === "story"
            : view === "videos"
              ? x.kind === "video"
              : view === "images" || view === "characters" || view === "scenes"
                ? x.kind === "image"
                : true,
      ),
      chosen = visible.find((x) => x.id === selected) || visible[0];
    const model = (id) => models.find((x) => x.id === id);
    function openSettings(tab) {
      setModelDraft({ ...s.defaults });
      setSettings(tab);
    }
    function propose() {
      if (!text.trim()) return;
      mutate(() => {
        patch({
          messages: [
            ...s.messages,
            { id: ++seq.current, role: "user", body: text, episode },
            {
              id: ++seq.current,
              role: "assistant",
              body: "我会保留已确认设定，把这次想法整理成可修改的创作要求。确认后再制作候选。",
              episode,
            },
          ],
        });
        setRequest({
          summary: text,
          kind: view === "story" ? "story" : view === "videos" ? "video" : "image",
          advanced: "",
          episode,
        });
        setText("");
      });
    }
    function startPreview(kind = request?.kind || "image") {
      if (kind === "story") {
        confirm(
          "形成故事候选",
          stack(
            note(request?.summary || "继续优化故事"),
            note("仅生成待采用的故事提案；已确认故事和设定保持不变。原型不调用语言模型。"),
          ),
          () => {
            const base = ++seq.current;
            const outputs = ["从记忆出发", "沿古桥探访"].map((title, i) => ({
              id: "story-" + base + "-" + i,
              kind: "story",
              episode,
              title,
              summary:
                (request?.summary || "继续优化故事") +
                "\n\n" +
                (i
                  ? "来访者走过古桥，从集市、桥面和村民的讲述中认识地方生活。"
                  : "年轻人询问修桥的往事，村民讲述赶集、节庆与共同守护的记忆。") +
                "\n\n结尾：人们再次走过古桥，守护延续。",
              variant: i,
            }));
            patch({
              candidates: [...outputs, ...s.candidates],
              messages: [
                ...s.messages,
                {
                  id: ++seq.current,
                  role: "assistant",
                  episode,
                  body: "两份故事候选已同步到中央，选中不等于采用。",
                  results: outputs.map((x) => x.id),
                },
              ],
            });
            setView("story");
            setSelected(outputs[0].id);
            setRequest(null);
          },
          "模拟形成故事候选",
        );
        return;
      }
      setTask({
        kind,
        model: s.defaults[kind],
        resolution: "",
        duration: 5,
        references: 0,
        firstLast: false,
        voice: "",
        confirmed: false,
        summary: request?.summary || "保留已确认设定，优化当前作品的氛围。",
        advanced: request?.advanced || "",
        episode,
      });
    }
    function switchTask(id) {
      const next = model(id);
      confirm(
        "更换本次模型",
        stack(
          note("从 " + (model(task.model)?.name || "未配置") + " 改为 " + next.name),
          note("适用场景：" + next.scene),
          note(
            "分辨率：" +
              (next.resolution || ["不适用"]).join("、") +
              "；可用参考素材：" +
              (next.references ?? "不适用"),
          ),
          note("仅影响本次。原参数和素材保留待核对，原确认失效。"),
        ),
        () => setTask({ ...task, model: id, confirmed: false }),
        "使用此模型并核对",
      );
    }
    function generate() {
      mutate(() => {
        const base = ++seq.current;
        const outputs = [0, 1].map((i) => ({
          id: "candidate-" + base + "-" + i,
          kind: task.kind,
          episode: task.episode,
          title:
            task.kind === "voice"
              ? "配音 · " + (i ? "清晰叙述" : "温和叙述")
              : "古桥 · " + (i ? "柔和暮色" : "清晨微光"),
          summary: task.summary,
          model: task.model,
          variant: i,
        }));
        patch({
          candidates: [...outputs, ...s.candidates],
          messages: [
            ...s.messages,
            {
              id: ++seq.current,
              role: "assistant",
              body: "已准备两个合成候选，请在中央比较。它们尚未成为正式内容。",
              episode: task.episode,
              results: outputs.map((x) => x.id),
            },
          ],
        });
        setSelected(outputs[0].id);
        setView(task.kind === "video" ? "videos" : task.kind === "voice" ? "audio" : "images");
        setTask(null);
        setRequest(null);
      });
    }
    function adopt(c) {
      if (c.kind === "story") {
        confirm(
          "采用故事提案",
          stack(
            note(c.title),
            note("仅更新当前分集故事，不开始媒体制作，不改变已确认人物和视觉设定。"),
          ),
          () => patch({ stories: { ...s.stories, [episode]: c.id } }),
          "采用这份故事",
        );
        return;
      }
      confirm(
        "采用为正式素材",
        stack(
          note(c.title),
          note(
            "将这个候选保存为当前项目已采用资产，并进入同一用户公共资产库。私有资料不公开；已确认人物与风格不被替换。",
          ),
        ),
        () => patch({ adopted: [...new Set([...s.adopted, c.id])] }),
        "采用此候选",
      );
    }
    function settingsBody() {
      return h(Tabs, {
        activeKey: settings,
        onChange: setSettings,
        items: [
          {
            key: "platform",
            label: "平台模型管理",
            children: stack(
              h(Tag, null, "当前工作空间 · 合成管理数据"),
              note("平台管理集中处理连接、凭据与能力。不会自动把连接共享到其他工作空间。"),
              h(
                Form,
                { layout: "vertical" },
                stack(
                  field(
                    "连接名称",
                    h(Input, { defaultValue: "演示模型服务", "aria-label": "连接名称" }),
                  ),
                  field(
                    "供应商地址",
                    h(Input, { value: "https://models.example.invalid/v1", readOnly: true }),
                  ),
                  field("API Key", h(Input.Password, { value: "DEMO-NOT-A-KEY", readOnly: true })),
                ),
              ),
              btn(
                "模拟连接检查与目录读取",
                () =>
                  mutate(() => {
                    setConnections(true);
                    message.success("模拟目录已读取；未执行生成测试。");
                  }),
                { type: "primary" },
              ),
              h(Alert, { type: "info", title: "连接检查不提交生成。原型不接收真实凭据。" }),
              connections &&
                stack(
                  ...models.map((m) =>
                    box(
                      m.name,
                      stack(
                        note(m.scene),
                        note(
                          "支持：" +
                            (m.resolution?.join("、") || m.voices?.join("、")) +
                            (m.durations ? "；" + m.durations.join("/") + " 秒" : ""),
                        ),
                        h(Tag, null, "合成能力 · 无真实生成证据"),
                      ),
                      { key: m.id },
                    ),
                  ),
                ),
            ),
          },
          {
            key: "project",
            label: "项目默认模型",
            children: stack(
              note("选择会明确保存到“" + p.title + "”。推荐只提供候选，不自动替你选择。"),
              ...["image", "video", "voice"].map((kind) =>
                box(
                  "默认" + kindName[kind] + "模型",
                  stack(
                    !s.defaults[kind] && h(Tag, { color: "gold" }, "未配置"),
                    note("已保存：" + (model(s.defaults[kind])?.name || "尚未指定")),
                    connections
                      ? h(
                          Radio.Group,
                          {
                            "aria-label": "默认" + kindName[kind] + "模型",
                            value: modelDraft[kind],
                            onChange: (e) =>
                              setModelDraft({ ...modelDraft, [kind]: e.target.value }),
                          },
                          stack(
                            ...models
                              .filter((m) => m.kind === kind)
                              .map((m) =>
                                h(
                                  Radio,
                                  { value: m.id, key: m.id },
                                  stack(h("strong", null, m.name), note(m.scene)),
                                ),
                              ),
                          ),
                        )
                      : btn("先接入可用模型", () => setSettings("platform")),
                    connections &&
                      btn("查看" + kindName[kind] + "推荐", () => {
                        const m = models.find((m) => m.kind === kind);
                        confirm(
                          "推荐 " + m.name,
                          stack(
                            note("依据：匹配当前项目的" + m.scene + "需求。"),
                            note("这是合成能力说明，不代表实际效果保证。选择后仍需保存项目设置。"),
                          ),
                          () => setModelDraft({ ...modelDraft, [kind]: m.id }),
                          "选入待保存设置",
                        );
                      }),
                  ),
                  { key: kind },
                ),
              ),
              btn(
                "保存项目模型设置",
                () =>
                  mutate(() => {
                    patch({ defaults: { ...modelDraft }, configRev: s.configRev + 1 });
                    message.success("已保存当前项目默认；未配置项仍会阻止相关制作。");
                  }),
                { type: "primary" },
              ),
              note("有对白时语音未配置会提示设置，不回退Edge或其他未知模型。"),
            ),
          },
        ],
      });
    }
    function taskBody() {
      if (!task) return null;
      const m = model(task.model),
        available = connections ? models.filter((x) => x.kind === task.kind) : [];
      const incompatible =
        !!m &&
        ((task.resolution && !m.resolution?.includes(task.resolution)) ||
          task.references > (m.references ?? 0) ||
          (task.firstLast && !m.firstLast) ||
          (task.kind === "video" && !m.durations.includes(task.duration)));
      const blocked =
        !m ||
        incompatible ||
        s.paused ||
        ["unknown", "denied", "waiting", "failed"].includes(scenario);
      return stack(
        note("本次创作：" + task.summary),
        task.advanced && note("高级补充：" + task.advanced),
        note("当前项目 / " + (pid === "series" ? "第 " + task.episode + " 集" : p.type)),
        h(
          Tag,
          null,
          task.model === s.defaults[task.kind] ? "继承项目默认" : "本次临时指定 · 不改项目默认",
        ),
        !m &&
          h(Alert, {
            type: "warning",
            title: "请先设置项目" + kindName[task.kind] + "模型",
            action: btn("去项目模型设置", () => {
              setTask(null);
              openSettings("project");
            }),
          }),
        available.length > 0 &&
          h(
            Radio.Group,
            {
              "aria-label": "本次生成模型",
              value: task.model,
              onChange: (e) => switchTask(e.target.value),
            },
            stack(
              ...available.map((x) =>
                h(Radio, { value: x.id, key: x.id }, x.name + " · " + x.scene),
              ),
            ),
          ),
        m &&
          h(
            Form,
            { layout: "vertical" },
            stack(
              note("示例支持能力 · " + m.scene),
              m.resolution &&
                field(
                  "分辨率",
                  h(Select, {
                    "aria-label": "分辨率",
                    value: task.resolution || m.resolution[0],
                    options: m.resolution.map((x) => ({ value: x, label: x })),
                    onChange: (v) => setTask({ ...task, resolution: v, confirmed: false }),
                  }),
                ),
              m.durations &&
                field(
                  "时长",
                  h(Select, {
                    "aria-label": "时长",
                    value: task.duration,
                    options: m.durations.map((x) => ({ value: x, label: x + " 秒" })),
                    onChange: (v) => setTask({ ...task, duration: v, confirmed: false }),
                  }),
                ),
              m.references > 0 &&
                field(
                  "参考素材",
                  h(Select, {
                    "aria-label": "参考素材数量",
                    value: task.references,
                    options: [0, 1, 2, 3]
                      .filter((x) => x <= m.references)
                      .map((x) => ({ value: x, label: x + " 个合成参考" })),
                    onChange: (v) => setTask({ ...task, references: v, confirmed: false }),
                  }),
                ),
              m.firstLast &&
                h(
                  Checkbox,
                  {
                    checked: task.firstLast,
                    onChange: (e) =>
                      setTask({ ...task, firstLast: e.target.checked, confirmed: false }),
                  },
                  "使用首尾帧",
                ),
              m.voices &&
                field(
                  "音色",
                  h(Select, {
                    "aria-label": "音色",
                    value: task.voice || m.voices[0],
                    options: m.voices.map((x) => ({ value: x, label: x })),
                    onChange: (v) => setTask({ ...task, voice: v, confirmed: false }),
                  }),
                ),
            ),
          ),
        incompatible &&
          h(Alert, {
            type: "error",
            title: "原参数或素材与新模型不兼容",
            description: "保留原输入供你核对；须明确调整后才能继续。",
            action: btn("明确重置为兼容设置", () =>
              setTask({
                ...task,
                resolution: m.resolution?.[0] || "",
                duration: m.durations?.[0] || 5,
                references: 0,
                firstLast: false,
                voice: m.voices?.[0] || "",
                confirmed: false,
              }),
            ),
          }),
        scenario === "unknown" &&
          h(Alert, {
            type: "warning",
            title: "已有任务结果待核对，不允许再次发送",
            action: btn("核对原任务", () =>
              message.info("模拟核对：仍在等待原任务结果，不创建新任务。"),
            ),
          }),
        scenario === "denied" &&
          h(Alert, {
            type: "error",
            title: "项目资料不允许发往所选服务",
            description: "调整资料范围或在项目许可中处理。这里不自动放宽许可。",
          }),
        scenario === "waiting" && h(Alert, { type: "info", title: "已有任务正在处理中" }),
        scenario === "failed" &&
          h(Alert, {
            type: "error",
            title: "连接失败 · 已确认尚未发送",
            description: "当前要求和参数已保留。修复后重新确认本次范围，不自动发送。",
            action: btn("模拟恢复连接", () => {
              setScenario("normal");
              setTask({ ...task, confirmed: false });
            }),
          }),
        note("已确认约束：" + s.constraints),
        note("示例范围：两个候选，最多 2 次制作操作。当前仅模拟，不外发、不计费。"),
        h(
          Checkbox,
          {
            checked: task.confirmed,
            disabled: blocked,
            onChange: (e) => setTask({ ...task, confirmed: e.target.checked }),
          },
          "已核对模型、参数、素材与本次范围",
        ),
        btn("模拟生成两个候选", generate, {
          type: "primary",
          disabled: blocked || !task.confirmed,
        }),
      );
    }
    function research() {
      return stack(
        !s.files
          ? h(Empty, {
              description: "请先加入项目资料",
              children: btn("去项目资料", () => go("files")),
            })
          : stack(
              h(Tabs, {
                items: ["摘要", "人物", "地点", "事件", "时间线", "文化线索"].map((x, i) => ({
                  key: x,
                  label: x,
                  children:
                    i === 0
                      ? stack(
                          h(Input.TextArea, {
                            "aria-label": "研究摘要",
                            value: researchDraft ?? s.research,
                            rows: 5,
                            onChange: (e) => setResearchDraft(e.target.value),
                          }),
                          row(
                            h(
                              Tag,
                              null,
                              researchDraft === null ? "当前有效 · 版本 " + s.rev : "未保存",
                            ),
                            btn(
                              "保存研究修正",
                              () =>
                                mutate(() => {
                                  patch({
                                    research: researchDraft,
                                    rev: s.rev + 1,
                                    history: [...s.history, s.research],
                                  });
                                  setResearchDraft(null);
                                }),
                              { type: "primary", disabled: researchDraft === null },
                            ),
                            btn("查看来源", () => setSourceOpen(true)),
                          ),
                          s.history.length > 0 &&
                            btn("恢复上一版内容", () =>
                              confirm(
                                "恢复内容",
                                note("将形成新的当前版本，所有修订仍保留。"),
                                () =>
                                  patch({
                                    research: s.history[s.history.length - 1],
                                    history: [...s.history, s.research],
                                    rev: s.rev + 1,
                                  }),
                                "恢复为新版本",
                              ),
                            ),
                          btn("比较重新分析建议", () =>
                            confirm(
                              "当前修正与新建议",
                              stack(
                                note("当前：" + s.research),
                                note("建议补充：古桥也是节庆相聚的公共空间。"),
                                note("只合并你确认的补充，不覆盖当前修正。"),
                              ),
                              () =>
                                patch({
                                  research: s.research + " 古桥也是节庆相聚的公共空间。",
                                  history: [...s.history, s.research],
                                  rev: s.rev + 1,
                                }),
                              "采用这条补充",
                            ),
                          ),
                          btn("发布为文化知识", () =>
                            confirm(
                              "发布知识快照",
                              stack(
                                note(s.research),
                                note(
                                  "同一用户所有工作空间可检索正文，不开放项目原件和未发布研究。",
                                ),
                              ),
                              () => patch({ knowledge: { body: s.research, rev: s.rev } }),
                              "发布以上正文",
                            ),
                          ),
                        )
                      : stack(
                          note(
                            i === 1
                              ? "原文未发现可核实人名，保留“未发现”。"
                              : i === 4
                                ? "建造年份待核实，不补造时间。"
                                : "已有合成资料线索，需结合原文核对。",
                          ),
                          btn("查看来源", () => setSourceOpen(true)),
                        ),
                })),
              }),
            ),
        scenario === "conflict" &&
          h(Alert, { type: "warning", title: "版本冲突演练：本地输入保留，未覆盖服务端。" }),
      );
    }
    function results() {
      return stack(
        chosen
          ? stack(
              chosen.kind === "story"
                ? h("div", { className: "source-quote" }, chosen.summary)
                : h(
                    "div",
                    { className: "media-large", "data-candidate-id": chosen.id },
                    h(Art, {
                      variant: chosen.variant,
                      label:
                        chosen.kind === "video"
                          ? "视频构图示意 · 无真实视频播放"
                          : chosen.kind === "voice"
                            ? "语音结果卡示意 · 无真实音频"
                            : "图片构图示意 · 非生成媒体",
                    }),
                  ),
              row(
                h("h2", null, chosen.title),
                h(
                  Tag,
                  {
                    color:
                      s.adopted.includes(chosen.id) || s.stories[episode] === chosen.id
                        ? "green"
                        : "gold",
                  },
                  s.stories[episode] === chosen.id
                    ? "当前正式故事"
                    : s.adopted.includes(chosen.id)
                      ? "已采用为资产"
                      : "候选 · 未采用",
                ),
              ),
              chosen.kind !== "story" && note(chosen.summary),
              row(
                btn(
                  chosen.kind === "story" ? "采用故事提案" : "采用为正式素材",
                  () => adopt(chosen),
                  {
                    type: "primary",
                    disabled: s.adopted.includes(chosen.id) || s.stories[episode] === chosen.id,
                  },
                ),
                btn(compare ? "结束比较" : "比较候选", () => setCompare(!compare)),
                btn("继续修改", () => {
                  setText("请修改“" + chosen.title + "”：");
                  chatRef.current?.focus();
                }),
                btn("重新生成", () => startPreview(chosen.kind)),
              ),
              chosen.kind === "video" &&
                box(
                  "审片与正式版本",
                  stack(
                    note("审看通过、选为正式视频与保存为公共资产是独立决定。"),
                    row(
                      btn("记录该候选审看通过", () =>
                        mutate(() => patch({ reviewed: { ...s.reviewed, [chosen.id]: true } })),
                      ),
                      btn(
                        "选为正式视频",
                        () =>
                          confirm(
                            "选定正式视频",
                            note("用于当前分集剪辑，不自动保存为公共资产或导出。"),
                            () => patch({ formal: { ...s.formal, [episode]: chosen.id } }),
                            "确认正式视频",
                          ),
                        { disabled: !s.reviewed[chosen.id] },
                      ),
                    ),
                    s.formal[episode] === chosen.id && h(Tag, null, "当前正式视频"),
                  ),
                ),
              h("h2", null, "生成结果（" + visible.length + "）"),
              h(
                "div",
                { className: compare ? "candidate-grid compare" : "candidate-grid" },
                ...visible.map((c) =>
                  h(
                    Card,
                    { key: c.id, className: c.id === chosen.id ? "selected-card" : "" },
                    stack(
                      c.kind === "story"
                        ? note(c.summary)
                        : h(Art, { variant: c.variant, label: c.title }),
                      btn("查看 " + c.title, () => setSelected(c.id), {
                        "aria-pressed": c.id === chosen.id,
                      }),
                    ),
                  ),
                ),
              ),
            )
          : h(Empty, {
              description: "这里还没有创作结果",
              children: btn("向导演描述想法", () => chatRef.current?.focus(), { type: "primary" }),
            }),
      );
    }
    function delivery() {
      const formal = s.candidates.find((x) => x.id === s.formal[episode]);
      return !formal
        ? h(Empty, {
            description: "请先审看并选定正式视频",
            children: btn("查看视频候选", () => go("videos")),
          })
        : stack(
            h(Art, { variant: formal.variant, label: "审片/剪辑示意 · 无实际视频播放" }),
            note("当前正式素材：" + formal.title),
            h(Tag, null, s.reviewed[formal.id] ? "审看通过" : "待审看"),
            field(
              "片尾字幕",
              h(Input, {
                "aria-label": "片尾字幕",
                value: editDraft ?? s.edit[episode] ?? "让记忆继续，让古桥常在。",
                onChange: (e) => setEditDraft(e.target.value),
              }),
            ),
            h(
              "div",
              { className: "timeline" },
              ...["画面", "配音", "字幕"].map((x, i) =>
                h(
                  "div",
                  { className: "track", key: x },
                  h("span", { className: "track-label" }, x),
                  h(
                    "div",
                    { className: "track-clip " + (i === 1 ? "audio" : i === 2 ? "caption" : "") },
                    "已采用来源 · 仅示意",
                  ),
                ),
              ),
            ),
            row(
              btn(
                "保存剪辑",
                () =>
                  mutate(() => {
                    patch({
                      edit: { ...s.edit, [episode]: editDraft ?? "让记忆继续，让古桥常在。" },
                    });
                    setEditDraft(null);
                  }),
                { type: "primary" },
              ),
              btn(
                "导出成片",
                () =>
                  confirm(
                    "导出已保存剪辑",
                    note(
                      "当前" +
                        (pid === "series" ? "第 " + episode + " 集" : "作品") +
                        "；MP4 + SRT。原型只生成模拟回执，不产生文件。",
                    ),
                    () => patch({ exports: { ...s.exports, [episode]: true } }),
                    "模拟导出",
                  ),
                { disabled: editDraft !== null || !s.edit[episode] || !s.reviewed[formal.id] },
              ),
            ),
            s.exports[episode] && h(Alert, { type: "success", title: "模拟导出回执已记录" }),
            pid === "series" &&
              note(
                "第 1 集：" +
                  (s.exports["1"] ? "模拟导出完成" : "未交付") +
                  "；第 2 集：" +
                  (s.exports["2"] ? "模拟导出完成" : "未交付"),
              ),
          );
    }
    function central() {
      if (view === "home")
        return stack(
          results(),
          h(Collapse, {
            items: [
              {
                key: "project",
                label: "项目目标与已确认设定",
                children: stack(
                  note(p.goal + " · " + p.length),
                  note(s.constraints),
                  row(
                    btn("加入项目资料", () => go("files")),
                    btn("设置项目模型", () => openSettings("project")),
                  ),
                ),
              },
            ],
          }),
        );
      if (view === "files")
        return stack(
          h(Tag, null, "项目私有"),
          !s.files
            ? h(Empty, {
                description: "加入资料后逐文件分析",
                children: btn("加入合成资料并分析", () => mutate(() => patch({ files: true })), {
                  type: "primary",
                }),
              })
            : box(
                "《青溪桥记》· 合成 PDF",
                stack(
                  note(
                    scenario === "waiting"
                      ? "分析处理中；其他文件可独立推进"
                      : "解析完成 · 2 页 · 研究结果可查看",
                  ),
                  row(
                    btn("查看原文", () => setSourceOpen(true)),
                    btn("查看文化研究", () => go("research")),
                    btn("解除项目关联", () =>
                      confirm(
                        "解除资料关联",
                        note("保留历史研究并标记来源不可用，不删除原件或公共资产。"),
                        () => patch({ files: false }),
                        "解除关联",
                      ),
                    ),
                  ),
                ),
              ),
          h(Alert, { type: "info", title: "本原型只加入合成数据，不上传本地文件。" }),
        );
      if (view === "research") return research();
      if (view === "knowledge")
        return stack(
          note("独立文化知识 · 同一用户的所有工作空间"),
          ...projects
            .filter((x) => all[x.id].knowledge)
            .map((x) =>
              box(
                x.title,
                stack(note(all[x.id].knowledge.body), h(Tag, null, "发布快照 · 不含私有原件")),
                { key: x.id },
              ),
            ),
          !projects.some((x) => all[x.id].knowledge) && h(Empty, { description: "尚未发布知识" }),
        );
      if (view === "story")
        return stack(
          box(
            "故事方向",
            stack(
              note("从右侧讨论叙事方向，中央比较故事候选。明确采用后才成为当前正式故事。"),
              btn("与导演讨论故事", () => {
                setText("我想从村民记忆讲古桥的故事：");
                chatRef.current?.focus();
              }),
            ),
          ),
          results(),
        );
      if (view === "public") {
        const adopted = projects.flatMap((x) =>
          all[x.id].candidates
            .filter((c) => all[x.id].adopted.includes(c.id))
            .map((c) => ({ ...c, project: x.title })),
        );
        return stack(
          note("同一用户的公共资产 · 固定版本引用 · 不授予私有来源访问"),
          ...adopted.map((c) =>
            box(
              c.title,
              stack(
                h(Art, { variant: c.variant }),
                note("来源项目：" + c.project),
                s.links.includes(c.id) && h(Tag, null, "当前项目已引用此版本"),
                btn(
                  "引用到当前项目",
                  () =>
                    confirm(
                      "引用固定公共版本",
                      note("保留来源限制；不会复制或覆盖原件。"),
                      () => {
                        if (scenario === "denied") {
                          message.error("该资产的使用限制不允许本次引用。");
                          return;
                        }
                        patch({ links: [...new Set([...s.links, c.id])] });
                      },
                      "引用此版本",
                    ),
                  { disabled: s.links.includes(c.id) },
                ),
                btn(
                  "创建项目变体",
                  () =>
                    confirm(
                      "创建当前项目变体",
                      note("以该固定版本为依据调整为暖色环境，仅属于当前项目，不覆盖公共原件。"),
                      () =>
                        patch({
                          variants: [
                            ...s.variants,
                            { base: c.id, name: c.title + " · 暖色项目变体" },
                          ],
                        }),
                      "创建变体",
                    ),
                  { disabled: !s.links.includes(c.id) },
                ),
                ...s.variants
                  .filter((v) => v.base === c.id)
                  .map((v, i) => h(Tag, { key: i }, v.name)),
              ),
              { key: c.id },
            ),
          ),
          !adopted.length && h(Empty, { description: "暂无已采用公共资产" }),
        );
      }
      if (view === "delivery") return delivery();
      return stack(
        ["characters", "scenes"].includes(view) &&
          box(
            "已确认设定",
            stack(note(s.constraints), note("本次生成只新增候选，修改正式设定需独立确认。")),
          ),
        results(),
      );
    }
    const navigation = stack(
      h(
        "div",
        { className: "project-identity" },
        h("div", { className: "project-mini" }, h(Art, { label: "合成项目" })),
        stack(h("strong", null, p.title), note("创作中 · 示例项目")),
      ),
      field(
        "切换项目",
        h(Select, {
          "aria-label": "当前项目",
          value: pid,
          onChange: (v) =>
            navigate(() => {
              setPid(v);
              setEp("1");
              setView("home");
              setSelected(null);
              setText("");
              setRequest(null);
            }),
          options: projects.map((x) => ({ value: x.id, label: x.title })),
          style: { width: "100%" },
        }),
      ),
      ...[
        ["home", "项目"],
        ["files", "资料"],
        ["research", "研究"],
        ["story", "内容"],
        ["images", "素材"],
        ["delivery", "交付"],
      ].map(([key, label]) =>
        btn(label, () => go(key), {
          key,
          type: view === key ? "primary" : "text",
          block: true,
          "aria-current": view === key ? "page" : undefined,
          "aria-label": nav.find((x) => x[0] === key)?.[1],
        }),
      ),
      h(
        "div",
        { className: "nav-footer" },
        h("h3", null, "项目素材"),
        ...nav
          .filter(([key]) =>
            ["story", "characters", "scenes", "images", "videos", "public"].includes(key),
          )
          .map(([key, label]) =>
            btn(label, () => go(key), {
              key,
              block: true,
              type: "text",
              "aria-label":
                key === "story" ? "故事素材分类" : key === "images" ? "图片素材分类" : label,
            }),
          ),
      ),
      h(
        "div",
        { className: "nav-footer" },
        btn("项目模型", () => openSettings("project"), { block: true }),
        btn("文化知识库", () => go("knowledge"), { block: true }),
        btn("平台模型管理", () => openSettings("platform"), { block: true }),
      ),
    );
    const chat = stack(
      h(
        "div",
        { className: "section-label" },
        h("h2", null, "✦ AI 创意助手"),
        h(Tag, null, "Director"),
      ),
      note("随时告诉我你的想法，我来帮你修改和优化。"),
      h(
        "div",
        { className: "conversation", "aria-label": "Director 对话记录" },
        h(
          "div",
          { className: "chat-line" },
          "告诉我想做怎样的作品。我会结合资料与已确认设定组织创作，重要结果由你决定是否采用。",
        ),
        ...s.messages
          .filter((m) => m.episode === episode)
          .map((m) =>
            h(
              "div",
              { key: m.id, className: "chat-line " + (m.role === "user" ? "user" : "") },
              stack(
                note(m.body),
                ...(m.results || []).map((id) => {
                  const c = s.candidates.find((x) => x.id === id);
                  return (
                    c &&
                    box(
                      c.title,
                      stack(
                        c.kind === "story"
                          ? note(c.summary)
                          : h(Art, { variant: c.variant, label: "与中央相同候选" }),
                        btn("在中央查看 " + c.title, () => {
                          setSelected(id);
                          setView(
                            c.kind === "voice"
                              ? "audio"
                              : c.kind === "story"
                                ? "story"
                                : c.kind === "video"
                                  ? "videos"
                                  : "images",
                          );
                          setChatOpen(false);
                        }),
                      ),
                      { key: id },
                    )
                  );
                }),
              ),
            ),
          ),
      ),
      request &&
        box(
          "这次创作要求",
          stack(
            h(Input.TextArea, {
              "aria-label": "创作要求",
              value: request.summary,
              rows: 3,
              onChange: (e) => setRequest({ ...request, summary: e.target.value }),
            }),
            h(Select, {
              "aria-label": "创作内容类型",
              value: request.kind,
              onChange: (v) => setRequest({ ...request, kind: v }),
              options: [
                { value: "story", label: "故事" },
                { value: "image", label: "图片" },
                { value: "video", label: "视频" },
                { value: "voice", label: "配音" },
              ],
            }),
            note("约束：" + s.constraints),
            h(Collapse, {
              items: [
                {
                  key: "prompt",
                  label: "高级 Prompt（可选）",
                  children: h(Input.TextArea, {
                    "aria-label": "高级 Prompt",
                    value: request.advanced,
                    onChange: (e) => setRequest({ ...request, advanced: e.target.value }),
                  }),
                },
              ],
            }),
            btn("查看本次制作设置", () => startPreview(), { type: "primary" }),
          ),
        ),
      h(
        "div",
        { className: "chat-composer" },
        row(
          ...["我想修改…", "帮我调整…", "继续优化…"].map((label) =>
            btn(
              label,
              () => {
                setText(label.replace("…", "："));
                chatRef.current?.focus();
              },
              { key: label, size: "small" },
            ),
          ),
        ),
        h(Input.TextArea, {
          ref: chatRef,
          "aria-label": "给 Director 的想法",
          placeholder: "请输入你的需求，例如：我想修改画面风格…",
          rows: 3,
          value: text,
          onChange: (e) => setText(e.target.value),
        }),
        row(
          btn("发送想法", propose, { type: "primary", disabled: !text.trim() }),
          btn(s.paused ? "继续后续创作" : "暂停后续创作", () => patch({ paused: !s.paused }), {
            type: "text",
          }),
        ),
      ),
    );
    return h(
      "div",
      { className: "prototype" },
      h(
        "div",
        { className: "design-bar" },
        row(h("b", null, "D6 三栏交互原型"), h("span", null, "合成数据 · 无模型调用 · 刷新重置")),
        h(Select, {
          "aria-label": "原型场景",
          value: scenario,
          onChange: setScenario,
          options: [
            ["normal", "正常"],
            ["offline", "断网"],
            ["conflict", "版本冲突"],
            ["waiting", "处理中"],
            ["failed", "发送前失败"],
            ["unknown", "提交结果待核对"],
            ["denied", "外发受阻"],
          ].map(([value, label]) => ({ value, label })),
        }),
      ),
      h(
        "header",
        { className: "studio-header" },
        row(
          h(
            "div",
            { className: "brand" },
            h("span", { className: "brand-mark" }, "DF"),
            "DramaForge",
          ),
          h(Tag, null, p.type),
        ),
        row(
          btn("项目与素材", () => setLeftOpen(true), { className: "nav-toggle" }),
          pid === "series" &&
            h(Select, {
              "aria-label": "当前分集",
              value: ep,
              onChange: (v) =>
                navigate(() => {
                  setEp(v);
                  setSelected(null);
                  setRequest(null);
                }),
              options: [
                { value: "1", label: "第 1 集 · 相遇" },
                { value: "2", label: "第 2 集 · 守护" },
              ],
            }),
          btn("展开 Director", () => setChatOpen(true), { className: "chat-toggle" }),
        ),
      ),
      h(
        "div",
        { className: "triptych" },
        h("nav", { className: "project-rail", "aria-label": "项目与资产导航" }, navigation),
        h(
          "main",
          { className: "work-stage" },
          h(
            "div",
            { className: "page-head" },
            stack(
              h("span", { className: "eyebrow" }, p.title),
              h(
                "h1",
                null,
                nav.find((x) => x[0] === view)?.[1] ||
                  (view === "audio" ? "配音结果" : "文化知识库"),
              ),
            ),
            h(Tag, null, pid === "series" ? "第 " + episode + " 集" : "当前作品"),
          ),
          s.paused && h(Alert, { type: "warning", title: "后续创作已暂停，已有任务仍需核对结果" }),
          central(),
        ),
        h("aside", { className: "director-rail", "aria-label": "持续 Director 对话" }, chat),
      ),
      h(
        Modal,
        {
          title: "模型配置",
          open: !!settings,
          onCancel: () => setSettings(null),
          footer: null,
          width: 880,
          destroyOnHidden: true,
        },
        settings && settingsBody(),
      ),
      h(
        Modal,
        {
          title: "本次生成 · 模型与实际能力",
          open: !!task,
          onCancel: () => setTask(null),
          footer: null,
          width: 760,
          destroyOnHidden: true,
        },
        taskBody(),
      ),
      h(
        Modal,
        {
          title: "原文与引用",
          open: sourceOpen,
          onCancel: () => setSourceOpen(false),
          footer: null,
        },
        stack(
          h(Tag, null, "项目私有 · 合成资料"),
          s.files &&
            h(
              "div",
              { className: "source-quote" },
              "青溪古桥连接村落与集市。村民共同维护桥面，节庆时在桥边相聚。",
            ),
          note(
            s.files
              ? "《青溪桥记》· 第 1 页 · 段落 2"
              : "来源已解除关联，历史引用保留，原件当前不可用。",
          ),
        ),
      ),
      h(
        Drawer,
        { title: "项目与素材", open: leftOpen, onClose: () => setLeftOpen(false) },
        leftOpen && navigation,
      ),
      h(
        Drawer,
        { title: "AI Director", open: chatOpen, onClose: () => setChatOpen(false), width: 420 },
        chatOpen && chat,
      ),
    );
  }
  ReactDOM.createRoot(document.getElementById("root")).render(
    h(
      ConfigProvider,
      { theme, locale: antd.locales.zh_CN, button: { autoInsertSpace: false } },
      h(AntApp, null, h(Studio)),
    ),
  );
})();
