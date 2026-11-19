# 机构版执行状态

更新：2026-11-19。此文件是本长期任务唯一执行状态，产品/架构规则仍由 [CURRENT](../CURRENT.md) 导航；本目录是合同12明确要求的执行管理材料，不是第二套架构宪法。


## 当前阶段与批次

- **当前任务**：I9 编辑与交付（已开工，进行中）。I8b 生产段已到“关键帧/视频→正式媒体”并有跨集共享与Provider提交证据（EV137–EV149），合成与分集交付归 I9；I9-01a 时间线 schema2 来源校验（EV153）、I9-01b 分集作用域（EV154）已落地。
- **下一步**：① I9 剩余——`selection_snapshot` 服务端观测、asset/public 素材资质接线、切换集版本化 Save、渲染快照与导出绑定（I9-02）；② I8b 合成段与多镜头编排；③ 获授权后的批量 create；④ 在空闲/足算力机器上复跑 Full（Owner 已确认保持 200ms 门槛不变）。
- **本轮新增（EV137–EV146）**：生产就绪只读模型与跨集共享计数（EV137–EV139）、共享资产计划解析与派发冻结（EV140–EV141）、后端单元全量 2704 passed（EV142）、共享资产到达两集 Provider 提交（EV143）、三类作品关键帧到正式媒体 + 就绪共享统计缺陷修复（EV144）、项目级生产批只读预览（EV145）与 HTTP 入口/生成类型（EV146）。
- **阻塞与验收**：本地接线无待批审批项。I4 研究/知识、I5 公共引用、I8a 资产媒体、I6b 领域流程、I8b 关键帧生产段已有机制证据；**Full Gate 仍未通过**——仅 `frontend-quality` 的 `workbench-resource` p95（30/100 镜头 ~325–396ms > 200ms）失败，归因宿主争用，需空闲主机重跑；未取得完整 Full 前不宣布阶段 Full。真实作品、目标机与 I10 最终候选仍待验收。
- **交接方式**：当前任务、下一步、阻塞或最近证据变化时覆盖本节，详细历史按 EV 编号查阅。D8 冻结基线为 D8-20261117-r1。

主合同：[桌面12](<C:/Users/RXZY/Desktop/新建 文本文档 (12).txt>)；次合同：[桌面11](<C:/Users/RXZY/Desktop/新建 文本文档 (11).txt>)。Owner明确12优先11。N11已澄清全部改动后续统一执行，先完整设计再工程；不重复请求普通阶段授权。真实费用、扩大真实资料外发、不可逆迁移、正式发布等仍停在硬门槛。


## D0续接审查

七份[D0交付](<D:/DramaForge_机构版设计基线_D0/README.md>)均已重新读取；不重做或改写该历史快照。原报告真实结论为“严格冻结未通过”，不能因11写“已完成”伪造历史通过。按11允许登记非阻断验证项继续设计的规定：
- R01–R38、O1–O7及资料/资产细则完整继承。
- C05/C06/C07经本次Owner答复关闭产品边界，实施/验证仍待完成。
- C11由12的D/I定义关闭编号缺口，具体实施依赖仍在D8冻结。
- C10实际数据库/角色/活动任务未知，不阻断无运行写入的设计；阻断基于未知实例的迁移、恢复及运行验收。I0须只读核验，隔离测试库证据不能冒充现有实例。
- C12细化为产品验收用例与资源能力证据，不把D1设计所选样例参数冒称Owner设备SLA。
- C13在D2/D3/D7审阅候选，D8冻结后依据12实施；不再以旧包“待批准实施”要求普通逐阶段审批。

这属于续接准入判定，不将原D0严格运行基线判定改为通过。后续风险和关闭责任统一见 [RISK_REGISTER](RISK_REGISTER.md)。


## 尚待交付的跨阶段事项

| 承接批次 | 交付与验收动作 |
|---|---|
| I6b-01 | 补齐 Flow 读投影、执行/研究预览的外发摘要及 SourceUse 跨项目 owner 授权计数与资格。用受控流程读取实例，核对预览与实际许可，覆盖无资格时的拒绝。 |
| I7-01 | 接回 I4 的 Director 研究解释/补充、恢复候选对照和知识发布共享范围预览。从研究入口读到解释、比较候选并在发布前确认可见范围。 |
| I7-01 | 接回 I5 公共资产库独立浏览页面。从工作台浏览已发布资产，预览并按项目资格采用；用无资格样例核对访问限制。 |
| I10-02 | 核对三类作品端到端、目标机与最终干净候选的完整验收。真实费用、外发和正式发布继续适用主合同 §8。 |

D0–D8 设计结论、各阶段已运行的证据和当时尚待处理的事项按下文留存。当前续跑位置见首页。


## D1阶段报告

依据：主合同12产品十九项、D0 R01–R38、O1–O7、Owner N02–N04，已读真实项目/资料模型与现有产品主链。
交付：PRODUCT机构完整合同、CREATION_FLOW研究/知识/创作正常及异常流程；复用既有权威，无第二PRD。
自检：38项需求按业务对象、旅程、三作品与分组验收逐项覆盖；项目资料与公共资产规则保留；知识独立使用并显式发布；普通问答不等于MasterRun；计划/内容/生产/正式/导出决定不互相授权。
交叉检查：修正旧PRODUCT每请求Run、Workflow命名、全局默认本地及资料先于安全的顺序；已有真人样片仅技术基线；三类型都进入整体验收。研究编辑与typed Apply区别、单集/整剧完成、剪辑与生产事实归属一致。
Schema/API/Event/状态影响：研究/知识/公共引用与作品类型需D2新增/扩展；目标/流程第三轮候选继续复核；D7冻结精确接口，不把语义状态当现有enum。安全影响：显式发布内容快照、不开放私有来源、O4/O5新旧路径区分。依赖：D2–D7细化，D8完整冻结。
验收：9份本批文档链接无缺失，diff --check退出0；1358 tracked路径比较仅PRODUCT/CREATION_FLOW/CURRENT改变，原17项dirty内容/删除状态不变。未跑产品测试、未连接DB、未改业务/Schema/Compose。
剩余：C10运行身份、C12资源与真实作品质量待工程验收；不阻断纯设计。D1结论是产品设计检查通过，非整体设计冻结或产品运行通过，按合同自动进入D2。


## 当前证据与Review

D2-01实质进展：已在DATA_MODEL新增目标Schema，覆盖作品类型/目标、SourceExtraction/Fragment、
ResearchResult/Revision/Citation、独立Knowledge及项目固定引用；补当前候选公共发布/项目链接/变体/令牌扩展。
DOMAIN_VOCABULARY同步新事实语义，均标未实施。已读第三轮P1/P4完整字段及状态、P3准入、实际
Project/Asset/Turn/Invocation/Artifact/令牌与引用消费者，未以文件名代替内容。
自检修正：研究采纳必须新增不可变accept修订以保存重放回执；恢复不倒拨版本；current指针禁止指未应用候选；
知识发布/撤回保留操作revision；公共引用保留原Artifact所有权，不直接放开源项目RLS。
D2-02追加进展：已回填MasterRun/Plan/控制回执、Flow三表、Turn关联及外发三表的目标字段、状态集合、
候选键/复合FK、权限和幂等顺序，保留单命令单NodeRun及O6旧lease顺序。
D2-02时尚未通过的事项：全作品完成predicate、来源限制血缘、公共引用全部组合键、完整ER/既有表扩展/权限索引、
迁移和负向用例仍需闭合；不可据当前Schema草案开始迁移。
RSK21已由Owner N05“同一用户的所有 Workspace 共享”关闭产品决定；D1/D2已回填同owner共享，
保留私有项目RLS，未扩大到其他用户。知识/发布/消费链接/公共令牌/变体的组合键按源与消费空间分别绑定。

D2-03新增证据与修订：读取实际EditSession、Export、FinalFilm dirty实现及Artifact血缘，确认当前无会话分集作用域，
补episode绑定和不可变成片回执索引，不覆盖原未提交代码。新增来源使用限制及ArtifactSourceUse，保留生产所有权。
交叉检查发现“六类结果至少各一条”会迫使无资料事实被编造，改用ResearchAnalysis覆盖清单与none/incomplete区别；
新增分析输出/Invocation关联，不新增分析Runtime。补类型化来源定位、六类body及逐claim引用，公开知识不得序列化私有Result ID。
已补27新表清单、3幅ER、现有表扩展、角色/不可变权限、迁移依赖/回退和DB01–12数据用例设计。
上述是设计，未执行迁移/PG/产品门。D2-04已继续闭合公共令牌六列同空规则/精确FK、变体父源链接、
跨项目来源basis的typed/约束触发器、在途完成与新发送不同检查时间、重复分析排他与空指针可见性。


## D2阶段报告与D3开始

D2退出结论：数据设计审查通过。依据真实模型/迁移与第三轮修订，27张新表均有字段定义，现有扩展/候选键/
FK/RLS/不可变/索引/删除/迁移方向齐备；3幅ER、JSON核心形状、DB01–12用例设计已回填DATA_MODEL。
逐链审查来源/研究/知识/公共引用/目标/流程/外发/逐集交付，修正NULL逃逸、current旧版本恢复、零发现和跨空间范围问题。
设计依据与安全/依赖/Schema/API/Event影响见DATA_MODEL各节及D1；阶段审查不是PG测试PASS或D8最终冻结。
运行实例Schema/角色仍未知，后续每个实现门必须实测；D3–D7细化如发现数据不足须回填并复查。

D3-01已实际读取control.guard、executor、agent_harness/agent_service、domain_tools、ProductionCommands与Worker装配。
发现现有Graph guard持行锁跨步骤，生产工具另开session；当前ProductionCommands却是caller-owned commit。
已将两Runtime事实归属、O6接口切换、短事务/锁外网络与受限原子受理候选回填DIRECTOR_RUNTIME。
D3-02/03已补完整状态边、统一锁序、原子受理、epoch checkpoint隔离/应用指针、故障矩阵、三个执行槽与累计限额、
受限Worker适配器、固定研究操作计划及六类BusinessFlow定义、O2命名消费者和RT01–12。
源码复核纠正旧Agent已有execution ID（以冻结state版本路由而非有无ID）、Production授权先锁grant再锁Shot、
reconcile目前跳过Agent且只覆盖单NodeRun等待。新增Control checkpoint_ref/SignalClaim结果及槽索引已回填DATA_MODEL，
并检查未新增租约表/第三Runtime/生产事实副本。D3退出：设计审查通过，未实施/未跑产品测试。
ARCHITECTURE_MAPPING保留原未提交改动，仅审阅修正持久Flow名称、已接入HTTP/dispatcher两行；其余原文逐行一致。

D4-01已读source_parser、pyproject及Dockerfile：当前仅TXT/CSV/TSV/受限DOCX，原locator为1-based；
D2新定位0-based必须显式版本化转换，不能默默改变旧坐标。现有Pillow/OpenCV/FFmpeg可复用，PDF/OCR/ASR能力仍缺。
D4-02/03完成：全格式解析链/资源上限/中间块恢复、六类研究/零发现/用户修正、同owner知识发布检索撤回、上下文预算/失效，
已回填ARCHITECTURE。选容器内Poppler/Tesseract/whisper.cpp与openpyxl+defusedxml；官方来源与版本/哈希证据在正文，未安装。
核对实际EventLog/Outbox/RLS迁移/SSE，发现新owner事件不能复用旧NULL project通配；DATA_MODEL新增显式事件scope及分发限制，
同步处理证据、坐标转换、生成搜索列/pg_trgm合同（没有新表/外部搜索服务）。D4退出为设计审查通过；SRC01–13全部待实现运行。
下一步D5闭合公共采纳/变体/限制、Vision文本消息、模型能力、TTS/引用/存储等实际出口与撤销竞态；不得把网络SSRF视作内容许可。

D5-01已读原附件05、AssetVersion.promote/from-artifact、Shot Formal及真实AgentMessage/Gateway profile、
voice_runtime/voice_path、egress：资产采用与Shot Formal/Export不是同一事实，两个Asset采用入口均需原子入公共库；
现有AgentMessage只支持文本，Gateway仅chat_text_v1/chat_tools_v1；Edge TTS联网但已有原Operation事实链。
初步合同回填MODEL_PROVIDER，D5尚未通过；继续精确Vision/模型能力、全部出口/撤销及公共权限场景。

Owner新增N06：清理旧Edge TTS配置，默认采用项目指定语音模型，未配置则提示设置（已明确答复）。
已据此取消“为Edge建设新guard”的待实施设计，回填PRODUCT/MODEL_PROVIDER/DATA_MODEL；业务代码/依赖/实际.env尚未删除。
只读盘点命中config.py、voice_config/runtime、edge_tts.py、voice_path、Voice DTO、pyproject/uv.lock、
docker-compose/.env.example及声音/镜头/成片测试；实际.env含四个TTS键，仅记录键名未输出值。
实施时完成所有消费者替换后清理活动Edge；保留原Operation/Artifact只读，不重发旧任务，不修改其它凭据。

D5退出：设计审查通过。已读真实LiteLLM传输/Manifest/媒体提交/语音/引用/对象存储/错误路径；
完整合同与SEC01–14回填MODEL_PROVIDER，route/adoption/media/voice字段回填DATA_MODEL，长语音分段回填PRODUCTION_GRAPH。
因当前唯一Operation约束，不使用未实现的同Node多Operation假设。Provider Binding语音沿原voice_execution，不恢复旧音频槽。
尚未执行任何Edge删除、依赖更新、Schema或Compose修改；N06为已确认/待实施，而非完成清理。

D6使用仓库frontend-skeleton技能；已读取视觉规范、UiProvider、Token、导航、package及前端状态权威。
本机已有React18/ReactDOM/dayjs/AntD6的UMD文件可复用，计划制作仅设计用HTML/JS原型，
不改frontend/src业务代码，不启动宿主API/Vite，不安装依赖，不把原型数据当产品验收。
已创建的institution.html/css只有静态外壳，缺交互脚本，未渲染/验收。Owner N07指出前端显示和模型配置均须重构；
停止沿用该布局，现有外壳不作为设计候选。复用React/AntD/Token不意味着保留专业工作台页面形式。
重新读取总方案§2/§4、实际模型设置/项目模型来源组件，确认原需求要求机构用户表达意图、Director组织工作。
现有FRONTEND_WORKBENCH的供应商面板、默认Profile及“配音不受这里控制”是旧现状，不能作为N06/N07目标。
下一步结合Owner补充重做信息架构和模型配置流程，交叉回填PRODUCT/MODEL_PROVIDER/DATA_MODEL/API；
随后再制作可操作原型并验证。已发出一次聚焦的体验澄清；不预设用户已批准具体视觉方案或新模型配置层级。

[TEST_EVIDENCE](TEST_EVIDENCE.md)记录静态检查和后续真实命令结果。当前没有本任务产品测试PASS、代码Review通过或Full Gate通过的证据。D1检查只证明产品合同覆盖，不证明实现。

D6-03：Owner N08已给出完整三栏/三级模型/自然语言创作要求，N09限定本次设计原型。已回填PRODUCT、
FRONTEND_WORKBENCH、MODEL_PROVIDER及design/README，旧无常驻聊天规则由N08明确替代。
重写原型为institution-studio.js，删除本任务刚创建的两栏institution.js，未删除历史权威。
现有八项入口均有设计与原型表面；平台/项目/单次模型、聊天同ID候选、比较/采用、研究修正/发布、
审片/正式视频/Save/模拟Export已交互。局部实际验证见EV24–28，未把模拟结果当生成或成片。
原型临时静态服务仅监听127.0.0.1:4179，白名单只含设计文件及已有UI依赖，不启动业务API。
Codex预览已请求打开（工具返回queued）；可访问/design/prototypes/institution.html。
后续已补：故事候选和聊天同步/明确采用；连续剧跨项目与分集候选/对话隔离；公共引用/项目变体的内存交互。
Owner N10随后提供参考图并明确首版大体交互先按图、细节以后迭代，已改左项目卡+六主导航/素材分类，
中央大预览+三候选，右侧持续对话/结果卡/快捷修改/输入区。图中的技术事实没有被冒充为产品现状；默认载入三份合成示例。
首版实际验证见EV29–31；界面显示“合成数据/无模型调用/刷新重置”。原型已在Codex预览打开，可刷新查看最新版本。
未完成：三作品完整端到端原型验收、全部失败场景/窄屏操作/公共引用变体回归、三级配置后端目标解析/字段/API一致性。
D6整体尚未通过，首版交互可供后续细节迭代；不把本地模拟当真实模型、RLS、媒体或成片证据。
当时继续仅设计；N11现已澄清全部改动后续统一执行，保留N10首版交互，D8完成后按主合同进入I阶段。
阶段退出条件见 [PHASE_GATES](PHASE_GATES.md)，计划见 [MASTER_EXECUTION_PLAN](MASTER_EXECUTION_PLAN.md)。


## D6首版设计审查与D7准入

依据：Owner N08明确三栏/三级模型/自然语言创作，N10给出首版参考图并允许后续细节迭代，N09限定设计原型。
交付：八项页面流程回填FRONTEND_WORKBENCH，PRODUCT/视觉规范/模型合同一致；独立原型使用现有React/AntD/Token，
左项目卡与分类、中央作品与候选、右持续聊天，同ID同步与各正式门可操作。旧两栏脚本是本任务临时产物，已替换。
自检与交叉检查：发现并修复原型中资产采用/正式视频混用、共享知识非固定快照、语音消息未定位中央等问题；
真实Profile/两resolver缺项/首次复制语义核对后，E04统一项目三媒体默认，替代尚未实施的voice_defaults/Shot模型覆盖草案。
Schema/API/Event影响：扩展原Profile三Binding/语音选项/迁移核对版本；复用model-profile读写与原执行预览，
新增零生成推荐读模型及配置变更事件，详见三领域权威。安全：配置零生成、Workspace凭据不共享、无隐式fallback，
历史/未知任务身份不改；原型只有合成内容。依赖：D7完成全接口/事件/迁移/行为测试合同，D8整体一致性冻结。
实际证据EV24–34：三作品共四个交付单元完成代表性原型旅程；空/等待/错误/冲突/断网/未知提交、研究修正/发布、
公共引用/变体、候选同步与比较、三级配置、首尾帧能力切换、审片/正式/保存/导出及布局/键盘均有相应DOM断言。
检查不是实际文件上传/解析、模型生成、音视频播放或导出验收，也不是产品Full Gate；所有运行能力仍未实施。
剩余：视觉细节按N10后续迭代；实际200%缩放、真实媒体和全产品UI-01–13留到工程验收，不能被本原型代替。
配置迁移待核对和精确部署/运行Schema问题登记RSK24/C10，由D7/D8设计、未来实施实测关闭。
D6结论：按Owner指定首版范围，设计与原型审查通过，进入D7设计；不宣称最终产品或D8通过，不进入代码实施。


## D7阶段审查

交付：API各领域目标请求/返回/权限/版本/幂等/错误/事件；DATA_MODEL新增回执/配置/范围字段、M01–08依赖与历史保护；
DEPLOYMENT的既有部署形态、维护/恢复准入及E06多库/对象备份；DEVELOPMENT真实现有命令与隔离真实API旅程接线；
TEST_EVIDENCE逐R01–R38的16组测试落点；MASTER_EXECUTION_PLAN的25个批次、模块归属、前置及退出证据。
依据均包括实际文件，不以历史方案名字代替内容。新路由、表列、测试文件和CLI选项均标目标/未实施。
自检/交叉修正：E05采用回执覆盖私有版本而不强迫公共化；FinalFilm prepare新语音必须显式预览/授权；
控制/研究回执不虚构键列；scope事件不过度广播；备份不把目标URL字符串差异/部分snapshot当完整恢复；
研究先依赖I6a流程核心，媒体配置在I8a先行，I8b只验证生产段、完整交付依I9，保护真实实例的备份工具先于其实例迁移。
补多模态消息SourceMediaInput与required_purposes交集，避免文字许可单独放行Vision附件。
Schema/API/Event影响已回填各权威，权限/副作用风险由T组与API/DB/RT/SEC/SRC/MC用例覆盖，非已运行证据。
实际检查EV39：38项、16组、14阶段/25批次无环、14文件链接缺失0、diff --check通过。
未决运行验证：C10实例Schema/活动任务、所有新代码/真实PG/Provider/目标机容量恢复仍缺；
这些阻断后续对应实施/验收，不以设计文档关闭。真实费用/外发/发布硬门保持；N11已澄清设计后统一工程。
结论：D7设计交付与一致性审查通过，进入D8全量审计；D8尚未冻结，产品与工程实施没有通过声明。


## D8审计修订进展（尚未冻结）

第一轮已逐实际文件修正：N09后续授权的过强解释由Owner N11澄清；旧专业布局/ADR术语与三栏目标分清；
NodeRun→Operation当前0..1及本地FFmpeg同链事实回填；默认Compose与可选dev暴露端口区别明确；
旧Workflow两条wire路径/DTO/前端消费者正式改名合同补齐，不动旧冻结hash。
新增现有权威内R01–R38全量追踪与REUSE/EXTEND/NEW/REFACTOR/REMOVE/VERIFY处置，未另建架构宪法。
第二轮发现并补齐真实缺口：Asset独立三媒体生成不能借假Shot，原grant/Graph需asset目标；
公共/已采用素材直接剪辑需要Clip.source schema2及服务端选用快照，不复制源Artifact或改生产真相；
计划去重与CAS需真实decision_basis；已解析文件重新识别与多块本地处理需明确原回执/固定零模型source_extract_v1。
补了7种注册流程/7类完成predicate、语音参数绑定身份、来源生命周期、维护mode与恢复会话换钥。
这些是同一既有架构内的目标扩展，未修改业务代码、Model、Migration、Compose或真实配置。
保护核验EV42：1358跟踪路径相对起点仅设计文档改变，非设计变化0；原工作区代码仍保持。
参考图已原样入frontend/design/prototypes，原型仅格式化；source/model元数据只读，未装工具/权重或调用模型。
当前检查：38项追踪、38项测试映射、16测试组、14阶段/26批次无环、28文档文件链接存在。
剩余：完成主合同19项最终交付的逐项审计/当前冲突分类和设计冻结指纹；完成后按N11统一进入I0。


## D7分批过程记录

D7-01实质进展：已读取真实项目文件HTTP/服务、Agent请求/响应/Thread路由与Proposal部分Apply、
EventService/EventLog/SseHub/Redis桥，并与D2/D3/D4状态及回执字段交叉核对。
API新增明确目标合同：项目作品参数、解析/研究状态读投影、五类来源定位、六类研究修正/采纳/恢复、
固定知识快照/同owner引用、SSE scope/重放；持续对话202受理、create_goal、MasterRun控制/Plan Apply、Flow/Attempt只读。
修正：分析提交携带完整预览输入以重算指纹；研究固定计划沿原typed Apply不借媒体grant；
研究新建version按内部1→2、SSE用持久event_id、知识私有source_links不公开；通用控制回执不虚构request_key列。
测试设计补API-R01–05/K01–03/E01/P01/D01–06，均未执行。D7尚未通过：公共资产/外发安全API、
全事件目录/迁移与恢复/部署运维/真实测试命令和可执行批次仍待完成；本次仍不修改业务代码。

D7-02完成本切片设计：已读实际Asset版本采用/from-artifact/Provider引用下载/egress，
补公共浏览、固定项目链接/变体、来源用途声明、项目外发策略、目的地修订、参考绑定与Provider token目标API。
E05将采用回执归AssetVersion，避免为私有/手工版本制造公共发布；候选创建与采用分别保存不可变受理版本。
补目的地configuration_hash/expected revision/location_evidence及原始SourceUse expected0行为，仍未改Schema。
交叉检查修正：公共库预览需owner_preview窄模式；链接旧创建回放不得覆盖后来label/detach；
新key重复采用旧版本不得拨回current；无workspace event scope不新增平台广播；策略/用途/操作授权保持独立。
新增API-A01–04/S01–04测试合同，只有静态差异/链接检查实际通过。公共API设计已完成本轮覆盖，
D7仍需分集剪辑/导出扩展、迁移备份回退、部署、完整测试文件/容器命令与实施批次，不能标阶段通过。

D7-03已补分集会话/范围确认/创建回执、只读尾部准备预览、原Production逐命令受理、保存版本导出及交付读模型。
实际dirty FinalFilm prepare会排队尾部节点，不是纯读取；新语音能力必须独立预览授权，导出不得隐含付费生成。
DATA_MODEL补M01–08迁移依赖/历史保护/隔离回退及native-text-v1真实TXT/CSV/TSV/DOCX定位转换规则；未创建迁移文件。
DEPLOYMENT补现有Windows/WSL2/容器方式、Parser/网络隔离、维护/恢复准入目标、多库与对象/密钥恢复及目标机验收。
备份脚本当前只核对URL字符串与桶名、容器分支只用目标database名，且全归档装内存；未运行restore，风险登记RSK26。
真实命令来源已读quality脚本、Dockerfiles/Compose/package/CI，但尚未运行任何产品门。
剩余：收敛备份容量方案、完整需求→具体测试文件/命令矩阵、故障/重启/恢复用例、可执行实施批次与全设计一致性；D7未通过。


## D8最终设计审计（2026-11-17）

审计范围为主合同12§5十九项交付、R01–R38、O1–O7及N02–N11，继承D0真实结论，不重做/篡改历史D0。
本轮自检与交叉检查由当前Agent执行，不冒称独立第三方Review。逐域读取实际源码/文件，修订后反查数据/API/用户门/批次与测试。

| # | 主合同交付 | 实际设计落点与核查内容 | 结论 |
|---|---|---|---|
| 1 | 完整PRD | [PRODUCT](../PRODUCT.md)：机构定位、全部范围、三作品、O/N边界及验收 | 设计齐全；未实现 |
| 2 | 用户旅程/流程 | [CREATION_FLOW](../CREATION_FLOW.md)：资料→研究→创作→确认→生产→交付，等待/故障/修改分支 | 设计齐全；未运行 |
| 3 | 领域模型/ER | [词表](../DOMAIN_VOCABULARY.md)、[DATA_MODEL](../DATA_MODEL.md)：不同事实与4幅ER，scope/Owner归属 | 无新增同义Runtime/真相表 |
| 4 | 全量Schema | DATA_MODEL：27新表及既有表扩展、列/约束/索引/RLS/版本/删除和迁移合同 | 目标已定义；ORM/实际DB未改 |
| 5 | Director/Harness/LangGraph | [DIRECTOR_RUNTIME](../DIRECTOR_RUNTIME.md)、[模块边界](../MODULE_BOUNDARIES.md)：唯一引擎、受控端口、短事务/epoch/checkpoint | 设计齐全；无回归PASS声明 |
| 6 | MasterRun/Flow/Production | DIRECTOR_RUNTIME、[PRODUCTION_RUNTIME](../PRODUCTION_RUNTIME.md)、[PRODUCTION_GRAPH](../PRODUCTION_GRAPH.md)：7定义/7谓词、原命令/回执与单操作关系 | 归属/恢复一致；待实施 |
| 7 | 资料与文化研究 | [ARCHITECTURE](../ARCHITECTURE.md)、DATA_MODEL/API：7格式、坐标/来源、六类结果、修正/再分析/知识与上下文 | 设计齐全；真实处理器待验证 |
| 8 | 公共/私有资产 | DATA_MODEL、MODEL_PROVIDER、API：同owner跨Workspace、固定引用/变体/撤销、无私有源访问扩张 | 设计齐全；RLS/出网未实测 |
| 9 | 模型与Provider | [MODEL_PROVIDER](../MODEL_PROVIDER.md)：三级配置、真实能力、VoiceSpec、Edge退出、资产三媒体同链 | 设计齐全；尚未清理Edge/接入新TTS |
| 10 | 权限/外发 | MODEL_PROVIDER、API、DATA_MODEL：O4分路径、SourceUse、目的地/复合用途、准入/撤销、密钥隔离 | 无设计豁免；实际安全验证未完成 |
| 11 | 信息架构/原型 | [FRONTEND_WORKBENCH](../FRONTEND_WORKBENCH.md)、[原型](../../frontend/design/prototypes/institution.html)、Owner参考图 | N08/N10首版交互已检查；合成媒体不证明播放/生成/导出 |
| 12 | API/Event | [API](../API.md)：目标请求/返回/权限/版本/幂等/错误、SSE及O2改名 | 新路由/DTO均未实施，不冒称OpenAPI已生成 |
| 13 | 状态/生命周期 | DIRECTOR_RUNTIME及DATA_MODEL：合法边、终态、待确认/未决、来源/知识/发布/解析生命周期 | 设计一致；真实并发待测试 |
| 14 | 迁移/回退 | DATA_MODEL M01–08、DEPLOYMENT：实际0099前提、历史定位转换、空库与有数据边界 | 不授权破坏性回退；实际实例仍未知 |
| 15 | 部署/运维 | [DEPLOYMENT](../DEPLOYMENT.md)：原Windows/WSL2方式、准入mode、处理器、restic多库/对象恢复 | 设计已选；未安装/启动/恢复 |
| 16 | 完整测试矩阵 | [TEST_EVIDENCE](TEST_EVIDENCE.md)、[DEVELOPMENT](../DEVELOPMENT.md)：38需求/16组，实际质量入口及合成/真实分层 | 用例计划齐全，不算测试已通过 |
| 17 | 实施依赖图 | [MASTER_EXECUTION_PLAN](MASTER_EXECUTION_PLAN.md)：14执行阶段/26批次、依赖图、I6a/I8a先行及真实实例保护前置 | 无环；非空壳阶段编号 |
| 18 | 自主执行合同 | MASTER_EXECUTION_PLAN、PHASE_GATES、N11：批次入口/退出/Review/修复预算、当前授权与硬门 | 普通工程已获主合同/N11授权 |
| 19 | 一致性审计 | 本节、[ARCHITECTURE_MAPPING](../ARCHITECTURE_MAPPING.md)完整追踪/能力处置、风险登记及冻结指纹 | 设计审计通过；不等于目标全部完成 |

核心修正已回填：旧权限/布局/词表歧义、Operation基数及本地事实、O7顺序、O2精确wire改名、
计划decision_basis去重与CAS、分块本地Flow与reparse回执、asset生产目标/授权、剪辑固定来源选用证明、
备份实际目标/模式/会话密钥、N11后续统一执行。所有工程选择标E类，不伪装成Owner逐项亲自批准。
旧材料版本关系明确：所谓v2是v1原件+第三轮候选组合；新冻结规则以CURRENT所列权威为正文，外部原件保持不变。

设计冲突：C01–C09/C11/C13的设计歧义已处理；C10实际实例身份、C12设备/质量以及各RSK的运行验证仍未关闭，
分别阻断相应实施/最终验收，而不阻断已有明示边界的设计冻结。无未经确认的Owner决策变更或第二Runtime被写为批准。
证据：38项架构追踪与38项测试映射、16测试组、14阶段/26批次、28文档文件链接检查；
全部1358旧跟踪路径比较只改变设计文档，原非设计dirty保持；原型语法/格式及前述DOM用例见EV记录。
检查只证明文档/原型范围，未执行产品Full、迁移、真实Provider或实际部署。源码dev/远端dev仍为eff39bf…，
合同12/11文件hash复核未变。所有设计成果目前未提交，不虚构clean候选或发布状态。

冻结编号D8-20261117-r1，精确文件指纹与只读快照由[DESIGN_FREEZE.json](DESIGN_FREEZE.json)登记。
指纹是本次时间点证据，不是第二套长期权威；实现中必要设计修订须回填原文件并记录影响，不静默换合同。
结论：D8设计冻结通过，进入I0只读工程基线及隔离验证准备。完整目标仍为I0–I10产品实装/测试/恢复/三作品验收，
任何费用、扩大真实资料外发、不可逆数据动作和发布都不因本结论获批。


## 工作区身份与运行证据

分支dev；HEAD及远端dev：eff39bf0c940da4dc5dcaa42388d432a2a77111f。
远端main：c12c3dfb89cca92a45de99a6db4ade2f0c5f19e7。
源码迁移图103 revisions、唯一head 20261113_0099；N12旧库实查为20261103_0096，重建后的dramaforge-dev实际head为20261113_0099且alembic check通过。

续接前已有14M/3D，清单见D0/02。涉及CI、Workflow模板、FinalFilm、相关测试、ARCHITECTURE_MAPPING、PRODUCTION_GRAPH、architecture-baseline；不将这些改动计入本次成果。已保存本轮开始1358个tracked路径的内容hash/删除状态用于保护校验，不创建长期源码副本。

D8冻结时Docker不可用；N12之后已取得实际运行身份并重建。当前12常驻服务healthy，3初始化任务exit0，users/projects/provider_operations/node_runs均0；访问http://127.0.0.1:8080显示首次Owner初始化。没有真实Provider调用。


## 人工审批与下一步

三项产品问题已答复，见[DECISION_LOG](DECISION_LOG.md)。2026-11-17 Owner先要求保持旧栈停止，随后N12明确允许旧容器和不重要数据重建；按后者执行，先防止恢复、再核对旧库为空、最后替换旧栈。此具体环境任务已完成，不自动取消用户设置的长期Goal暂停。恢复长期任务后，下一步是I0隔离质量镜像/测试与Full，而不是再次询问旧任务状态。
此前Docker不可用曾连续三回合形成blocked；现已由N12解除。未来费用、扩大真实资料外发、正式发布等原硬门保持；不把本地重建当正式发布授权。

2026-11-17 Owner重新激活目标后，保持“业务栈停止”限制，重新核对隔离验证替代路径。主合同I0是工程基线，
其§8允许普通迁移开发与隔离库测试；当时现有实例状态尚未查明，也未启动Docker Desktop或旧WSL实例。
本机docker desktop start帮助与官方文档只有detach/timeout，无禁止容器恢复开关；两个现有context都指向同一Desktop安装。

已被N12替代、未执行且不再待批准的候选：新增仅本任务使用的WSL2实例`dramaforge-quality-i0`，安装目录固定为
`D:/dramaforge/tmp/i0-engine/wsl`，从Ubuntu官方24.04.5 amd64 Base原件导入（SHA256
`e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86`）。
仅在新实例安装Docker/Compose构建工具，通过其Unix socket运行；不开放Docker TCP API，不设为默认发行版，
不改Windows全局Docker context或.wslconfig，不挂载旧docker_data.vhdx、不复用旧容器/卷/凭据，不启动Docker Desktop。
现有质量脚本/锁定应用依赖不换栈；执行时用任务局部WSL调用适配路径，全部DB/模型上游为合成fixture。
这只是测试环境，不替代现有Windows/WSL2/Desktop部署验收；C10旧实例核验在接触该实例前仍必须关闭。
预计需数十GB测试镜像空间，当前D盘约150GiB可用。只清理确认属于本任务的新实例和资源，保留现有两个发行版及数据。
此候选涉及新增系统级WSL注册/工具环境，当时拟单独确认；N12随后选择重建旧环境，没有下载/导入/安装新实例。
依据：https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro 、
https://docs.docker.com/reference/cli/docker/desktop/start/ 、
https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/SHA256SUMS 。


## I0首批工程进展

恢复后的首轮Full：`scripts/run_quality_in_docker.ps1 -Stage Full`，项目df-quality-i0-20261117-a，
输出tmp/i0-full-a.log，合同目录tmp/quality-contract/df-quality-i0-20261117-a；exec session16307已结束exit1。
目录/架构/Provider合同/ruff/mypy通过；2550单测通过（1条Connection._cancel未await警告）；
迁移head及alembic check通过，176项PG集成通过。前端API权威/生成类型一致性通过，format:check仅报design/README.md。
已用同次frontend质量镜像的Prettier修复该文档格式，不改规则内容；其余源代码未改变。
前端诊断链exec session28807已结束exit0，使用原固定image ID、network none、原OpenAPI及修正后的README只读挂载；
日志tmp/i0-frontend-feedback.log，输出合同目录内frontend-feedback。
前端format/lint/UI权威、87文件746单测、typecheck/build/routes及211浏览器测试全部通过（E2E 9.4m）。
新增机构接线已在独立df-quality-i0-institution-20261117-a项目实际通过：初始化/受限角色、API/dispatcher/三Worker健康，
1个真实旅程case（项目保存、TXT原件/后台解析/来源内容、浏览器刷新、跨用户列表/修订/原件拒绝、上游调用0）通过；
该项目及其临时输出已清理，日志tmp/i0-institution-a.log。此case不是三作品或全机构能力验收。
网关/Proxy诊断exec session48780已结束exit0：网关1项、Proxy及策略35项通过，项目df-quality-i0-proxy-20261117-a及临时输出已清理。
日志tmp/i0-proxy-feedback.log；复用原固定image ID、合成配置。no-such-alias报错属于实际负向用例，测试进程退出0；未调用外部模型。
媒体资源诊断session47070已结束exit0：256MiB、并发1/4真实TLS下载/MinIO上传流读2项通过（22.37s），Provider create=0，独占项目及临时输出已清理。此测试在浏览器资源基准结束后才运行。
以上分项不拼成Full。第二轮df-quality-i0-20261117-b/session2365的2550单测再次通过，警告仍发生于同一case；
随后定位到前一dispatcher生命周期单测只隔离两个循环，新增资料循环会实际尝试数据库连接。为修复该测试候选，
主动停止已核对归属的backend测试容器；第二轮以137结束，资源自动清理，不把主动中止记录为Full通过或基础设施自行失败。
修复test_provider_recovery原用例：资料循环启动/阻塞/停止也受断言，禁止测试接触真实session factory，停止后三个任务均不得残留。
同次新构建镜像中14用例在network none且RuntimeWarning=error通过，ruff通过。负向对照仅去掉资料循环隔离，
用例按预期因未启动合成循环而超时，日志明确记录被guard阻止的数据库访问；真实数据库未连接。未修改业务运行逻辑。
第三轮无过滤Full：项目df-quality-i0-20261117-c，exec session=30270，日志tmp/i0-full-c.log，合同目录tmp/quality-contract/df-quality-i0-20261117-c。
第三轮2550单测已通过（334.58s），无RuntimeWarning汇总；176 PG集成通过（494.10s），迁移/check通过。
前端API类型/format/lint/UI权威、87文件746单测（221.43s）、typecheck/build/routes已通过，211浏览器测试继续在同一Full运行中；前述漏隔离修复得到完整单测验证。
第三轮session30270已结束exit0：2550后端单测、176 PG集成、746前端单测、211 E2E、2媒体、1网关、35 Proxy/策略、1机构真实链路均在同一次无过滤Full通过，自动清理成功，项目标签下无剩余容器。
镜像为backend sha256:7afb81e4ac62af05ce3c26986904c35451b16783ffb8eee6d73fedc77aeefffb、frontend sha256:36445e2099b1b9d0d404f5dfd1b982980469fe50ec6742a64c99edec50894364。HEAD及远端dev仍eff39bf…；代码含原dirty，非clean发布候选。
I0退出审查：现有源码/工作区保护、旧/新实例Schema及角色、空生产任务、隔离测试和备份适用性边界均已核对；N12批准旧空实例重建，未使用有缺陷的旧restore分支。全量实际验证通过，I0准入I1。
已消费的A/B失败诊断、分项成功输出与C普通成功输出按DEVELOPMENT清理；结果与镜像身份保留于本节/TEST_EVIDENCE。D8冻结快照和当前.env引用的tmp/i0-runtime.override.yml仍保留。

I1开始身份：dev/eff39bf0c940da4dc5dcaa42388d432a2a77111f，远端dev相同、main=c12c3df…；本地运行Schema0099，ProviderOperation/NodeRun查询均空。I1只对隔离合成库测试，不自动升级本地业务实例。
I1-01已开始写入：Project/Workspace模型增加作品类型、目标、受众、时长/集数与组合约束/候选键；
新增ProjectIntent领域校验及0100迁移（旧类型保持NULL、有新意图值拒绝有损downgrade）。
（开工时点记录：该轮上下文中断前实际已接通API/服务/两处分集写入口/前端/客户端生成与测试；
最终实施、Review与验证结论见文末I1-01节。）本地运行库仍0099，未执行新迁移。
警告定位到的2个恢复case在同一backend镜像、network none、RuntimeWarning升级error复测通过（2 passed/12 deselected），
未单独复现，不虚构已修复。所有结果只是当前阶段进展，Full尚未通过，I0不退出。

N12运行处置（2026-11-17）：离线挂接原Docker数据盘，只读识别16容器全部归属dramaforge-owner-28ca4b70且工作区为D:/dramaforge；核对hash后将其restart设为no并标手工停止，再卸载数据盘、启动引擎。启动后16容器均未运行，未恢复Worker。
只启动旧PostgreSQL读取：实际head=20261103_0096，projects/provider_operations/node_runs均0；app/checkpoint角色均非superuser、无BYPASSRLS、NOINHERIT，public有60表启用RLS。旧实例身份已取得，不能再写“实际Schema完全未知”。
已按当前dirty工作树构建本地重建镜像，前端容器内typecheck/Vite build通过；已补.env中缺失的LiteLLM调用/管理key和salt，仅更新运行身份及缺项，不输出或改写已有Provider凭据。未创建新WSL实例，离线盘点临时启动的Ubuntu已终止。
旧项目dramaforge-owner-28ca4b70的16容器、4命名卷及2随容器删除的匿名卷、1网络已删除；共享镜像/缓存保留。新项目采用仓库默认dramaforge-dev。
默认Quay MinIO地址401，保留原实例实际使用且质量门已固定的GHCR摘要镜像，通过本地`tmp/i0-runtime.override.yml`覆盖；.env的COMPOSE_FILE/COMPOSE_PATH_SEPARATOR引用该文件，当前仍有用途，不能作为无用tmp清理。LiteLLM固定到源码规定的90d8de…摘要。源码Compose没有修改。
新栈`docker compose -p dramaforge-dev up -d --no-build --wait --wait-timeout 180`退出0；12常驻服务healthy、migrate/database-bootstrap/litellm-bootstrap退出0。新库0099、alembic check无差异，app/checkpoint角色均非superuser/NOBYPASSRLS；users/projects/ProviderOperation/NodeRun均0。
运行镜像：backend sha256:1426833c5a46c9f19837ebb1204f5a9701c3d41992411f72dbc37392741d92c8，frontend sha256:f3c7cf8eb85feaafbf4a68d53167139022ecddf7e999c5529467f9aeac2f00d5。全部后端服务使用同一镜像；来源标签eff39bf…另含当前未提交代码，不冒充clean构建。
浏览器实际DOM确认首次Owner标题/按钮可见，health与bootstrap-status均200；auth/me的401是未登录预期，无业务写入。运行重建验收完成，机构业务旅程和Full未执行。

D8冻结32文件指纹及临时zip已建立；后续状态/权威更新不会重写其时间点指纹。28文档文件链接无缺失，38项需求/追踪/测试、16组、14阶段26批次无环；不是产品运行PASS。
I0-02在现有quality Compose和Full脚本加入8个内部网络服务，复用同次构建image ID；新库/桶/Redis DB14合成配置，
业务进程使用非superuser、NOBYPASSRLS角色，不继承.env凭据，无宿主端口。bootstrap拒绝已有库，不改真实实例。
新增真实API/来源解析/浏览器读回/跨用户拒绝baseline和拓扑安全用例；复用已有mock上游计数，未伪造业务API响应。
续接Review修正：Playwright同时核对E2E_API_URL及优先级更高的API_URL，防止绕过隔离目标；负向用例新增“他人合法Workspace+外部project/revision/original ID”，不只测试伪造Workspace头。Compose实际解析/内部网络检查仍通过；这些浏览器断言尚未运行。
实际验证：Compose解析及8服务单internal网络/零端口检查通过；PowerShell生命周期原场景与新增启动失败23/浏览器失败29传播及资源收尾全部通过。
尚未运行：质量镜像中的Python测试/ruff、前端format/lint、机构套件真实旅程及Full；N12只有本地运行重建、前端build/typecheck、迁移/模型一致性和首屏检查通过，I0整体仍未通过。
质量接线批次不改业务Model/Migration/生产Compose；N12另外已授权修改本地.env和执行新空库迁移/旧容器数据清理。两者均无Provider调用。
保护复核：1358原跟踪路径仅20设计文档及5个本批质量/测试文件变化，新增第5项为test_provider_recovery的上述隔离修复；意外变化0，原非设计dirty保持。新fixture/Playwright文件仍未提交。


## I1-01实施与验证（2026-11-17）

上轮上下文在批次中途结束时，I1-01竖向切片已实际写入工作区；本轮逐文件核对确认API/服务/两处分集写入口/
前端/客户端生成/测试均已接通，随后完成代码Review、一次失败诊断修复与完整验证。产品代码预期未修改。

实施要点：
- 后端：projects新列work_type/creative_goal/audience/planned_duration_seconds/planned_episode_count及
  CHECK/唯一约束（0100迁移：旧类型保持NULL待确认；有意图值或project_changed事件时拒绝降级，空字段可回退）；
  ProjectIntent类型校验；create必选work_type、PATCH部分更新与intent-preview均走expected_version CAS；
  结构冲突阻断（现有分集超过新计划、改变作品类型与既有正式Export范围不兼容）不自动删除或改写正式事实；
  episodes.py共享分集准入同时接入script import与typed story.upsert_episode两处写入口，Project行锁下
  并发新增分集只有单胜者。
- 前端：CreateProjectForm必选作品类型；ProjectIntentEditor预览-确认两步门、版本冲突时对照最新并保留
  草稿；ProjectCard类型标签；api.ts客户端与generated.ts（OpenAPI 294 schema权威检查逐字节通过）。
- T01/API-P01证据：unit test_projects_api.py 27项新增（三类型往返、非法组合拒绝、CAS部分更新与冲突保持、
  无变化不升版、ProjectChanged事件回执、越权拒绝）+新integration test_institution_projects_pg.py 5项
  （import/import、import/apply、apply/apply并发单集唯一胜出；CAS+事件+两用户三项目RLS可见性与异主404；
  0100升级/约束拒绝/拒绝降级/空字段回退）；E2E project-intent.spec.ts三类型真实旅程与分集保护。

失败与修复（EV51）：首轮Full在integration失败1项——新PG用例终段把异主用户RLS project上下文绑定到
他人项目却期望可见自己项目。诊断为测试缺陷而非策略缺陷：projects_workspace_scope按当前project_id钉住
是0005/0010以来既定语义，真实请求以workspace作用域进入并由get_project_for_owner逐项目重绑。
最小修复终段绑定foreign_id，与同用例前段可见性循环一致；未改产品代码、未放宽断言；修复后在独占
df-quality-i1-01-pg-2005e431（镜像sha256:6d7d5139fd3d…）复跑该文件5用例通过（42.60s，exit0）。

第二轮无过滤Full：df-quality-f8fabf9532ba4535befb070fcb5a8e0c，exit0，自动清理成功（EV52）。
同次通过：静态门、ruff/mypy、2577后端单测（337.49s）、迁移upgrade+check、181 PG集成（532.05s，
含机构项目5新用例）、OpenAPI 294 schema类型权威、前端format/lint/typecheck/build、89文件754 Vitest、
211 mock E2E（8.8m）、2媒体资源、1网关、35 LiteLLM、机构真实栈5浏览器用例（38.3s，上游模型调用0）。
镜像：backend sha256:d4554b83245c9877…、frontend sha256:363a0cc96d75efae…。快反馈：targeted后端
2577过、targeted前端754过（exit0），日志已按生命周期清理。

I1-01退出判定：批次合同证据齐全（三类型/约束持久读回、并发CAS、旧NULL保持、并发分集真实PG、
两用户三项目切换、真实API+UI旅程），受影响回归通过，代码Review完成，无未决失败。按主合同进入
I1-02（资料原件/版本/基础提取：M04基础Extraction与纯本地提取、T02；此时只合成资料，不启动语义研究）。
本地运行库dramaforge-dev仍0099：0100仅在隔离质量库验证，不自动升级运行实例。


## I1-02实施与验证（2026-11-17）

交付：M04基础部分——不可变解析快照，未新增Runtime/任务状态表。
- Schema（0101）：source_extractions（attempt/parser_key/parser_version/content_hash/
  extraction_schema_version/coverage/processor_evidence/completed_at，UNIQUE(file_revision_id,attempt)
  与(id,file_revision_id,project_id)）；source_fragments（ordinal/locator_kind/locator/text_content/
  content_hash/extraction_method/processor_ref/evidence_meta，UNIQUE(extraction_id,ordinal)）；
  project_file_revisions.current_extraction_id为只前移指针，复合延迟FK绑定同一revision；
  两表FORCE RLS按项目，运行角色仅SELECT/INSERT（显式REVOKE UPDATE/DELETE/TRUNCATE）。
- 迁移转换：旧inline excerpts(1基location)按DATA_MODEL逐形状确定转换为schema2 0基半开区间，
  原location与转换版本保存在evidence_meta；未知形状/空结果fail-closed并以安全ID清单阻断整次迁移，
  不静默丢弃、不伪造页码；旧列在转换后删除，无新旧双写。降级在有任何快照时拒绝并保留头。
- 解析器：输出FragmentDraft(locator_kind+locator+text+evidence_meta)；schema2与processor_evidence
  （ref/engine/version/settings_hash/network_mode=local及coordinate_system）随解析结果返回；
  coverage以可寻址单元计数（CSV按行、DOCX按段/单元格），任何遗漏直接报错而非标记部分完成；
  char范围按Unicode码点（含emoji用例）。
- 服务/API：extract()在revision锁内追加不可变Extraction+Fragments并CAS前移指针，重复投递幂等；
  修订读取改为{source,extraction|null,source_available}；新增extraction详情与fragments分页
  （total为集合总数、next_offset按总数计算、可按locator_kind过滤）。旧SourceExcerptsRead删除。
- 前端：新增「项目资料」入口与页面（上传、状态、失败重试、解除关联、快照与片段定位显示），
  使用既有UI库控件（Upload），导航计数契约同步6→7；generated.ts由真实OpenAPI重生（298 schema）。

失败与修复（EV53）：①0101在backfill后DROP COLUMN触发`cannot ALTER TABLE ... pending trigger events`
→改为backfill→drop→最后建延迟FK；②0005的`ALTER DEFAULT PRIVILEGES`为新表默认授予UPDATE/DELETE，
「不授予」不足以保证不可变→显式REVOKE并保留语句级拒绝断言；③旧用例断言head=0100/旧降级文案→更新为
0101与新SOURCE_EXTRACTIONS守卫，拒绝语义未放宽；④navigation-ia按新IA更新计数与顺序断言。
前三轮Full均不通过且未计入证据；每项均定位根因后最小修复。

验证：无过滤Full df-quality-da90eb1d8c17485b89df8ed673795b13，exit0，清理无残留（EV54）：
静态门、ruff、mypy 351文件、2580单测（341.75s）、迁移upgrade+check无漂移、184 PG集成（562.24s，
含0101转换/未知定位阻断/append-only/RLS三用例）、OpenAPI 298 schema、前端format/lint/UI权威/
typecheck/build、89文件754 Vitest、211 mock E2E（9.7m）、2媒体、1网关、35 LiteLLM、
机构真实栈5浏览器用例（37.4s，上游0调用）。镜像backend sha256:247192e60a34…、
frontend sha256:3fdd6726690a…。定向轮次：backend ruff/mypy/39用例、frontend typecheck/lint/
754用例、0101 alembic check、PG两模块6用例均通过后才有上述Full。
Gate后仅做两项非行为收尾：删除models.py文件末尾空行（`git diff --check`由2→0，ruff与导入复验通过）
与清理本批tmp输出；未改任何断言、Schema或运行逻辑。

I1-02退出判定：T02基础部分证据齐全（原件hash/版本/重放、跨项目隔离、不可变快照、旧数据确定转换、
fail-closed阻断、真实PG RLS与授权），进入I2a-01。未完成且不冒称：PDF/图片/音视频七类格式真实处理器、
OCR/ASR、source-capabilities、analysis_mode/processing摘要、reparse与事件schema v2（按计划属I4）；
本地运行库仍0099。


## I2a-01实施与验证（2026-11-17）

交付：M02第一批——持续目标、不可变计划与控制回执；未新增Runtime或第二任务状态机。
- Schema（0102）：`director_master_runs`（来源Thread/Turn、goal、current_plan_id、八态status、
  desired_state、epoch/revision、终态与归档不变量、项目/线程/来源复合FK，来源恒为agent）；
  `director_master_run_plans`（revision/schema_version/plan_hash/plan_data/decision_ref，不可变，
  UNIQUE(run,revision)/(run,plan_hash)/(project,decision_ref)）；`director_master_run_control_receipts`
  （operation/expected_revision/request_hash/result_revision，result=expected+1，UNIQUE(run,expected,operation)，
  不可变）；Turn增加master_run_id/plan_revision及候选键；ProposalItem补(id,project_id)候选键。
  Run→Plan与Turn→Run/Plan指针最后以ALTER建成延迟FK；Run仅SELECT/INSERT/UPDATE，Plan/Receipt仅
  SELECT/INSERT（显式REVOKE，因库级默认授权会授予新表全部写权限）。
- 服务：`create_for_origin_turn`只能由本用户、本工作空间、带线程的agent Turn建立；同Turn重放返回原绑定、
  异目标409、普通问答不建Run；`append_plan`校验顶层形状与decision_basis（observed revision/epoch/
  当前计划），按(run,plan_hash)返回原计划、不推进Run业务revision，并要求该项目的typed决策项；
  `apply_plan`（typed命令`director.master_run_plan_apply`）CAS revision/epoch后写current指针、epoch+1、
  revision+1，planning→waiting，拒绝回退到更早计划；`control`按(run,expected,operation)回执幂等、
  同键异载荷409、沿D3冻结状态边（未列出的边拒绝），pause/resume/cancel改epoch，verify仅在
  desired_state=run且waiting且有已确认计划时记录`satisfied:false`回执并保持waiting；`archive`只对终态。
  事件：master_run_changed/plan_proposed/plan_applied经director侧通知端口写入既有production.facts.v1。
- API：目标列表/单目标/计划列表/计划详情只读（progress与unresolved按设计返回null+read_blockers，
  不序列化成0），pause/resume/cancel/verify与PATCH归档；generated.ts由真实OpenAPI重生（304 schema）。

过程中两次真实事故与修复（EV55/EV56）：架构门拒绝director→production与shared→新director模块两条
新增依赖债，改为同层通知端口并经既有turn_models注册；`git checkout --`误清上一会话I1-01分集准入接线，
按早前完整读取的原实现恢复并由回归用例确认。另外修正SQLite不支持的btrim、延迟FK的commit断言、
两处旧head断言与一处决策项复用。均未放宽断言。

验证：无过滤Full df-quality-dcf12cea555b48069af8bc797fdcd9f0，exit0，清理无残留（EV57）：
静态门、ruff、mypy 354文件、2586单测（347.41s）、迁移upgrade+check（head 0102）无漂移、
187 PG集成（573.23s，MasterRun 3项含RLS/append-only/来源FK/终态与归档/拒绝降级）、304 schema、
前端format/lint/UI权威/typecheck/build、754 Vitest、211 mock E2E、2媒体、1网关、35 LiteLLM、
机构真实栈5浏览器用例。镜像backend sha256:f7e5c7bd5872…、frontend sha256:65906e97e419…。

I2a-01退出判定：T06/DB07/12证据齐全，进入I2a-02。未完成且不冒称：202受理侧create_goal自动建Run
（I2b）、Flow/步骤/attempt读投影与完成谓词（I6a）、cancel对远端任务的实际核对；本地运行库仍0099。


## I2a-02实施与验证（2026-11-17）

交付：运行控制由“跨步持锁”改为短事务准入+发布，旧lease/epoch语义保留，未新增Runtime。
- `DirectorRuntimeControlService.begin_step(lease)`：短事务内校验lease（owner/epoch/有效期/未stop）
  并返回StepTicket(epoch, revision)，调用方提交后释放行锁；图执行期间不再持有控制行锁。
- `commit_step(ticket, runtime_status=…)`：短事务重新加锁，若epoch、行revision、lease owner或
  stop标记任一变化则抛`DIRECTOR_RUNTIME_LEASE_STALE`且不写；否则清lease并落状态/revision+1。
  删除旧`guard`（跨步持锁），不存在第二套控制路径。
- 执行器start/resume改为：claim→begin_step→提交→图/工具（无锁）→commit_step→投影→提交；
  异常仍走`_recover_lease`释放lease。stop路径保持“先持久化停止意图再处理checkpoint”的顺序。

验证：新PG用例覆盖①准入后另一worker可接管（证明无跨步锁）②接管epoch+1后原worker发布被拒且
状态未变③步内request_stop同样围栏发布；既有binding/RLS/信号claim与真实checkpoint scope用例同批通过。
无过滤Full df-quality-423f6253efa24ee7b1a6c903707103ec，exit0，清理无残留（EV59）：
2586单测、188 PG集成、迁移check、304 schema、754 Vitest、211 mock E2E、媒体/网关/LiteLLM、
机构5浏览器用例。镜像backend sha256:6e121de7a1be…、frontend sha256:5b3740241cdd…。

I2a-02退出判定：T08短事务/锁序/迟到写证据齐全，进入I3-01。未完成且不冒称：Worker真实文本仍须
I3安全门通过后才启用（本批未启用）；checkpoint级epoch围栏（checkpoint_ref/应用指针）按D3设计在
I2b随异步执行接线，本批只保证控制行与投影写入的围栏。


## I3-01实施与验证（2026-11-17）

交付：M03第一批——可信目的地声明与项目外发策略；未新增外发任务表，未改变任何真实出口。
- Schema（0103）：`provider_destination_revisions`（绑定引用、修订、origin、处理位置、用途、
  declaration/configuration hash、route_manifest、location_evidence；工作空间作用域RLS；
  UNIQUE(binding,revision)与(binding,origin_expected)）；`project_egress_policy_revisions`
  （mode current/local_only/allowlisted、policy_data、policy_hash；项目RLS；UNIQUE(project,revision)
  与(project,origin_expected)）；`project_egress_policy_heads`（唯一可变指针，复合延迟FK回修订）。
  revisions两表仅SELECT/INSERT（显式REVOKE），head允许UPDATE。
- 目的地服务：binding_ref只接受本工作空间已登记的`ProviderModelBinding`；origin/route_manifest/
  configuration_hash全部由真实连接列派生；客户端须先回读configuration_hash，漂移即拒绝；
  `local`只在origin为私有/回环地址时接受（否则DESTINATION_LOCAL_UNPROVEN），并记录origin_class证据；
  额外结果来源必须是显式scheme://主机[:端口]（禁通配符/query/凭据/路径）；同(binding,expected)同hash回原声明、
  异hash 409。
- 策略服务：无head时GET返回revision0/current且零写入；PUT expected0直接建立请求的revision1；
  否则按head CAS，重放同basis+同hash返回原修订、同basis异hash冲突；local_only/current禁带载荷；
  allowlisted要求同Workspace可信目的地且其purpose集合覆盖全部允许用途；同事务写
  `project_egress_policy_changed`。
- HTTP：`GET/PUT /projects/{p}/egress-policy`、`GET/POST /workspaces/{w}/provider-destinations`；
  generated.ts由真实OpenAPI重生（308 schema）。

失败与修正（EV60）：`protocol`属性不存在→改用`protocol_profile`；策略重放次序须先于head比较；
文档head与实际链不一致由既有契约测试抓到（镜像构建早于文档更新）；三个PG用例硬编码head过期→
改用`pg_support.alembic_head()`按唯一链头断言（仍校验"头未变"）；ruff/mypy按真实类型修复。

验证：无过滤Full df-quality-b77a36505639450c8545f31a5e316263，exit0，清理无残留（EV61）：
2592单测、191 PG集成（含egress 3项）、迁移check（0103）无漂移、308 schema、754 Vitest、
211 mock E2E、媒体/网关/LiteLLM、机构5浏览器用例。镜像backend sha256:f3694888d8f2…、
frontend sha256:9358db858ab0…。

I3-01退出判定：管理面（API-S01–04）证据齐全，进入I3-02。未完成且不冒称：真实出口的准入强制与
撤销屏障、SourceUse交集、预览egress摘要、Worker真实文本启用；本地运行库仍0099。
Gate后仅清理`pg_support.py`文件末尾空行（`git diff --check` 2→0），未改代码逻辑或断言。


## I3-02部分实施（准入与来源用途，2026-11-17）

交付：M03第二批的数据与准入核心；**该批次未完成**，不得标阶段通过。
- Schema（0104）：`source_use_subjects`（原件修订/素材二选一、forward指针、version）、
  `source_use_revisions`（number/origin_expected/result_version=+1、state unreviewed/declared/revoked、
  allowed_uses、statement、content_hash、request_key；不可变）、`artifact_source_uses`
  （artifact×subject×input_role唯一，绑定实际消费的声明修订与access_kind）；三表项目FORCE RLS，
  声明/血缘仅SELECT/INSERT，subject允许UPDATE指针。
- 服务：`assets/source_use.py`提供声明/重放/撤回（撤回后不能原地恢复，只能新建声明）、
  `gate()`按required_uses求交集、`record_artifact_source_use()`冻结实际消费修订。
- 准入：`access/egress_admission.py`单一决定（current→legacy_current；local_only要求实际hop为local
  且声明为非local的目的地不能被洗白；allowlisted要求目的地命中的策略修订且required_purposes全部被
  策略与目的地声明覆盖；unknown位置不被当已核实；SourceUse阻断优先），结果可冻结为
  `egress_admission`证据。
- 出口接线：导演文本在写Invocation与任何远端调用之前准入，拒绝以`EGRESS_*`码返回、0请求、
  不留Invocation；允许时把准入证据写入request_snapshot。

验证：针对PG source-use 3项、单元23项通过；无过滤Full df-quality-8bfa8bca4c7c4f0ca8be8370cdcfaf40，
exit0，清理无残留（EV63）：2595单测、194 PG集成、迁移check（0104）无漂移、308 schema、754 Vitest、
211 mock E2E、媒体/网关/LiteLLM、机构5浏览器用例。镜像backend sha256:7d736e46a1ff…。

I3-02未完成项（下一轮继续）：`providers/reference_delivery.py`与Production发送入口接入同一准入并做
撤销前后屏障；执行/研究预览返回egress摘要与required_purposes推导；来源用途HTTP入口（随I4）。
本地运行库仍0099。


## I3-02完成轮（引用签发与生产提交，2026-11-17/18）

- `issue_artifact_reference`在生成任何token之前调用同一准入（purpose=reference_delivery，
  默认processing_location=external）；拒绝时抛`EGRESS_*`且**零token**；允许时把准入证据写入
  `artifact_reference_tokens.egress_admission`（0105新增可空列，旧grant保持NULL且不重写）。
- `submit_user_execution`在获取命令锁、查回执与创建ProviderOperation之前准入
  （image_keyframe→image_generation、video→video_generation，external hop）；拒绝即零操作、零回执。
- 新增用例：引用签发在strict/ local_only下拒绝且token计数不变、默认路径写入legacy_current证据；
  生产提交路径回归（workbench/batch/reference共53项）在默认策略下不变。

验证：无过滤Full df-quality-08af152b81764b5aaa697bbb3505a5a1，exit0，清理无残留（EV64）：
2596单测、194 PG集成、迁移check（head 0105）无漂移、308 schema、754 Vitest、211 mock E2E、
2媒体、1网关、35 LiteLLM、机构5浏览器用例。镜像backend sha256:256b78d17ee7…。

I3-02退出判定：三处真实出口（导演文本、引用签发、生产用户提交）均在外副作用前拒绝且零请求，
SourceUse与策略交集独立生效，拒绝码原样返回。仍未实施并明确不冒称：执行/研究预览egress摘要、
来源用途HTTP（随I4/I8预览面）。本地运行库仍0099。下一批I2b-01。

### I2b-01 待执行范围（2026-11-18记录，尚无代码变更；需连续实施预算）

本轮只做只读侦察，未改代码：确认现有异步机制只覆盖"生产事件→runtime wakeup"，聊天受理仍是同步
`DirectorAgentService.run`。改造成202必须整片完成，不能只改HTTP状态码。

已核对事实：`api/v1/director.py::run_director_agent_turn` 同步调用 `service.run` 并返回
`AgentTurnResult`；`workers/director.py` 有 dispatcher→`execute_director_wakeup`/`execute_director_runtime_wakeup`
与 `recover_interrupted_director_turns`；`director_inbox/director_wakeup` 由生产事件驱动，不是聊天受理队列；
Turn已有`queued`状态与`request_summary`列（无需新表/迁移）。

实施顺序（同一批次，全部通过才记录）：
1. `agent_service.py`：`AgentRequest`增加`intent:conversation|create_goal|continue_goal`与
   `master_run_id`；新增`accept(thread_id, request)`—解析thread/模型配置（无网络），写user message与
   `status=queued`的Turn（把content/intent/limits/request_key存入`request_summary`），同事务追加
   `director.turn.accepted` Outbox事件（`EventService.append_with_outbox`，project scope）。
2. `agent_service.py`：把现有`run()`拆为`_execute_accepted(turn, payload)`，由`run()`（同步回放兼容）
   与新`execute_queued(turn_id)`共用；执行前以CAS `queued→thinking`+epoch领取，失败/中断沿用
   `recover_interrupted_director_turns`。
3. `agent_service.py`：`create_goal`在Turn flush后同事务调用`MasterRunService.create_for_origin_turn`；
   `continue_goal`校验同项目/同Thread的Run并绑定；conversation不建Run。
4. `api/v1/director.py`：POST改为202 `AgentAcceptance={thread_id,turn_id,user_message_id,master_run_id,
   status:"accepted",request_key}`；保留GET turn/thread与requests回放；同步`run`路径删除，不留双写。
5. `workers/director.py`：cron扫描`turn_kind='agent' AND status='queued'`（带游标，参照
   `workers/project_files.py`）→enqueue `execute_queued`；处理断线后继续与重启复活。
6. 测试迁移：`test_director_agent_api.py`等把"POST返回完整结果"改为"202+轮询/worker执行"；
   新增T08/API-D01/06用例（普通问答无Run、create_goal有Run、重复key回放、断线不取消、epoch迟到写拒绝）。
7. 前端：`generated.ts`重生（响应类型变化）、调用方改为受理后轮询；E2E更新。
8. 收尾：无过滤Full与证据（EV65），更新API/DEVELOPMENT/状态。

在此之前I2b任何部分都不标通过；本地运行库仍0099。上次无过滤Full（EV64）仍是当前代码验证基线。


### I2b-01 状态（2026-11-18）：切片已交付并通过Full，其余未实施

rounds 10/11/13/14 四次尝试均因同一原因失败：该批次要求"202受理+Outbox+worker执行+epoch/checkpoint+既有测试迁移"在同一轮内完成并跑无过滤Full，剩余会话预算不足以安全完成；每次失败均整体回滚，未留未验证表面。最后一次尝试暴露的缺陷：第二次`execute_queued`仍读到`queued`并抛`DIRECTOR_AGENT_TURN_NOT_EXECUTABLE`，即领取/状态提交尚未正确。

审计结论：当前代码等于EV64的Full验证状态（I1/I2a/I3各批），不含intent/202/worker队列改动。下一轮应从零实施该批次，或由用户决定更换执行方式。


## I2b-01完整闭环（2026-11-18，EV68）

本轮在EV66（intent/create_goal切片）之上一次性完成受理、执行与全部测试迁移，未回滚、未删除既有成果。

交付：
- **受理**：`DirectorAgentService.accept`在一个短事务写user Message、`status=queued`的Turn
  （`request_summary.request/input_hash/accepted_revision/limits`、冻结的intent_snapshot）与
  `director.turn.accepted` Outbox事件；不打开checkpoint、不调模型、无内存后台任务。
  `AgentAcceptance`由这些持久事实投影（`status:"queued"`不随完成改写）。同键同输入返回原受理
  （200），同键异输入409 `AGENT_REQUEST_KEY_REUSED`。
- **执行**：删除同步`run()`；唯一执行入口`execute_queued`以单条CAS领取
  （`queued→thinking`、`agent_control_epoch+1`、worker lease、`revision+1`）。第二个worker只读
  `thinking`/终态，不加入执行；不存在同步与异步双重所有者。`_finish`以lease token围栏，
  旧owner的迟到结果不能覆盖新epoch。`thinking`轮次从不续跑：lease过期或重启时
  `recover_expired`收敛为`unknown_submission`并终止，不重放可能计费的文本调用。
- **Worker**：`app.workers.director`新增`execute_agent_turn`与游标扫描
  `dispatch_accepted_agent_turns`；`app/director/agent_worker.py`解析持久项目作用域后打开
  scoped checkpointer并调用服务。`recover_interrupted_director_turns`现在也恢复Agent轮次。
- **Schema**：0106只新增`app.pending_agent_director_turns`（含单轮作用域解析）并把Agent lease
  过期纳入`app.recoverable_director_turn_contexts`；无新表、无平行写路径。本地运行库仍0099。
- **HTTP**：`POST .../messages`新受理202、重放200；`GET .../requests`返回
  `AgentRequestState={acceptance,turn}`；`director.scoped_checkpointer`从API层移除。
- **测试迁移**：`test_director_agent_api.py`、`test_director_agent_service.py`、
  `test_director_agent_creative_context.py`、`test_director_agent_pg.py`、
  `test_director_agent_http_pg.py`（原7条同步断言整片改为"202→worker→轮询"，并新增断线恢复与
  受理身份用例）、`test_rls_scope_resolution.py`；新增`test_director_agent_acceptance.py`（8项）。
- **前端/E2E**：`generated.ts`由真实OpenAPI重生；`api.ts`改为受理+状态读取；
  `DirectorAgentPanel`按`state.turn`轮询；面板16项与`director-agent.spec.ts` 7项迁移通过。

验证：无过滤Full `df-quality-i2b01-full`，exit0，清理无残留（EV68）：静态门、ruff、mypy 362文件、
2609后端单测（370.18s）、迁移upgrade+check（head 20261118_0106）无漂移、196 PG集成（670.23s，
0跳过）、OpenAPI 304 schema权威、前端format/lint/UI权威/typecheck/build、89文件754 Vitest、
211 mock E2E、2媒体、1网关、35 LiteLLM、机构5浏览器用例（36.1s）。镜像backend
sha256:34913b5a832b…、frontend sha256:fe0cb611b010…。

I2b-01退出判定：受理/重放/冲突/领取/fencing/checkpoint边界/断线恢复/unknown_submission不重发
均有PG或单元证据，旧同步套件已整片迁移，故标记I2b-01完成。**未改变**：本地运行库仍0099、
未部署、未调用真实付费Provider、O1–O7与D8冻结基线不变；真实作品与目标机验收仍属I10。


## I6a-01实施（2026-11-18，EV69）

交付：
- **Schema（0107）**：`director_business_flow_instances/_steps/_step_attempts`三表，
  项目FORCE RLS、运行角色SELECT/INSERT/UPDATE（撤DELETE/TRUNCATE）、复合候选键/延迟FK、
  `(step_id)`部分唯一槽（活动状态或`unresolved_external`）、Turn→Attempt链接；
  NodeRun与`production_command_authorizations`补`(id,project_id)`候选键。降级在有数据时
  以`BUSINESS_FLOWS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE`拒绝。
- **定义注册**：`business_flows.py`的`BusinessFlowDefinition/Registry`（版本冻结、
  contract_hash、step依赖、完成规则、resume规则、LangGraph入口名），内置
  `shot_prompt_review@1`；未知定义/循环依赖/未知规则/未注册受控工具均拒绝。
- **服务**：`BusinessFlowService`提供`create_from_plan`（幂等）、`apply_dispositions`
  （retain/supersede/cancel，retain只接受定义+输入hash未变）、`ready_steps`/`advance`
  （依赖波次、会话外并发、顺序落回执）、`progress`/`completion`（只读原事实）、
  `cancel_run`（保留成功）。unknown_submission占用槽且不自动重发。
- **计划接线**：`MasterRunService.apply_plan`同事务处置旧实例+创建新实例；`verify`用注册
  完成规则返回satisfied/checks；`cancel`取消未完成流程；新增`summary`返回真实计数。
- **测试**：`tests/unit/test_business_flows.py`（10项）、`tests/integration/test_business_flows_pg.py`
  （4项：RLS/append-only/复合FK/槽位/retain/降级拒绝）；迁移后`alembic check`无漂移。
- **边界（不冒称）**：本批次不新增Worker驱动循环，`advance`由调用方驱动（I6b的Worker/授权
  受理端口）；Flow读投影HTTP仍属D7设计未实施；本地运行库仍0099。

验证：无过滤Full `df-quality-i6a01-full`，exit0，清理无残留（EV69）：静态门、ruff、mypy 364文件、
2619后端单测（453.67s）、迁移upgrade+check（head 20261118_0107）无漂移、200 PG集成（820.22s，
0跳过）、OpenAPI 304 schema权威、前端format/lint/UI权威/typecheck/build、89文件754 Vitest、
211 mock E2E、2媒体、1网关、35 LiteLLM、机构5浏览器用例（42.9s）。镜像backend
sha256:a66316ecda16…、frontend sha256:7af4f33e2ff5…。

I6a-01本切片退出判定：Flow/Step/Attempt持久化、定义注册、受控工具校验、计划处置/创建、完成规则与
取消语义均有单元与PG证据，**该切片**标记完成（EV69）。**未完成且不冒称**：批次合同中的
`runtime/inbox/wakeup` Worker驱动与生产执行适配（I6a-02）、Flow读投影HTTP、真实研究/知识/媒体
端口接线（I4/I6b）。本地运行库仍0099。


## I6a-02实施（2026-11-18，EV70）：Worker 驱动与受控工具执行

交付：
- **迁移0108**：`app.pending_business_flow_contexts(limit, after, instance_id)`窄作用域扫描
  （非终态且仍有pending/ready/running步骤，或按id解析单实例），SECURITY DEFINER归
  `dramaforge_worker_resolver`；无新表。
- **Worker**：`worker-director`新增`execute_business_flow`作业与`dispatch_business_flows`
  cron（10秒、游标、稳定job id）；实例行是唤醒权威，Redis丢失可由下次扫描恢复。
- **执行器**：`business_flow_worker.py`解析持久作用域→RLS→`advance`；`ToolFlowActionExecutor`
  只走既有`ToolExecutor`/`ToolRegistry`白名单；无Turn动作以attempt为审计身份，工具错误转为
  有界`FlowActionError`。
- **恢复**：`advance`前把`running`超过300秒的attempt以`FLOW_ATTEMPT_STALE`终止且不重放。
- **测试**：新增worker执行器映射、卡死attempt不重放、扫描候选3项单测；PG新增真实
  `dramaforge_app`角色经扫描函数→RLS→真实`project_get`→回执→实例succeeded用例。

验证：无过滤Full `df-quality-i6a02-full`，exit0，清理无残留（EV70）：静态门、ruff、mypy 365文件、
2622后端单测（371.22s）、迁移upgrade+check（head 20261118_0108）无漂移、201 PG集成（704.35s，
0跳过）、OpenAPI 304 schema权威、前端format/lint/UI权威/typecheck/build、89文件754 Vitest、
211 mock E2E（10.3m）、2媒体、1网关、35 LiteLLM、机构5浏览器用例（34.5s）。镜像backend
sha256:b81ee97d2016…、frontend sha256:dc31b4c3adc6…。

I6a-01批次退出判定：Flow/Step/Attempt持久化、定义注册、受控工具校验、计划处置/创建、
完成规则、取消语义、Worker驱动与卡死attempt不重放均有单元与PG证据（含真实app角色工具执行），
故标记I6a-01批次完成。**未完成且不冒称**：Flow/步骤读投影HTTP（D7设计）、生产/修复动作的
授权受理端口与真实研究/知识/媒体接线（I6b/I4）。本地运行库仍0099、未发布。



## I4前置切片：来源用途HTTP（2026-11-18，EV71）

按DATA_MODEL/API冻结值校正USE_PURPOSES（research/creation/library_reference/external_processing/export，修正此前实现自造的四值），SourceUseService增加find_subject、state=与expected_version CAS；新增pi/v1/source_use.py提供每原件修订与每Artifact的GET/PUT：artifact须属当前项目，GET无subject返回version0/unreviewed且零写入，PUT先按request_key回执再比较expected_version，declared要求非空声明与用途、revoked用途必须为空。generated.ts重生。

验证：无过滤Full df-quality-0c4737cfa987450db942f9c56713b9a2，exit0，清理无残留（EV71）：2624单测、201 PG集成、迁移check（0108）无漂移、304 schema、754 Vitest、211 mock E2E、媒体/网关/LiteLLM、机构5浏览器用例。镜像backend sha256:9f9bdc869883…。

未实施且不冒称：source-use-subjects/{s}/impact影响读取与跨项目授权计数；I4全格式处理器/研究工作流仍是下一批。本地运行库仍0099。



## I4前置切片：影响读取（2026-11-18，EV72）

GET /projects/{p}/source-use-subjects/{s}/impact：仅当前项目、按id游标分页，返回artifact/usage/status；status由API层读取Artifact，服务层不跨层import（修正架构门报出的ssets→execution新依赖）。未知subject 404。

验证：无过滤Full df-quality-975afff10b2c407a88031ddb313b4edb，exit0，清理无残留（EV72）：2626单测、201 PG集成、迁移check（0108）无漂移、304 schema、754 Vitest、211 mock E2E、媒体/网关/LiteLLM、机构5浏览器用例。镜像backend sha256:787275573515…。

未实施且不冒称：跨项目owner授权计数（other_project_uses_count）与跨项目只读资格；I4全格式处理器/研究工作流为下一批。本地运行库仍0099。



## I4-01 全格式处理器实施（2026-11-18，进行中）

续接上一轮未完成的 PDF 切片（PDF 处理器已写入但旧用例仍期待 `source_format_unsupported`，属未完成状态）。
本轮按“先一种代表格式走通真实入口→连续实现其余格式→集中跑对应测试组”的节奏推进，不回滚在途成果。

已实施（工作区，未提交）：
- **同域处理器**：`app/assets/source_processors/{contracts,native_text,docx,pdf,tables,images,ocr,asr,media,registry}.py`；
  `source_parser` 保留唯一门面 `parse_source`，片段级 `extraction_method`/`processor_ref` 贯穿到
  `source_fragments`、extraction 详情与 API。
- **七类格式真实处理器**：TXT/CSV/TSV（stdlib）；DOCX 正文/表格/**脚注/尾注/页眉/页脚**（悬挂引用拒绝，
  宏/内容控件/替代内容显式失败）；PDF Poppler 文本层＋扫描页 `pdftoppm`→Tesseract OCR（25 页/块、加密拒绝、
  OCR 页上限并如实记录遗漏）；XLSX openpyxl 只读（sheet/行列/合并格、公式与缓存区分、忽略声明 dimension）；
  图片 Pillow 解码/方向/40MP＋中文 OCR（无文字仍保留 visual_input 区域）；音频/视频 FFprobe/FFmpeg＋
  whisper.cpp 30 秒窗口转写、视频取样帧 OCR（coverage 如实标采样）。
- **能力与漂移**：`GET /projects/{p}/source-capabilities`（实际组件探测、格式/上限/限制、`profile_revision`
  配置hash，零解析零模型调用）；`SourceFragmentRead.limitations` 派生（machine_transcript/visual_input_only/
  low_ocr_confidence/page_ocr）；前端上传 accept、上限与缺组件提示改为读该接口。
- **块回执**：PDF 分块写 `projects/{p}/source-blocks/{content_hash}/{revision}/{attempt}/block-N.json`，
  内容 hash 校验后复用；重复投递不重算，新 attempt 不复用旧块；全部块完成才写不可变 Extraction。
- **资源边界**：上传仍 16 MiB；文本 2,000,000 字符/50,000 片段；图片 40MP；音视频当前 10 分钟档
  （30 秒窗口，目标 60 分钟待块级 ASR 回执）；PDF 500 页；Worker 本地解析超时 30s→900s（无外部调用）。
- **镜像/依赖**：backend 与 quality Dockerfile 增加 tesseract 5.3.0（chi_sim/chi_tra/eng）、poppler 22.12.0、
  whisper.cpp v1.9.5 静态构建（79s）与 `ggml-base.bin`（147,951,465 字节，构建期 SHA-256
  `60ed5bc3…ba2efe` 校验通过，官方源不可达时回退镜像但只接受同一 hash）；`uv` 0.12.0→0.13.3（lock revision 5）；
  pyproject 增加 openpyxl 3.1.5/defusedxml。

已测（本轮）：
- 首次无过滤Full `df-quality-i4-01-a` 在 frontend-quality 阶段失败：`prettier --check` 命中
  `src/lib/queryKeys.ts`（新增 capabilities key 的换行风格）；后端 2641 单测、201 PG 集成、media 9、
  gateway 1、institution 5 均已在同次运行通过，但整次 Full 不通过，故不计为批次证据。修复为
  `prettier --write`（仅格式），随后整轮重跑。
- 第二次无过滤Full `df-quality-i4-01-b`，exit0，清理无残留（0 容器）：
  静态门/架构门/Provider权威、ruff（app/tests/alembic + scripts）、mypy 379 文件、**2641 后端单测**
  （431.93s）、迁移 upgrade+check（head 20261118_0108）无漂移、**201 PG 集成**（851.66s，0 跳过）、
  OpenAPI **315 schema** 类型权威与 `api:check`、前端 prettier/lint/UI权威/typecheck/build、
  89 文件 **754 Vitest**、**211 mock E2E**（9.6m）、媒体资源 **9**、网关 **1**、LiteLLM **35**、
  机构真实栈 5 浏览器用例（55.5s）。镜像 backend
  `sha256:a6a29b717a026f364a07fbe4e740bd3183853205bb9aedf55b5dbb2368d2fb28`、frontend
  `sha256:e4c4446c7abe911b034a5cdaf7d4531aa609d87f2a243139fe92568c58c4eaa3`。
- 真实媒体组 `tests/media/test_source_processors.py` 7 passed（中文图片 OCR、扫描 PDF 页 OCR、英文 TTS
  音频 ASR 时间轴、静音不编造对白、视频取样帧+音轨、缺组件显式 unavailable、模型 hash 不匹配拒绝）；
  镜像构建内 whisper.cpp v1.9.5 静态编译 79s，`ggml-base.bin` 147,951,465 字节 SHA-256
  `60ed5bc3…ba2efe` 构建期校验 `OK`；tesseract 5.3.0（chi_sim/chi_tra/eng）、poppler 22.12.0、ffmpeg 5.1.9。

未完成且不冒称：reparse/事件 schema2 受理回执、`source_extract_v1` BusinessFlow（现有定义只有静态步骤，
动态块步骤需要先扩展定义/计划合同，不另造平行机制）、媒体块级 ASR 回执、I4-02 研究分析与 I4-03 知识、
流式上传放大处理档、真实中文 ASR 质量（espeak 合成音不可辨，仅用英文 TTS 证明链路；真实资料质量属 I10）。
本地运行库仍 0099，未部署，未调用真实付费 Provider。


## I4-01 续：受理冻结处理器合同与 retry/reparse（2026-11-18，EV75）

本切片把“解析合同漂移”和“用户显式重新处理”做成同一份持久受理事实，避免后台悄悄换处理器或重复解析。

已实施：
- **迁移0109**：`project_file_revisions.processor_profile_revision`(String64?)＋CHECK（NULL或64字符）；
  事件日志增加schema2部分唯一表达式索引`(project_id,aggregate_id,payload->>'request_key')`与
  `(…->>'accepted_attempt')`（仅PostgreSQL；Alembic不比较表达式索引，实际DDL在迁移中）。
- **受理**：上传事件改为schema2，冻结`action/request_key/request_hash/accepted_attempt/file_version/
  processor_profile_revision`；新增`ProjectFileService.accept_extraction`（retry|reparse）：
  同key同载荷回原`ExtractionAcceptance`、异载荷409 `SOURCE_REQUEST_KEY_REUSED`、profile漂移409
  `SOURCE_PROFILE_DRIFT`、文件版本/attempt/提取指针陈旧409 `SOURCE_STALE_ACCEPTANCE`、状态不符409
  `SOURCE_STATE_CONFLICT`；retry仅failed→pending、reparse仅parsed→pending，attempt+1并保留旧成功快照。
- **执行**：Worker在`extract`内校验冻结profile；NULL旧受理以`source_profile_legacy`失败、不等时以
  `source_profile_drift`失败，均不产生新Extraction，等待显式retry。
- **HTTP/前端**：`POST …/retry`与`POST …/reparse`改为202 `ExtractionAcceptance`；前端改用
  `acceptExtraction`，解析成功的资料出现「重新识别」，409时刷新能力并提示；generated.ts重生。

已测（本轮定向）：
- 后端unit（全量）2642 passed，唯一失败是`docs/DATA_MODEL.md`记录的head仍为0108；更新为0109并挂载
  current alembic/docs后该用例通过（完整镜像内由Full再验证）。
- `tests/unit/test_project_files.py`＋`test_project_files_api.py` 13 passed（回执/重放/异载荷/漂移/
  陈旧basis/状态冲突/reparse保留旧快照/legacy与drift失败）。
- PG `tests/integration/test_project_files_pg.py` 1 passed（31.54s，含0109升级与降级到0097）；
  隔离库`alembic upgrade head`＋`alembic check`：**No new upgrade operations detected**。
- 前端typecheck、prettier、lint/UI权威通过，754 Vitest通过；OpenAPI重生（含ExtractionAcceptanceRead）。
- **无过滤Full `df-quality-i4-01-d`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 379 文件、**2643 后端单测**（436.74s）、迁移 upgrade+check（head 20261118_0109）无漂移、
  **201 PG 集成**（743.31s，0 跳过，含0109升级与降级）、OpenAPI 315 schema 与`api:check`、
  前端prettier/lint/UI权威/typecheck/build、89文件754 Vitest、211 mock E2E、媒体资源9、网关1、
  LiteLLM 35、机构真实栈5浏览器用例（37.7s）。镜像 backend
  `sha256:8bd84faa5d3898f9ed0c7846a99a5d01d7ff21047cb960c468610f9cf8ef3434`、frontend
  `sha256:90b5ba1a505d7092b3ec79628efa82f5a2fd4c8dedc402797ac300f76524c210`。

未完成且不冒称：`source_extract_v1` BusinessFlow（动态块步骤）、媒体块级ASR回执、I4-02/03；
本地运行库仍0099，未部署，未调用真实付费Provider。


## I4-02a 研究结果、用户决定与引文（2026-11-18，EV76）

本切片先把“研究结果是什么、谁能改、引文是否真实”做成可验收的数据与API事实；模型分析执行（固定
`research_import_v1` Flow/Invocation/六类覆盖）仍是下一步，不把用户录入当模型分析。

已实施：
- **迁移0110**：`research_results`/`research_result_revisions`/`research_citations`三表，复合候选键、
  延迟FK（结果→current修订、base/restores/accepts自引用、引文→片段）、origin/verification/应用版本CHECK、
  `origin='model'`才允许invocation+output_item_key的部分唯一索引；`app.research_result_current_guard()`
  要求指针指向同结果已应用修订、版本恰+1、base等于原current，仅元数据归档允许版本不变或+1；
  项目RLS + 运行角色对revisions/citations仅SELECT/INSERT；`director_invocations`补`(id,project_id)`候选键。
- **领域**：`app/assets/research_bodies.py`六类判别body（schema_version=1，多余字段拒绝）与claim词表；
  `app/assets/research.py`提供创建/修正/采纳候选/恢复/归档、request_key回执与request_hash冲突、
  `expected_version`+`base_revision_id` CAS、引文逐字与locator范围校验、列表kind/q/archived/view过滤。
- **HTTP**：9个端点（列表/创建/读取/修订列表/修订详情/追加修订/采纳/恢复/归档），错误码
  `RESEARCH_REQUEST_KEY_REUSED`/`RESEARCH_STALE_VERSION`/`RESEARCH_STALE_BASE`/
  `RESEARCH_RESULT_ARCHIVED`/`RESEARCH_CANDIDATE_ALREADY_APPLIED`；generated.ts重生。

已测（定向）：
- 单元`test_research_results.py` 11 passed（六类形状/多余字段、回执重放与异载荷冲突、CAS与base冲突、
  accept/restore新增修订不改历史、归档幂等并阻断新修订、引文逐字/locator范围/未知片段、列表过滤）。
- API `test_research_api.py` 1 passed（真实上传+解析取得片段后走完整HTTP生命周期与409/422码）。
- PG `test_research_results_pg.py` 1 passed（10.22s）：RLS跨项目隔离与WITH CHECK、修订表UPDATE被拒、
  指针指向未应用修订/版本跳跃被触发器拒绝、并发修正单胜者、中文`q`匹配。
- 隔离库`alembic upgrade head`（0110）与`alembic check`：No new upgrade operations detected；
  0109→0110降级/升级往返通过。
- 全量unit 2655 passed；前端typecheck/prettier/lint/UI权威通过，OpenAPI重生。
- **首次Full `df-quality-i4-02-a`**：backend-quality通过（2655单测、202 PG集成、迁移check无漂移），
  frontend-quality在`EditingWorkspace.test.tsx`的“saves chosen audio Artifacts…”上触发15s默认超时
  （该用例在重载主机单跑约30s，属环境超时而非断言失败，且本轮改动不涉及剪辑UI）；为该单一重负载用例
  显式设置60s上限（不改变任何断言），并停止本地运行栈释放内存（容器停止、数据卷保留，未升级/未部署），
  随后整轮重跑。首次运行不计为批次证据。
- **第二次Full `df-quality-i4-02-b`**：backend-quality通过（2655单测1024s、202 PG集成1880s、迁移check无漂移、
  OpenAPI导出）；frontend-quality的vitest 89文件754、typecheck/build、api权威329 schema与209个mock E2E通过，
  但`workbench-resource`两个延迟预算用例失败（p95 326/421ms，预算≤200ms；firstScreen 3.5–7.9s）。
  聚焦复跑同一镜像：1-shot用例82.7ms通过，30/100-shot仍326/421ms。根因判定为**主机容量/CPU争用**
  （本轮改动仅新增生成类型与后端，未触及workbench渲染路径；同用例在EV74/EV75的Full中通过），
  不以放宽200ms预算或删除用例处理；待主机容量恢复后重跑完整Full，当前不计为Full通过。
  另：为释放内存已停止本地运行栈容器（数据卷保留，未升级/未部署）。

未完成且不冒称：analysis-preview/analyses受理与模型执行、六类覆盖清单、research search_text生成列与
GIN索引（随I4-03检索切片）、I4-03知识库；完整Full待容量恢复后重跑；本地运行库仍0099。


## I4-02b-1 分析预览（2026-11-19，EV77）

先落“用户可预览、零模型调用、零写入”的输入冻结与阻断原因；分析受理/执行（固定Flow+Invocation+覆盖清单）
仍下一步。

已实施：
- `app/assets/research_analysis.py`：`ResearchAnalysisService.preview`校验当前原件修订/文件版本/提取指针，
  校验类别集（去重、六类）、目标结果（同项目、kind在类别集、base等于current），汇总
  `source_use`（research+external_processing交集）与`egress`（research_text用途、external位置）决定，
  计算`preview_fingerprint`（提取内容hash/片段数/处理器profile/类别集/目标结果/模型身份/source-use/
  egress/`max_model_calls=1`）与`expires_at`（15分钟）。
- HTTP `POST /projects/{p}/file-revisions/{r}/analysis-preview`；模型身份由API层只读解析
  （`resolve_agent_text_model`），缺失时作为`text_model_unavailable` blocker而非500。
- 错误码：`RESEARCH_PREVIEW_STALE`、`RESEARCH_TARGET_UNKNOWN`、`RESEARCH_TARGET_KIND_MISMATCH`、
  `RESEARCH_TARGET_STALE`、`RESEARCH_CATEGORY_DUPLICATE`、`RESEARCH_CATEGORY_UNKNOWN`。

已测（定向）：
- 单元`test_research_analysis.py` 5 passed：未声明来源→`source_use_blocked`；声明
  research+external_processing后blockers清空且egress允许；同输入指纹稳定、类别集/模型身份变化则指纹变化；
  文件版本过期422、提取指针不匹配为blocker；目标未知/kind不匹配/类别重复分别拒绝；
  预览前后`DirectorInvocation`计数均为0（零模型调用）。
- API`test_research_api.py` 2 passed：预览返回blockers/`max_model_calls=1`/缺失类别，重复预览指纹稳定，
  无Invocation行，过期版本422 `RESEARCH_PREVIEW_STALE`。
- 全量unit 2661 passed（1127s）；前端754 Vitest（920s，重载主机）、typecheck/prettier/lint/UI权威通过；
  `generated.ts`已重生（含预览schema）。

未完成且不冒称：analysis受理（202 ResearchAcceptance）/执行、六类覆盖清单与analysis读投影、
search_text生成列与I4-03知识库；完整Full待容量恢复重跑；本地运行库仍0099。


## I4-02b-2 分析清单、发布与读投影（2026-11-19，EV78）

把“一次分析完成后到底发布了什么”做成不可变清单：六类覆盖、结果修订链接、调用证据与当前分析指针。

已实施：
- **迁移0111**：`research_analyses`（coverage/category_outcomes/manifest_hash/request_key+hash）、
  `research_analysis_invocations`（PK(analysis,invocation)、ordinal唯一）、
  `research_analysis_results`（PK(analysis,revision)、category+ordinal唯一、六类CHECK）；
  `project_file_revisions.current_analysis_id`＋延迟复合FK；三表项目RLS且仅SELECT/INSERT。
- **发布服务**（`app/assets/research_analysis.py`）：先校验六类outcome（恰六类、findings计数一致、
  none无输出、incomplete必须有原因）与全部引文（同提取、逐字、claim、locator范围），**再**写清单/
  结果修订/引用/链接，失败不留部分修订；`origin=model`修订对新结果是首次生效（applied=2、current），
  对目标结果是候选（applied NULL、current不变）；`manifest_hash`冻结输入、outcome、finding body hash、
  引文与invocation；同request_key+hash回原清单、异载荷409 `RESEARCH_ANALYSIS_KEY_REUSED`；
  提取已变化409 `RESEARCH_ANALYSIS_SOURCE_CHANGED`。
- **HTTP读投影**：`GET …/file-revisions/{r}/analyses`、`GET …/analyses/{a}`（含最多100条结果与
  current|candidate处置）、`GET …/analyses/{a}/results`（分页）；generated.ts重生（337 schema）。

已测（定向）：
- 单元`test_research_analysis_publication.py` 7 passed：清单/结果/指针、候选不改current、重放与异载荷、
  四类outcome非法组合、伪引文/未知片段拒绝；`test_research_analysis.py` 5 passed。
- API`test_research_api.py` 3 passed（新增读投影：列表/详情/results分页/跨项目404）。
- PG`test_research_analysis_pg.py` 1 passed（11.23s）：项目RLS可见性、分析表UPDATE被拒、
  延迟FK强制立即检查后跨修订指针被拒、合法指针提交可读。
- 隔离库0111升级＋`alembic check`无漂移、0110↔0111升降级往返通过。
- **无过滤Full `df-quality-i4-02-c`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 385 文件、**2669 后端单测**（384.47s）、迁移 upgrade+check（head 20261118_0111）无漂移、
  **203 PG 集成**（694.52s，0 跳过）、OpenAPI 337 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、89文件754 Vitest、**211 mock E2E**（8.4m，含此前受主机争用影响的resource延迟用例）、
  媒体资源9、网关1、LiteLLM 35、机构真实栈5浏览器用例（35.5s）。镜像 backend
  `sha256:1b2ec408a955b55c057e2b08bb8493954049dca1e8d23c63da158ac660920759`、frontend
  `sha256:0980ca115503bd2b3a79cbbb7e3dd84af7eefd6a77e039d848494495c57ff014`。
  该Full同时补齐了EV76中因主机容量未通过的resource用例（本轮主机空闲时p95 22/82.7/87.2ms，预算200ms），
  确认此前失败为环境争用而非代码回归。

未完成且不冒称：analysis受理（202）与真实模型执行（固定Flow/Invocation、六类输出提示与解析）、
search_text与I4-03知识库；本地运行库仍0099。


## I4-02c 分析受理（202，冻结Turn）（2026-11-19，EV79）

把“用户接受这份预览”变成唯一持久事实：一个`scope_type=research_analysis`的queued Director Turn，
冻结输入身份；受理零模型调用，执行仍由既有文本端口在后续切片接入。

已实施：
- `app/director/research_import.py`：`ResearchRequest`/`build_request_payload`把extraction、类别集、
  目标结果、模型身份、preview指纹与片段ID（最多200条、每条截断2000字符）冻结进Turn的
  `input_versions`/`intent_snapshot`；`context_snapshot`用`DirectorContextBuilder`生成，保证未来执行
  调用`generate_structured`时上下文hash一致；`accept`经`DirectorTurnService.create_or_get`创建/复用Turn
  （同key同上下文回原Turn、异上下文拒绝），不调用模型。
- HTTP `POST …/analyses`：重算完整preview→指纹不符409 `RESEARCH_PREVIEW_DRIFT`；blockers非空409
  `RESEARCH_BLOCKED`（details.blockers）；通过则202 `ResearchAcceptance`（master_run_id/flow_instance_id
  为null，turn_id/accepted_revision/read_url）；generated.ts重生。

已测（定向）：
- 单元`test_research_import.py` 3 passed：accept创建queued Turn（scope/状态/冻结的类别与片段ID）、
  同key重放同Turn、异指纹拒绝；HTTP受理创建Turn且重放同id、指纹漂移409 `RESEARCH_PREVIEW_DRIFT`、
  有blockers时409 `RESEARCH_BLOCKED`且不建Turn。
- 全量unit **2672 passed**（526.58s）；前端754 Vitest（292.85s）与typecheck/prettier通过；
  generated.ts重生（含受理schema）。架构门新增一条已审阅依赖边
  `app.director.research_import -> app.providers.model_profiles.slots`（与既有director模块同一reason，
  非重建baseline），`arch_import_scan --check`通过。

未完成且不冒称：真实模型执行（固定`research_import_v1`、Invocation、六类输出提示/解析与coverage发布接线）、
search_text与I4-03知识库；本地运行库仍0099。


## I4-02d 分析执行引擎与Worker（2026-11-19，EV80）

把受理的Turn真正跑完：claim→既有文本端口一次结构化调用→六类输出校验→发布清单，失败只记有界失败回执、
不自动重试。

已实施：
- `app/director/research_import.py`新增`execute`：从Turn冻结输入重建同一payload，调用
  `DirectorTextRuntimeAdapter.generate_structured`（task=`research_import_v1`、slot=planning.script、
  系统提示声明资料为不可信数据、只允许提供的片段ID与逐字引文），把模型输出映射为
  `FindingInput`/`CategoryOutcome`（目标结果base来自冻结targets、引文file_revision来自本次提供的片段），
  计算coverage（片段总数/处理数/预算遗漏），用本次Invocation调用`ResearchAnalysisService.publish`；
  输出缺类别、引用未提供片段等直接失败，不伪造完成。
- **迁移0112**：`app.pending_research_analysis_turns`窄作用域扫描（只返回`scope_type='research_analysis'
  且status=queued`，或按id解析），SECURITY DEFINER归`dramaforge_worker_resolver`，无新表。
- `app/director/research_worker.py`：解析scope→RLS→claim（queued→thinking）→execute→commit；
  异常回滚后以`analysis_failed`标记Turn失败（仅错误类型，不重试、不覆盖证据）。
- `worker-director`新增`execute_research_analysis`作业与10秒游标扫描`dispatch_research_analyses`；
  Turn行是唤醒权威，Redis丢job可由下次扫描恢复。

已测（定向）：
- 单元`test_research_import_execution.py` 1 passed：冻结Turn→（fake transport）六类输出→发布；
  两个新结果均current、`current_analysis_id`前移、coverage complete、类别计数正确。
- PG`test_research_analysis_pg.py` 3 passed（新增扫描用例：queued研究Turn被返回、claim后不再返回、
  按id仍可解析、agent Turn不混入）；迁移0112升级+`alembic check`无漂移、0111↔0112升降级往返。
- 全量unit 2673 passed（537.29s）；ruff/mypy通过。
- **无过滤Full `df-quality-i4-02-d`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 387 文件、**2673 后端单测**（389.59s）、迁移 upgrade+check（head 20261118_0112）无漂移、
  **204 PG 集成**（705.40s，0 跳过）、OpenAPI 339 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、89文件754 Vitest、**211 mock E2E**（8.5m）、媒体资源9、网关1、LiteLLM 35、
  机构真实栈5浏览器用例（34.9s，worker-director带新cron正常启动）。镜像 backend
  `sha256:fe5c5d5bb69fe7572e26c308841da51ef1ac09ede77f1656100e35c1ff16cd32`、frontend
  `sha256:a4572bd93adf91018efc814f5d949d44a7de695bdf40b0389a4f60a2b1ca141a`。

未完成且不冒称：真实Provider调用的端到端证据（本批只以fake transport验证引擎与发布接线）、
search_text与I4-03知识库；本地运行库仍0099。


## I4-03a 独立知识库、发布/撤回与检索投影（2026-11-19，EV81）

把“知识是用户显式发布的内容快照”做成可验收的数据/服务/API；私有溯源只在原项目可读，检索用
确定性投影而非第二可编辑正文。

已实施：
- **迁移0113**：`knowledge_entries`/`knowledge_revisions`/`knowledge_source_links`/
  `project_knowledge_references`四表；entry→current延迟复合FK、`app.knowledge_entry_guard()`校验
  指针/版本/状态/withdrawn_at一致；`app.research_search_text_v1`/`app.knowledge_search_text_v1`
  IMMUTABLE函数与BEFORE INSERT触发器维护`search_text`（可移植测试库无法编译PG生成列，故同一派生投影用
  触发器写入，应用不直接写该列），PG建立`gin_trgm_ops`索引；owner RLS（entries/revisions）与项目RLS
  （source_links/references），revisions/source_links仅SELECT/INSERT。
- **服务**（`app/assets/knowledge.py`）：创建草稿/发布、追加修订、撤回（复制当前内容为不可变withdraw修订
  并写withdrawn_at）、owner跨Workspace列表（kind/status/q）、request_key回执与异载荷冲突、
  expected_version CAS、published上save_draft 409；`source_links`只接受同owner源项目的research revision
  （异owner 422），仅经原项目`source_links()`读取。
- **HTTP**：`POST/GET /knowledge/entries`、`GET /knowledge/entries/{e}`、
  `GET/POST /knowledge/entries/{e}/revisions`、`POST /knowledge/entries/{e}/withdraw`；generated.ts重生
  （349 schema）。

已测（定向）：
- 单元`test_knowledge.py` 3 passed（草稿→发布→撤回全链、回执重放/异载荷、published上save_draft拒绝、
  陈旧版本、私有source_links仅原项目可读、未知用途/非法URL/异owner来源拒绝）。
- API`test_knowledge_api.py` 1 passed（HTTP全链、status过滤、撤回重放同revision、陈旧版本409）。
- 隔离库0113升级+`alembic check`无漂移、0112↔0113升降级往返；全量unit 2677 passed（588.62s）；
  前端754 Vitest（293.65s）、typecheck/prettier/lint/UI权威通过。
- **无过滤Full `df-quality-i4-03-a`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 390 文件、**2677 后端单测**（397.26s）、迁移 upgrade+check（head 20261118_0113）无漂移、
  **204 PG 集成**（717.98s，0 跳过）、OpenAPI 349 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、89文件754 Vitest、**211 mock E2E**（8.4m）、媒体资源9、网关1、LiteLLM 35、
  机构真实栈5浏览器用例（38.6s）。镜像 backend
  `sha256:cb97c9823764f23b305f308162958417f9cc316a2431d56d48544cfe9c77aff6`、frontend
  `sha256:60d0d2fc644d2f6723afba6d51c73f16ead867ecb75b3fe03ded7280498ec192`。

未完成且不冒称：项目固定引用`/projects/{p}/knowledge-references`（GET/POST/PATCH）、真实Provider分析端到端、
I4阶段完整验收；本地运行库仍0099。


## I4-03b 项目固定知识引用（2026-11-19，EV82）

把“项目引用已发布知识”做成固定revision+用途的显式决定，并给出读取投影而非第二状态。

已实施：
- `app/assets/knowledge_references.py`：`create`（自然键 project+revision+use 去重；已detach同键返回
  detached引用不自动重连；未发布/用途不允许409）、`list`（active过滤、availability由Entry当前状态与
  current修订用途投影为published/restricted/withdrawn/unavailable）、`patch`（expected_version CAS
  detach/reattach，重连重验发布状态与用途）。
- HTTP：`GET/POST /projects/{p}/knowledge-references`、`PATCH …/{ref}`；新建201、同自然键重放200；
  generated.ts重生（353 schema）。
- 引用固定revision，后续发布不移动已有引用；私有source_links不进入引用读响应。

已测（定向）：
- 单元`test_knowledge_references.py` 2 passed（pin/重放/ detached同键不自动重连/重连/陈旧版本/
  新发布收窄用途→restricted/草稿与撤回拒绝/未知entry 404）。
- API`test_knowledge_api.py` 2 passed（引用201/200重放、active过滤、detach/reattach、草稿409）。
- 全量unit **2680 passed**（603.59s）；前端754 Vitest（298.70s）、typecheck/prettier/lint/UI权威通过。
- **无过滤Full `df-quality-i4-03-b`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 391 文件、**2680 后端单测**（397.34s）、迁移 upgrade+check（head 20261118_0113）无漂移、
  **204 PG 集成**（721.30s，0 跳过）、OpenAPI 353 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、89文件754 Vitest、**211 mock E2E**（8.5m）、媒体资源9、网关1、LiteLLM 35、
  机构真实栈5浏览器用例（33.8s）。镜像 backend
  `sha256:c00b1567b7472c514bae5e4d23ec6f389bc19854393663c9915d9a0140720f77`、frontend
  `sha256:c3132197af96658d4423706e853c084b852a02f0073fa7af4324f09d830e4ed1`。

未完成且不冒称：真实Provider分析端到端（需当前Owner授权，属外部边界）、研究/知识前端页面（计划归I4-03前端切片）、
I4阶段完整验收；本地运行库仍0099。


## I4-03c 研究/知识前端首版（2026-11-19，EV83）

把I4-02/I4-03的API接进工作台：研究浏览/修正/分析预览与受理，以及独立知识库的草稿/发布/撤回。

已实施：
- 项目二级导航新增「文化研究」（`/projects/{id}/research`，WORKSPACE_VIEWS/标签/壳类型同步）：
  六类筛选、列表与详情（当前修订正文、逐字引用、来源可用性）、保存用户修正为新版本、历史版本；
  资料选择→`分析预览`（指纹/模型/最大调用/缺失类别/阻断项）→无阻断才可`确认分析`（202 Turn身份，
  409提示重新预览）。
- 全局一级导航新增「文化知识库」（`/knowledge`）：状态/类别筛选、详情与历史版本、创建草稿/直接发布、
  撤回已发布知识；写操作带CSRF、错误按API码呈现。
- `features/research/api.ts`统一研究/知识客户端；queryKeys新增research/knowledge命名空间；
  路由树登记两条新路由。

已测（定向）：
- 新增`tests/unit/ResearchPanel.test.tsx` 3 passed：研究列表+当前修订正文渲染、无已解析资料时
  `分析预览`禁用；知识列表/状态渲染、标题与内容未填时`保存草稿`禁用、填写后启用。
- 前端全量**757 Vitest**（90文件）、typecheck/prettier/eslint/ui权威（115 TSX surfaces）通过；
  后端本轮无改动，未重复跑后端套件。
- Full `df-quality-i4-03-c`首跑**FAIL**：后端全绿（2680 unit/204 PG/迁移check），前端E2E两条导航计数断言仍按旧导航（一级2、创作导航7）失败；根因是新增一级「文化知识库」与二级「文化研究」，非产品缺陷。已把断言更新为一级3、创作导航8并插入「文化研究」文本序列；重建frontend-quality镜像后定向复跑两文件 **40 passed**（1.6m）。复跑完整Full见下条。
- **无过滤Full `df-quality-i4-03-c2`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 391 文件、**2680 后端单测**（400.60s）、迁移 upgrade+check（head 20261118_0113）无漂移、
  **204 PG 集成**（718.61s，0 跳过）、OpenAPI 353 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、90文件**757 Vitest**、**211 mock E2E**（8.5m，含更新后的导航计数）、媒体资源9、
  网关1、LiteLLM 35、机构真实栈5浏览器用例（35.4s）。镜像 backend
  `sha256:1c28875f578c14c2bbdacb42b43d396aa6474eaf55d9090eb9e7fa4635d6a570`、frontend
  `sha256:008aa61a6cb5730054011ac7ac6cd2d8bbb4e361c7a335c1b2755a5612d6676f`。

未完成且不冒称：右侧Director解释/补充、恢复候选的完整对照、知识发布共享范围预览、真实Provider
分析端到端；I4阶段完整验收待Full回填。


## I4-03d 研究/知识领域事件与Outbox（2026-11-19，EV84）

补齐I4-03计划中的events/outbox/SSE接线：每次研究/知识决定与业务写入同事务产生一条安全事件。

已实施：
- `app/assets/domain_events.py`：`emit`统一写EventLog+OutboxEvent（topic=event_type）。
- 研究：`research.result.created|revised|accepted|restored|archived`、`research.analysis.published`
  （project范围，经既有outbox→SSE桥接）。
- 知识：`knowledge.entry.drafted|published|withdrawn`（owner范围、project_id为空、不广播到项目流）、
  `knowledge.reference.attached|detached`（project范围）。
- payload只含稳定身份/版本/哈希；不含片段正文、对象键、凭据或私有来源。

已测（定向）：
- 新增`test_domain_events.py` 1 passed：六类事件按序写入、payload无私有字段、研究事件带project、
  知识事件project为空且状态正确。
- 定向研究/知识套件30 passed；全量unit **2681 passed**（550.67s）；ruff/mypy通过。

未完成且不冒称：知识事件的SSE通道（owner范围暂无项目流）、真实Provider分析端到端。
- **无过滤Full `df-quality-i4-03-d`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 392 文件、**2681 后端单测**（399.41s）、迁移 upgrade+check（head 20261118_0113）无漂移、
  **204 PG 集成**（723.42s，0 跳过）、OpenAPI 353 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、90文件**757 Vitest**、**211 mock E2E**（8.5m）、媒体资源9、网关1、LiteLLM 35、
  机构真实栈5浏览器用例（36.4s）。镜像 backend
  `sha256:ec55e3bf5ab3a0d1102ba15ab3223f45a386771ee523c323b23ad0e6c00d86c8`、frontend
  `sha256:fafe627c74a66dac56facb4e304d693c4729e178bfcd9a17989df355abd50086`。


## I4 阶段退出结论（2026-11-19，EV80–EV84）

已交付并各有Full证据：七格式解析/块回执/来源接受（I4-01）、研究结果/修订/引文与候选/恢复/归档、
分析预览（零模型调用）/202受理（冻结Turn）/执行引擎/Worker扫描/清单发布（I4-02）、独立知识条目/
修订/发布/撤回、固定引用与availability投影、research/knowledge检索投影与pg_trgm、领域事件与outbox
（I4-03）、研究/知识前端首版与导航。隔离库RLS/追加只读/延迟FK/迁移升降级均有PG证据；无过滤Full
`df-quality-i4-03-a/b/c2/d`连续通过，失败仅来自导航计数断言并已修复复跑。

**外部边界（不冒称完成）**：真实付费Provider的端到端分析调用需当前Owner按合同授权，属I10真实操作门；
本轮以fake transport + 真实PostgreSQL/Worker/HTTP链路证明机制。**未完成UI细节**：右侧Director对研究的
解释/补充、恢复候选的完整对照视图、知识发布共享范围预览；这些不改变已验收的数据/服务/HTTP合同，
记入后续切片。I4按机制验收退出，允许进入I5。


## I5-01a 公共资产库与项目固定链接（2026-11-19，EV85）

进入I5：先落公共资产的持久事实（发布/成员/项目链接）与读取/撤回/重连，不接私有源表。

已实施：
- **迁移0114**：`public_asset_publications`/`public_asset_publication_items`/
  `project_public_asset_links`三表；`asset_versions`新增`base_publication_id`/
  `base_public_asset_link_id`（同空/同非空CHECK+延迟组合FK到链接）、`uq_asset_version_scope`、
  `asset_version_references`补`uq_asset_version_reference_scope`；publications/items按owner RLS、
  links按项目RLS，items仅SELECT/INSERT。
- **服务**（`app/assets/public_assets.py`）：`publish`（仅formal版本、至少一个真实媒体引用、
  PublicDisplay校验与publication_hash冻结、items来自AssetVersionReference）、`read/list`
  （owner跨Workspace、q/kind/status）、`set_withdrawn`（revision CAS撤回/恢复，恢复重验源formal）、
  `ProjectPublicAssetLinkService.create/list/patch`（固定publication、request_key回执、
  自然键唯一、CAS label/detach/reattach并重验资格）。
- **HTTP**：`GET /public-assets`、`GET /public-assets/{pub}`、`GET …/items`、`PATCH /public-assets/{pub}`、
  `GET/POST /projects/{p}/public-asset-links`、`PATCH …/{link}`；generated.ts重生（362 schema）。
- 事件：`public_asset.publication.created|withdrawn|restored`、`public_asset.link.attached|updated`。

已测（定向）：
- 单元`test_public_assets.py` 2 passed：发布/重放、跨Workspace列表、撤回与陈旧revision、撤回后拒绝新链接、
  恢复后建链接/同key重放/异key自然键409、detach/reattach；HTTP列表/详情/items、链接201/200、撤回。
- 隔离库0114升级+`alembic check`无漂移、0113↔0114升降级往返；全量unit **2682 passed**（609.33s）；
  前端757 Vitest（300.35s）、typecheck/prettier/api:authority（362 schema）通过；架构门新增已审阅依赖边
  `app.assets.public_assets -> app.execution.models`（同from_artifact_service reason，非重建baseline）。

未完成且不冒称：from-artifact/promote/version-create的采用回执与公共发布同事务、owner_preview/project_use
内容流、参考绑定判别联合、Provider下载token（I5-01b/I5-02）；I5阶段Full待阶段终点。


## I5-01b 公共内容窄读（owner_preview）（2026-11-19，EV86）

让公共资产可被owner预览真实内容，同时不开放私有源表或存储URL。

已实施：
- `PublicAssetService.read_content`：owner+publication+item窄读；publication不可用/源版本非formal/
  artifact非available统一404；只返回object_key/mime/size/hash给API层，不序列化。
- `GET/HEAD /public-assets/{pub}/items/{item}/content`：`Accept-Ranges: bytes`、
  `X-Content-Type-Options: nosniff`、`Cache-Control: private, no-store`；单Range合法206+`Content-Range`，
  多Range/非法416，HEAD只读元数据不加载文件；失效统一404不泄露原因。
- 采用回执与project_use流仍未实施（下一片）。

已测（定向）：
- `test_public_assets.py` 3 passed：新增内容用例覆盖200全文、HEAD Content-Length、`bytes=2-5`→206与
  Content-Range、多Range→416、撤回后404。
- 全量unit **2684 passed**（605.32s）；前端757 Vitest、typecheck/prettier/api:authority通过；ruff/mypy 395文件通过。

未完成且不冒称：采用回执同事务、project_use内容流、参考绑定判别联合、Provider下载token（I5-02）；
I5阶段Full待阶段终点。


## I5-01c from-artifact采用回执与公共发布同事务（2026-11-19，EV87）

把“生成物成为资产”的采用决定变成固定回执，并允许同一事务内发布公共版本。

已实施：
- `AssetFromArtifactService.create_with_receipt`：复用原创建链，返回
  `AssetAdoptionReceipt={asset_id,asset_version_id,accepted_asset_revision,publication_id}`；
  提供`PublicDisplay`时在同一事务调用`PublicAssetService.publish`（仅formal、至少一个真实引用），
  私有/手工版本publication_id为null；同key同hash重放回原回执、异载荷仍409。
- HTTP `POST /projects/{p}/assets/from-artifact`：请求新增可选`public_display`，响应改为
  `AssetAdoptionReceiptRead`，新建201/重放200。
- 前端`createAssetFromArtifact`改为回执类型并支持`publicDisplay`；`AddArtifactToAssetDialog`用回执
  `asset_id`绑定、显示采用revision，`onCreated`同时给出显示名；`ShotCandidateTray`反馈改用显示名。

已测（定向）：
- 新增`test_asset_adoption_receipt.py` 2 passed：带display发布（publication_id非空、safe_name/媒体项正确）、
  同key重放同回执、无display时publication_id为空且公共库为空。
- 前端`AddArtifactToAssetDialog.test.tsx` 11 passed（回执mock、绑定用asset_id、显示采用revision）。
- 全量unit **2686 passed**（605.75s）；前端757 Vitest、typecheck/prettier/api:authority（362 schema）通过。

未完成且不冒称：promote/version-create/asset-create回执与目标CAS、project_use内容流、参考绑定判别联合、
Provider下载token（I5-02）；I5阶段Full待阶段终点。


## I5-02a 公共链接镜头引用（2026-11-19，EV88）

让公共资产成为可被镜头显式引用的生产输入，同时保持私有分支与源隔离。

已实施：
- **迁移0115**：`shot_reference_bindings`新增`public_asset_link_id`/`publication_item_id`与单源CHECK、
  公共链接组合FK（project一致）、`resolution_mode`新增`public_link`；links补`uq_public_link_project_scope`。
- `POST /projects/{p}/shots/{s}/references`新增`source:"public"`判别：校验链接属于当前项目、未detach、
  publication可用、item属于publication；与私有字段同现422 `REFERENCE_SOURCE_AMBIGUOUS`、缺公共字段422
  `REFERENCE_PUBLIC_SOURCE_REQUIRED`；写入`resolution_mode=public_link`，不写asset/artifact。
- `POST …/references/resolve`公共分支实时重验链接/publication/源版本formal/artifact，返回
  `source:"public_link"`与真实mime/hash；失效返回空（不泄露原因）。
- `BindingRead`返回公共两列；generated.ts重生（364 schema）。

已测（定向）：
- 新增`test_public_reference_binding.py` 1 passed：公共绑定201、两列与`public_link`模式、resolve返回
  public_link引用；私有字段同现422、缺字段422。
- 隔离库0115升级+`alembic check`无漂移、0114↔0115升降级往返。
- 全量unit **2687 passed**（607.18s）；前端757 Vitest、typecheck/prettier/api:authority（364 schema）通过。

未完成且不冒称：project_use内容流、Provider下载token六列身份、promote/version-create回执与目标CAS
（I5-02剩余）；I5阶段Full待阶段终点。


## I5-02b promote采用回执与目标CAS（2026-11-19，EV89）

把“候选转正式”从隐式切换改为可重放的采用决定。

已实施：
- **迁移0116**：`asset_versions`新增`adoption_request_key/hash/adopted_asset_revision`（全空/全非空CHECK、
  项目内request_key部分唯一索引）。
- `AssetVersionService.promote_with_receipt`：同key同hash回原回执（created False）、同版本异key
  409 `ASSET_VERSION_ALREADY_ADOPTED`（details含原identity）、`expected_asset_version` CAS陈旧
  409 `ASSET_STALE_VERSION`、非候选422；采用时Asset.version+1并写adoption三列；可选`public_display`
  同事务发布。
- HTTP promote请求改为`{request_key,expected_asset_version,public_display?}`，201/重放200返回
  `AssetAdoptionReceipt`；generated.ts重生（365 schema）。

已测（定向）：
- `test_asset_version_promotion.py` 4 passed：创建→采用201（receipt字段/版本+1）、同key重放200同回执、
  异key 409、陈旧expected 409、rejected候选422、单formal历史保留、跨项目隔离。
- 隔离库0116升级+`alembic check`无漂移、0115↔0116升降级往返。
- 全量unit **2688 passed**（608.07s）；前端757 Vitest、typecheck/prettier/api:authority（365 schema）通过。

未完成且不冒称：version-create候选回执与`base_public_asset_link_id`、project_use内容流、Provider下载
token六列身份（I5-02剩余）；I5阶段Full待阶段终点。


## I5-02c 候选版本回执与公共base链接（2026-11-19，EV90）

把“新建候选版本”也变成可重放的CAS决定，并允许元数据变体固定公共来源链接。

已实施：
- **迁移0117**：`asset_versions`新增`creation_request_key/hash`（全空/全非空CHECK、项目内部分唯一索引）。
- `AssetVersionService.create_candidate_with_receipt`：同key同hash回原`CandidateReceipt`、异载荷409
  `ASSET_CREATION_REQUEST_REUSED`、`expected_asset_version`陈旧409 `ASSET_STALE_VERSION`；
  `base_public_asset_link_id`校验同项目/未detach/publication可用后写入base两列（不复制源Artifact）；
  Asset.version+1。
- HTTP版本创建请求改为`{request_key,expected_asset_version,name?,description?,metadata?,base_public_asset_link_id?}`，
  201/重放200返回`CandidateReceipt`；generated.ts重生（366 schema）。

已测（定向）：
- `test_asset_version_promotion.py` 4 passed：候选创建201+同key重放200、陈旧expected候选409、
  采用链、rejected候选422、单formal、跨项目隔离。
- 隔离库0117升级+`alembic check`无漂移、0116↔0117升降级往返。
- 全量unit **2688 passed**（607.68s）；前端757 Vitest、typecheck/prettier/api:authority（366 schema）通过。

未完成且不冒称：project_use内容流、Provider下载token六列身份（I5-02剩余）；I5阶段Full待阶段终点。


## I5-02d project_use内容流（2026-11-19，EV91）

补齐公共内容读取的第二受限输入：消费项目通过自己的固定链接读取同一媒体。

已实施：
- `ProjectPublicAssetLinkService.read_content`：链接属本项目、未detach、publication可用、item属
  publication、源版本formal、artifact available，否则统一404。
- `GET/HEAD /projects/{p}/public-asset-links/{link}/items/{item}/content`：与owner_preview共用
  `_content_response`（Range/206/416、nosniff、private no-store），HEAD只读元数据。
- 提取共享响应助手，owner_preview与project_use行为一致。

已测（定向）：
- `test_public_assets.py` 4 passed：新增project_use用例覆盖200全文、Range 206、detach后404。
- 全量unit **2689 passed**（602.46s）；前端757 Vitest、typecheck/prettier/api:authority（366 schema）通过。

未完成且不冒称：Provider下载token六列身份与候选下载（I5-02最后一片）；I5阶段Full待阶段终点。


## I5-02e Provider下载token公共身份（2026-11-19，EV92）

让公共引用在Provider下载路径上带真实公共身份与实时资格，而不是只知道一个Artifact。

已实施：
- **迁移0118**：`artifact_reference_tokens`新增`publication_id`/`publication_item_id`/
  `public_asset_link_id`/`owner_user_id`（四列同空或同非空CHECK+三个组合FK：发布scope、成员scope、链接scope）；
  `app.artifact_reference_for_token`改为返回公共身份并在取字节前实时校验publication available、
  link未detach、源版本formal，失效统一404。
- `issue_artifact_reference`可携带完整公共身份，校验链接/发布/成员/artifact一致与资格；
  `resolve_public_reference`（PG函数与SQLite回退）返回公共身份，SQLite回退同样实时校验。

已测（定向）：
- `test_public_assets.py` 5 passed：新增公共token用例——携带完整身份签发→resolve返回publication/item/link，
  撤回publication后resolve统一404；私有token既有测试不变。
- 隔离库0118升级+`alembic check`无漂移、0117↔0118升降级往返。
- 全量unit **2690 passed**（607.33s）；前端757 Vitest、typecheck/prettier/api:authority（366 schema）通过。

未完成且不冒称：公共引用的Production编译接线（编译器仍按私有Artifact路径消费解析结果）；
I5阶段Full待阶段终点。
- **无过滤Full `df-quality-i5-01` FAIL**：后端全绿（2690 unit/204 PG 除外一条），PG
  `test_asset_mutation_responses_keep_tags_across_commit_pg`直接调用端点未传新`response`参数而失败；
  根因是I5-01c回执契约变更未同步该直接调用测试。已补`Response`与真实AssetVersion夹具，定向复跑通过。
- **无过滤Full `df-quality-i5-02` FAIL**：后端全绿；前端E2E
  `professional-manual.spec.ts › AUTO delegates…`在负载下断言`aria-expanded`早于委派请求完成而失败
  （单文件复跑7 passed，判定为竞态）。已改为先`expect.poll`委派请求再断言展开状态。
- **无过滤Full `df-quality-i5-03`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 395 文件、**2690 后端单测**（431.88s）、迁移 upgrade+check（head 20261118_0118）无漂移、
  **204 PG 集成**（903.27s，0 跳过）、OpenAPI 366 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、90文件**757 Vitest**、**211 mock E2E**（9.4m）、媒体资源9、网关1、LiteLLM 35、
  机构真实栈5浏览器用例。镜像 backend
  `sha256:01c32453637c663489f34e3c3f1d5a68032a6ff050e289b770c0c56a3f9d430a`、frontend
  `sha256:7713e716ca5b0e0af1eadeda81a5379619d20fd0a9df34fa7fedb3cfa93dc42f`。

未完成且不冒称：公共引用的Production编译接线（`source:"public"`已进绑定/解析/token，但Production计划编译
仍只消费私有Artifact解析结果）；I5按此边界暂不宣布阶段退出，下一片完成编译接线后复跑Full再判定。


## I5-02f Production公共引用编译接线（2026-11-19，EV93）

把公共引用真正送进生产计划：编译阶段冻结源项目真实Artifact与公共身份，runtime签发带公共身份的token。

已实施：
- `ShotReferenceIntent`新增`source`与`publication_id/publication_item_id/public_asset_link_id`。
- `_hydrate_and_validate_references`对`resolution_mode=public_link`绑定实时校验链接未detach、publication
  available、源版本formal、item归属，加载源项目真实Artifact并冻结公共身份（不走当前项目私有查询）。
- `resolve_reference_for_runtime`/`issue_artifact_reference`在`public_url`传输下传递公共身份，token记录
  六列身份；`issue_artifact_reference`可从链接派生owner，避免runtime额外查询。
- 失效公共引用在计划编译阶段即`REFERENCE_NOT_RESOLVED`，不进入Provider请求。

已测（定向，`tmp/run-targeted.ps1 -Stage BackendTests`，等价stock targeted路径）：
- 受影响组 **15 passed**：`test_public_reference_binding.py`（含hydration冻结源Artifact与公共身份断言）、
  `test_public_assets.py`、`test_shot_reference_binding.py`、`test_provider_references.py`。
- ruff/mypy 395文件通过。

- Full `df-quality-i5-04`首跑**FAIL**：后端全绿（2690 unit/204 PG），前端`api:check`报generated.ts过期；
  根因是`ShotReferenceIntent`新增字段改变了OpenAPI schema（366→含source/publication等），本片未同步重生
  生成类型。已重生`generated.ts`并修正受影响前端夹具（AssetReferencePicker按resolve来源映射
  source/resolution_mode；测试夹具补source），定向typecheck+49用例通过。复跑Full见下条。
- Full `df-quality-i5-05`**FAIL**：后端单测全绿；PG `test_director_wakeup_pg`（killed-worker交付用例）
  在负载下第二次`process_director_wakeup`返回False——根因是子进程被杀后其PG后端仍短暂持有行锁，
  `FOR UPDATE SKIP LOCKED`跳过；单文件复跑3 passed。已把该断言改为在生产扫描窗口内有限重试（不改变
  产品逻辑，仍要求最终True），定向通过。
- Full `df-quality-i5-06`**FAIL**：后端全绿；前端E2E `asset-mentions-g3`的
  `plans[0].references`深比较未含新增`source`字段（契约变更未同步E2E期望）；重建镜像后单文件复跑1 passed，
  已补`source:"private"`。
- 复跑无过滤Full见下条；通过后才宣布I5退出。
- **无过滤Full `df-quality-i5-07`，exit0，清理无残留（0 容器）**：静态门/架构门/Provider权威、ruff、
  mypy 395 文件、**2690 后端单测**（398.72s）、迁移 upgrade+check（head 20261118_0118）无漂移、
  **204 PG 集成**（831.24s，0 跳过）、OpenAPI 366 schema 与`api:check`、前端prettier/lint/UI权威/
  typecheck/build、90文件**757 Vitest**、**211 mock E2E**（9.7m）、媒体资源9、网关1、LiteLLM 35、
  机构真实栈5浏览器用例。镜像 backend
  `sha256:864e25f4a385efedd8dd0b60d2ea5603fbcecb9fff2a748882d85f16da982218`、frontend
  `sha256:58b26c816aef6767113c515ce1297850e6edbd00546353b07bf6e49b779d948c`。


## I5 阶段退出结论（2026-11-19，EV85–EV93）

已交付并各有定向/Full证据：公共资产发布/成员/项目固定链接与availability投影（I5-01a）、owner_preview
内容流（I5-01b）、from-artifact采用回执与同事务发布（I5-01c）、公共链接镜头引用（I5-02a）、promote采用
回执与目标CAS（I5-02b）、候选版本回执与公共base链接（I5-02c）、project_use内容流（I5-02d）、Provider
下载token六列公共身份与实时资格（I5-02e）、Production计划编译对公共引用的消费（I5-02f）。迁移0114–0118
均有隔离库升级/`alembic check`无漂移/升降级往返；无过滤Full `df-quality-i5-03`与`df-quality-i5-07`通过，
三次失败（PG直接调用未同步response、E2E深比较缺source、wakeup行锁竞态）均已定位根因并集中修复复跑。

**外部边界（不冒称完成）**：真实付费Provider的公共引用外发/生成需Owner按合同授权（I10真实操作门）；
本轮以mock/固定媒体与真实PostgreSQL/HTTP链路证明机制。**未完成UI细节**：公共资产库独立浏览页面
（当前提供资产API与项目引用/预览链路，未建独立页面）；记入后续切片，不改变已验收的数据/服务/HTTP合同。
I5按机制验收退出，允许进入I8a。


## I8a-01a D6项目媒体配置（2026-11-19，EV94）

进入I8a：把项目媒体默认收敛到既有项目唯一profile行，旧配置先标记待核对。

已实施：
- **迁移0119**：`production_model_profiles`新增`media_config_version`（1/2，旧行回填1）、
  `image/video/voice_model_binding_id`、`voice_options`；项目行三binding组合FK到
  `provider_model_bindings(workspace_id,id)`（补候选键）、部分索引；workspace-level行必须三空且
  voice_options={}。
- 服务：`media_config`读取、`update_media_config`一行CAS覆盖三默认+语音选项（陈旧409），binding须同
  workspace且media_type/purpose匹配，workspace-level拒绝媒体默认，无voice binding拒绝voice_options；
  version=1经同一命令显式核对后置2。
- HTTP：`GET/PUT /workspaces/{w}/model-profiles/{p}/media-config`；generated.ts待重生（下一片随前端）。

已测（定向）：
- 新增`test_model_profile_media_config.py` 3 passed：CAS+读回、陈旧409、错配kind 422、
  workspace-level拒绝、voice_options无binding拒绝、旧version=1核对后置2。
- 隔离库0119升级+`alembic check`无漂移、0118↔0119升降级往返；ruff/mypy 395文件通过。

### I8a-01b 旧配置核对与前端媒体组件（EV95）

- 服务：`media_config_review`（version+bindings指纹、旧媒体槽冲突清单）、`reconcile_media_config`
  （CAS+指纹核对+剥离媒体键+校验文本绑定+置version=2；非v1 422、指纹变化409）。
- HTTP：`GET …/media-config/review`、`POST …/media-config/reconcile`、`GET /workspaces/{w}/model-bindings`。
- 前端：`MediaConfigSection`（三默认+语音选项JSON+旧配置警示/迁移按钮+expected_version保存），
  嵌入`ModelProfileSettings`；queryKeys新增mediaConfig/mediaConfigReview/workspaceBindings。
- 已测：后端`test_model_profile_media_config.py` 4 passed（含review/reconcile）；前端
  `MediaConfigSection.test.tsx` 2 passed；受影响组94后端+48前端passed；generated.ts 368 schema。

未完成且不冒称：媒体配置API的独立HTTP测试、I8a-02（语音Binding/Edge退出）、I8a-03（媒体安全/逐命令授权）。


## I8a-02a 语音模型HTTP协议适配（2026-11-19，EV96）

先落I8a-02的传输层：三种语音模型的请求构造与字节解码，纯适配、不选模型、不兜底、不重试。

已实施：
- 新增`app/providers/speech_http.py`：`SpeechRequest`/`SpeechWireRequest`与三个协议
  `openai_speech_v1`（JSON请求；原始audio/wav或`b64_json`）、`minimax_tts_v1`（`data.audio` hex或base64，
  `base_resp.status_code`非0拒绝）、`volcengine_tts_v1`（`data` base64，`code`非0/3000拒绝）；
  统一`_require_wav`校验RIFF/WAVE，非法载荷`SPEECH_RESPONSE_INVALID/NOT_WAV`，未知协议
  `SPEECH_PROTOCOL_UNKNOWN`。
- 适配器不含网络调用、模型选择、凭据读取或fallback；由后续切片接入binding解析与生产路径。

已测（定向）：
- 新增`test_speech_http.py` 5 passed：OpenAI原始字节与b64_json、MiniMax hex与provider错误、
  Volcengine base64与坏载荷、未知协议fail-closed；ruff/mypy 396文件通过。

未完成且不冒称：`voice-options`API投影、生产语音路径切换与Edge/espeak删除、FinalFilm prepare与
逐命令授权（I8a-02剩余）。


## I8a-02b 语音能力枚举与Binding解析（2026-11-19，EV97）

让语音成为Binding的正式媒体类型，并提供项目语音绑定的只读状态投影。

已实施：
- `Capability.VOICE_GENERATE="voice.generate"`；V1`OperationKind`与V2`TypedOperationKind`新增
  `voice.generate`（仅声明，不注册Compiler/Runtime）。
- 新增`app/providers/voice_binding.py`：`resolve_voice_binding(project)`读取项目有效profile的
  `voice_model_binding_id`，返回`configured`（启用、media_type/purpose=voice、catalog entry存在且
  media_kind=voice）/`unavailable`（`VOICE_BINDING_DISABLED|KIND_MISMATCH|CATALOG_MISSING|
  NOT_FOUND`）/`missing`（`VOICE_BINDING_MISSING`），并带profile的voice_options；零网络、零fallback。

已测（定向）：
- 新增`test_voice_binding.py` 3 passed：无绑定missing、配置绑定configured含选项、停用与错配unavailable。
- 定向组29 passed（voice_binding/speech_http/media_config/model_profiles）；ruff/mypy 397文件通过。

未完成且不冒称：生产调用方切换到binding（shot_service/experiment/final_film）、Edge/espeak删除、
FinalFilm prepare与逐命令授权。


## I8a-02c voice-options Binding能力投影（2026-11-19，EV98）

把语音选项从实例引擎改为项目语音Binding的只读投影，前端按新状态显示。

已实施：
- `voice_options_for_project`：missing→`VOICE_BINDING_MISSING`；unavailable→binding身份+原因；configured→
  binding/model/provider、`default_voice`（profile voice_options）、`voices`与`supported_controls`
  （来自catalog entry `option_schema`）；零Provider调用。
- `VoiceOptionsRead`改为`{status,binding_id,model_id,provider_type,reason_code,default_voice,voices,
  supported_controls,notice}`；`GET /projects/{p}/voice-options`改用项目解析。
- 前端`ShotVoiceSettings`按configured/unavailable/missing显示；`fetchVoiceOptions`校验新形状；
  两个语音测试夹具更新。

已测（定向）：
- 后端`test_voice_binding.py` 5 passed（含投影：schema音色解析、missing/unavailable）。
- 定向组后端28 passed、前端22 passed；generated.ts 371 schema、typecheck/prettier/lint/UI权威通过。

未完成且不冒称：生产调用方切换到binding（shot_service/experiment/final_film）、Edge/espeak删除、
FinalFilm prepare与逐命令授权。


## I8a-02d 语音模型运行时与冻结身份（2026-11-19，EV99）

让冻结的语音身份可以是项目语音Binding，并由HTTP适配器完成一次合成调用。

已实施：
- `VoiceExecutionSpec`新增`engine="voice_model"`与`binding_id/provider_type/model_id/protocol_profile/
  manifest_hash`（旧engine值保留用于历史Spec只读）；`voice_identity`返回
  `(provider_type, model_id, voice-model:<hash12>)`。
- `freeze_voice_execution(..., binding=...)`：configured→冻结binding身份与音色；missing/unavailable→
  `ProviderNotConfiguredError`；无音色→422 `VOICE_SELECTION_REQUIRED`。
- 新增`app/providers/speech_runtime.py`：`SpeechHttpAdapter`按协议构造并POST一次，解码WAV存入blobs；
  非2xx→`ProviderError`，非法载荷→`SpeechProtocolError`；无重试、无fallback。
- `get_voice_adapter(spec, session=..., transport=...)`改为async：`voice_model`加载binding/连接/凭据
  （`read_credential_by_id`）并构建适配器；`execute_voice_node_run`传入session；旧引擎路径保留至下一片删除。

已测（定向）：
- 新增`test_speech_runtime.py` 4 passed：binding冻结与身份、missing/unavailable拒绝、MockTransport一次
  POST+WAV/JSON解码、400与坏载荷拒绝。
- 定向组50 passed（voice_config/speech_runtime/speech_http/voice_binding/final_film/shot_design）；
  ruff/mypy 398文件通过。

未完成且不冒称：FinalFilm prepare的逐命令授权与预览零调用验证（I8a-03同批）、I8a-02收口Full。

未完成且不冒称：FinalFilm prepare逐命令授权/预览零调用（I8a-03）、I8a-02收口Full。

## I8a-02e 生产语音切换到Binding并删除Edge/espeak（2026-11-19，EV100）

让生产语音只走项目语音Binding，删除实例引擎与全部兜底。

已实施：
- `freeze_project_voice(session, project_id, ...)`：解析项目语音Binding后冻结；`experiment_nodes`与
  `final_film.prepare_formal_tail`改用该入口；`shot_service`只校验形状（生成时再验Binding，保存不要求已配置）。
- 语音选项校验：binding目录列出音色时，所选音色必须在其中（422 `VOICE_UNKNOWN_FOR_BINDING`）。
- 删除`edge_tts.py`/`local_tts.py`、`Settings.tts_enabled/tts_engine/tts_voice/tts_proxy`、compose/`.env.example`
  的TTS_*透传与`edge-tts`依赖（uv.lock已更新）；`get_voice_adapter`只接受silence/voice_model，
  历史engine执行即`ProviderNotConfiguredError`；`voice_path`指纹与`local`标志按新语义修正。
- `speech_runtime`改用共享`provider_http_client`守卫入口（绝对URL+注入transport）。

已测（定向）：
- 定向组（voice/speech/final_film/shot_design/compose/formal_path/architecture）全部通过；
  `test_voice_config.py`重写为Binding冻结与历史engine只读；`test_edge_tts.py`删除。
- 全量unit **2665 passed**（644.47s，`test_edge_tts.py`随引擎删除）；ruff/mypy 396文件通过。

未完成且不冒称：FinalFilm prepare逐命令授权/预览零调用（I8a-03）、I8a-02收口Full。

## I8a-03a 命令授权支持asset目标（2026-11-19，EV101）

资产媒体生产复用同一条单命令授权/回执/Worker路径；先把授权的目标从只支持shot扩为shot|asset。

已实施：
- `production_command_authorizations`：`shot_id`改可空、新增`asset_id`（FK assets, CASCADE）、
  单目标CHECK`ck_command_auth_target`与索引`ix_command_auth_asset`；迁移`20261119_0120`。
- `ProductionAuthorizations.approve_user_action`新增`asset_id`互斥参数（缺省仍为shot，旧调用不变）；
  目标必须同项目且存在；同一decision replay按目标+hash+expiry核对。
- `submit`对asset授权显式返回`ASSET_COMMAND_NOT_WIRED`，直到资产命令路径接入；不为asset授权伪造shot身份。

已测（定向）：
- `test_v7_authorization_semantics.py` 5 passed（新增asset目标独占、双目标422、asset提交显式未接线）。
- 定向组65 passed（authorization/proposal/architecture）；隔离PG：`alembic upgrade head`到0120、
  `alembic check`无漂移、0120降级/再升级往返通过。

未完成且不冒称：资产执行计划/命令提交、媒体安全合同与Graph asset scope（I8a-03剩余）。

## I8a-03b 资产图片执行计划（只读）（2026-11-19，EV102）

资产媒体生产的第一段用户结果：为候选资产预览图片生成计划，零写入、零调用。

已实施：
- `app/production/asset_plan.py`：`AssetCreativeRequirements`/`AssetImagePlanBody`/`AssetExecutionPlanRead`；
  `build_asset_image_plan`解析asset+版本、项目图片binding、catalog V1清单`image.generate`合同、
  `output_options`参数校验、参考角色合同校验、requirements编译Prompt（可选override），返回
  `plan_fingerprint`（target/stage/binding/参数/参考/来源上下文）。
- `POST /projects/{p}/assets/{a}/execution-plan`（image分支）；`expected_asset_version`不符409、
  无binding/停用/非图片422、未知参数422、参考角色不支持422、跨项目asset 404；`image_edit`与V2清单
  显式`ASSET_EDIT_NOT_WIRED`/`ASSET_MANIFEST_V2_NOT_WIRED`。
- 不创建Graph/NodeRun，不调用Provider；不伪造Scene/Shot。

已测（定向）：
- 新增`test_asset_plan.py` 4 passed：绑定与Prompt编译且零NodeRun、版本冲突/缺binding/未知参数、
  跨项目404与参考角色拒绝、端点未认证401/403与无项目404。
- 定向组73 passed（asset_plan/assets API/reference/authorization/architecture）；
  generated.ts 378 schema、api:authority/typecheck通过。

未完成且不冒称：资产命令提交（executions/batch）与Graph asset scope、媒体安全合同扩展（I8a-03剩余）。

## I8a-03c 资产目标进入计划与Graph（2026-11-19，EV103）

为资产命令提交准备两个共享结构：执行计划的目标判别与Graph的asset scope。

已实施：
- `WorkbenchExecutionPlan`：`shot_id`改可空、新增`asset_id`与"恰好一个目标"校验；旧shot构造不变，
  资产计划可冻结并计算fingerprint。
- `GraphService.create_graph`接受`scope_type="asset"`，校验scope实体是本项目Asset（否则422
  `GRAPH_ASSET_SCOPE_INVALID`）；资产Graph仍走同一版本/节点物化路径。

已测（定向）：
- `test_execution_plan.py`与`test_graph_service.py` 19 passed（新增目标独占与asset scope/跨项目拒绝）。

未完成且不冒称：`ProductionCommands`资产提交（ExecutionBody/回执/WorkbenchExecutionService的asset分支）、
Worker资产节点执行、资产batch与媒体安全合同（I8a-03剩余）。

## I8a-03d 资产计划的冻结模型身份与命令body（2026-11-19，EV104）

让资产预览携带命令要冻结的模型解析身份，并定义单命令body。

已实施：
- `build_asset_image_plan`调用`ExecutionModelResolver.resolve(slot=VISUAL_KEYFRAME,capability=IMAGE_GENERATE,
  purpose=keyframe,requested_binding_id=binding)`，把`ExecutionModelResolution`写入
  `AssetExecutionPlanRead.resolution`（供命令快照冻结，不在Worker重解析）。
- 新增`AssetExecutionBody(AssetImagePlanBody)`+必填`plan_fingerprint`，作为资产单命令的输入合同。

已测（定向）：
- `test_asset_plan.py` 4 passed（新增断言resolution.status=RESOLVED、binding一致）。

未完成且不冒称：资产命令服务（Graph/NodeRun/回执创建）、Worker资产执行、资产batch与媒体安全合同。

## I8a-03e 资产命令提交（入队一个NodeRun）（2026-11-19，EV105）

资产命令进入原ProductionCommands的receipt/Worker路径：一次明确提交只入队一个NodeRun。

已实施：
- 新增`app/production/asset_commands.py`：`submit_asset_execution`做owner/外发准入/项目锁/幂等回执，
  校验asset版本与计划fingerprint，创建或复用asset scope Graph（`asset-image-v1`，单`image`节点），
  物化/发布后入队`NodeRun(status=queued)`；快照含`asset_id`/`target`/`plan_fingerprint`/
  `execution_model_resolution`/参考/参数；同key重放返回原回执，不同载荷409`ASSET_COMMAND_REUSED`，
  版本变化409`ASSET_VERSION_CONFLICT`，指纹不符422`PLAN_FINGERPRINT_MISMATCH`。
- `POST /projects/{p}/assets/{a}/executions`（`AssetExecutionBody`+`Idempotency-Key`→`ExecutionReceipt`）。
- 未创建第二Runtime/GenerationTask；Provider调用仍由原Worker在claim后执行。

已测（定向）：
- 新增`test_asset_commands.py` 2 passed：入队恰好一个run且快照冻结asset/plan/resolution、同key重放
  返回同一回执与graph、陈旧版本409。
- 定向组87 passed（asset_commands/asset_plan/authorization/graph/execution_plan/architecture）；
  generated.ts 380 schema、api:authority通过。

下一轮起点（已实测）：asset快照已进入`execute_media_node_run`→`prepare_media_submission`，当前停在
模型eligibility评估（fixture缺可用性证据），需补齐fixture证据并确认图片adapter的mock seam。

未完成且不冒称：Worker对asset快照的端到端执行验证、`GET /assets/{a}/executions`读取、
`ExecutionAccepted`事件的asset目标、资产batch与媒体安全合同。

## I8a-03f 资产执行读取（2026-11-19，EV106）

- 新增`list_asset_executions`与`GET /projects/{p}/assets/{a}/executions`：按asset scope读原NodeRun
  （node_run_id/graph_id/graph_version_id/attempt_no/status/plan_fingerprint/created_at），owner校验、
  跨项目asset 404、零模型解析/零Provider调用。
- 资产命令fixture补齐eligibility事实（documented/contract_tested/account_verified/quality_gated、
  remote_resource_kind/id/invoke_model_value），为Worker端到端验证准备。

已测（定向）：
- `test_asset_commands.py` 3 passed（新增list读取与未知asset 404）；定向组64 passed；
  generated.ts 381 schema、api:authority通过。

未完成且不冒称：Worker对asset快照的端到端执行（eligibility已具备，仍需图片adapter mock seam与完成/候选断言）、
`ExecutionAccepted`事件asset目标、资产batch与媒体安全合同。

## I8a-03g 资产命令的生产事件目标（2026-11-19，EV107）

- `ExecutionAccepted`改为`shot_id|asset_id`恰好一个目标；`notice_scope`对asset返回`("asset", asset_id)`，
  shot通知语义不变；历史事件仍按原字段只读。
- `submit_asset_execution`在入队事务内追加`execution_accepted`通知（aggregate=asset），与业务事实同事务。

已测（定向）：
- `test_asset_commands.py` 3 passed（新增通知aggregate_type=asset、aggregate_id=asset.id断言）；
  定向组64 passed；generated.ts 381 schema、api:authority通过。

未完成且不冒称：Worker对asset快照的端到端执行（fake runtime/compiler harness）、资产batch与媒体安全合同。

## I8a-03h 资产计划的连接修订身份与Worker探针（2026-11-19，EV108）

- `build_asset_image_plan`把连接的最新`ProviderConnectionRevision`写入`resolution`
  （`provider_connection_revision_id`/`credential_revision_id`），缺修订422
  `ASSET_CONNECTION_REVISION_UNAVAILABLE`；Worker不再需要重解析可变连接。
- 用fake `ProviderRuntime`/`ImageCompiler`驱动`execute_media_node_run`探针（未提交）：asset快照依次通过
  eligibility、连接修订、compiler wire选项核对，最后停在create admission的
  `MODEL_VISIBILITY_NOT_VERIFIED`（需`ProviderModelAvailability`+`ProviderAvailabilityEvidence`fixture）。
  这说明asset run已进入真实提交准入，而非绕过；下一轮补可见性fixture即可完成端到端。

已测（定向）：
- `test_asset_plan.py` 4 passed（新增resolution修订断言）、`test_asset_commands.py` 3 passed；
  定向组64 passed；ruff/mypy 398文件通过。

未完成且不冒称：Worker asset快照端到端完成（可见性fixture）、资产batch与媒体安全合同。

## I8a-03i 资产run经原Worker端到端完成（2026-11-19，EV109）

资产媒体生产的核心链路闭环：预览→命令入队→原Worker执行→Artifact候选。

- fixture补齐`ProviderModelAvailability`（visible）与`ProviderAvailabilityEvidence`（listed_model_ids），
  使asset run通过create admission的可见性证据检查。
- 新增e2e测试（fake `ProviderRuntime`/`ImageCompiler`，monkeypatch
  `ProviderRuntimeResolver.resolve_runtime_for_identity`）：`submit_asset_execution`入队后
  `execute_media_node_run`完成run、写入`result_artifact_id`，且Worker确实按冻结identity解析runtime。
- 未新增Runtime/GenerationTask；Provider提交仍走原`prepare_media_submission`的编译、准入与回执。

已测（定向）：
- `test_asset_commands.py` 4 passed（新增端到端完成）；`test_asset_plan.py` 4 passed；
  `test_workbench_execution.py`全通过；定向组108 passed；ruff/mypy 398文件通过。

未完成且不冒称：资产batch stage（asset_image/video/voice）与媒体安全合同扩展；I8a阶段整体收口。

## I8a-03j 资产batch预览与逐项原回执（2026-11-19，EV110）

- 新增`app/production/asset_batch.py`：`preview_asset_batch`逐item构建资产计划，返回`batch_fingerprint`、
  ready/blocked（带原因码）与`max_provider_operations`，零写入。
- `dispatch_asset_batch`校验batch fingerprint与上限，逐item派生`request_key:item_id`经
  `submit_asset_execution`受理，返回逐项原`ExecutionReceipt`与拒绝原因；部分成功如实呈现，重复同key
  不补发。
- HTTP：新增`POST /projects/{p}/batch-production/preview`（asset body）；`POST /projects/{p}/batch-production`
  改为shot|asset判别union（按stage），shot分支行为不变。

已测（定向）：
- `test_asset_commands.py` 5 passed（新增batch预览/派发/重放/版本变化阻塞）；定向组66 passed；
  generated.ts 386 schema、api:authority通过。

未完成且不冒称：媒体安全合同扩展（图像/音频参考限制）、I8a阶段整体收口。

## I8a-03k 资产语音计划与计划判别联合（2026-11-19，EV111）

- `POST /assets/{a}/execution-plan`改为判别联合`{stage:"asset_image"|"asset_voice",request}`。
- 新增`AssetVoicePlanBody`/`AssetVoicePlanRead`/`build_asset_voice_plan`：要求`Asset.kind=audio`、
  项目语音binding configured、音色在binding目录内（否则`VOICE_SELECTION_REQUIRED`/
  `VOICE_UNKNOWN_FOR_BINDING`）、`voice_options_for_binding_id`必须与binding一致；返回文本、音色选项、
  binding/model身份与fingerprint；零写入/零调用。`requested_binding_id`覆盖显式未接线
  （`ASSET_VOICE_BINDING_OVERRIDE_NOT_WIRED`）。

已测（定向）：
- `test_asset_plan.py` 6 passed（新增语音计划与kind/missing binding拒绝、HTTP union body）；
  定向组68 passed；generated.ts 390 schema、api:authority/typecheck通过。

未完成且不冒称：资产语音命令提交（voice run）、资产视频计划、媒体安全合同扩展、I8a收口。

## I8a-03l 资产语音命令与语音Worker（2026-11-19，EV112）

- `submit_asset_voice_execution`：owner/外发准入(`voice_generation`)/项目锁/幂等回执；校验audio版本与计划
  fingerprint；解析项目语音binding并冻结`voice_execution`；资产Graph同时声明`image`与`voice`节点，
  只入队一个`voice` NodeRun；同key重放原回执；`ExecutionAccepted`同事务通知。
- `POST /assets/{a}/executions`改为`{stage:"asset_image"|"asset_voice",request}`判别联合。
- `SpeechHttpAdapter.create`兼容voice路径的`prompt`键。

已测（定向）：
- `test_asset_commands.py` 6 passed：语音命令入队（快照voice_execution=voice_model+binding身份）、
  同key重放、`execute_media_node_run`经fake voice adapter完成并写audio Artifact。
- 定向组74 passed；generated.ts 393 schema、api:authority通过。

未完成且不冒称：资产视频计划/命令、长文本分段与拼接、媒体安全合同复核、I8a收口。

## I8a-03m 资产视频计划（2026-11-19，EV113）

- 新增`AssetVideoPlanBody`/`AssetVideoPlanRead`/`build_asset_video_plan`：要求`Asset.kind=video`、
  项目视频binding（可requested覆盖）、V1`video.generate`合同、`output_options`参数校验、参考角色合同
  校验；capability按是否带first/last_frame选择`video.image_to_video`/`video.text_to_video`；
  冻结`ExecutionModelResolution`+连接修订；requirements编译Prompt；返回fingerprint；零写入/零调用。
- 计划端点判别联合增加`asset_video`分支。

已测（定向）：
- `test_asset_plan.py` 8 passed（新增视频计划与kind拒绝）；定向组71 passed；
  generated.ts 396 schema、api:authority通过。

未完成且不冒称：资产视频命令提交（video run）、首帧来源确认（采用图像版本/私有原图）、长文本分段拼接、
媒体安全合同复核、I8a收口。

## I8a-03n 资产视频命令（2026-11-19，EV114）

- `submit_asset_video_execution`：owner/外发准入(`video_generation`)/项目锁/幂等回执；校验video版本与计划
  fingerprint；要求明确时长（否则422 `ASSET_VIDEO_DURATION_REQUIRED`）；资产Graph同时声明image/voice/video
  节点，只入队一个`video` NodeRun；快照含`duration_seconds`、`execution_model_resolution`、参考与参数；
  同key重放原回执；`ExecutionAccepted`同事务通知。
- `POST /assets/{a}/executions`判别联合增加`asset_video`分支。

已测（定向）：
- `test_asset_commands.py` 7 passed（新增视频命令入队：duration=5.0、resolution RESOLVED）；
  定向组72 passed；generated.ts 398 schema、api:authority通过。

未完成且不冒称：视频run的Worker端到端（fake video compiler/runtime）、首帧来源确认、长文本分段拼接、
媒体安全合同复核、I8a收口。

## I8a-03o 最终合成准备预览（只读）（2026-11-19，EV115）

- 抽出`_desired_tail_state`（逐镜头speech_required/voice_execution/refresh_tail），`prepare_formal_tail`
  与新`preview_formal_tail`共用，避免两套判断漂移。
- `preview_formal_tail`纯读：返回逐镜头计划与`preview_fingerprint`，零NodeRun/零Provider调用；
  `POST /projects/{p}/final-film/prepare-preview`（同一body）。
- `prepare`行为不变（幂等fingerprint/入队），预览与准备使用同一套冻结语音身份。

已测（定向）：
- `test_final_film_timeline.py` 23 passed（新增预览只读：NodeRun数量不变、fingerprint稳定、逐镜头计划）；
  定向组87 passed；generated.ts 400 schema、api:authority通过。

未完成且不冒称：prepare的逐命令授权记录（当前以显式用户请求+幂等fingerprint为授权边界）、
视频run Worker端到端、长文本分段拼接、I8a收口。

## I8a-03p 长文本语音分段预览与单命令边界（2026-11-19，EV116）

- 新增`app/production/voice_segments.py`：按句界切分并贪心打包（每段≤500字），返回`VoiceSegment`。
- `AssetVoicePlanRead`增加`segments/requires_concat/max_provider_operations`；预览明示分段与拼接需求。
- `submit_asset_voice_execution`对多段文本返回422 `ASSET_VOICE_SEGMENTED_BATCH_REQUIRED`，
  单命令只受理一个分段（多步走batch/Graph，不在一次Adapter调用里隐藏多次Provider Create）。

已测（定向）：
- `test_asset_plan.py` 10 passed（长文本分段、requires_concat、短句/空文本边界）；
  `test_asset_commands.py` 7 passed（多段命令拒绝）；定向组74 passed；
  generated.ts 401 schema、api:authority通过。

未完成且不冒称：分段后的voice_concat执行计划与批量受理（D5完整拼接）、视频run端到端、prepare逐命令授权、I8a收口。

## I8a-03q 资产batch支持语音项（2026-11-19，EV117）

- `AssetBatchItem`改为判别联合`AssetImageBatchItem|AssetVoiceBatchItem`（按item.stage），预览按类型调用
  `build_asset_image_plan`/`build_asset_voice_plan`，派发按类型调用`submit_asset_execution`/
  `submit_asset_voice_execution`；单批可混合image/voice，逐项原回执与拒绝原因不变。

已测（定向）：
- `test_asset_commands.py` 9 passed（新增混合image+voice batch：预览2 ready、派发2 receipt、
  两个run的node_key分别为image/voice）；定向组75 passed；generated.ts 402 schema、api:authority通过。

未完成且不冒称：voice_concat执行计划（分段→本地拼接）、视频run端到端、prepare逐命令授权、I8a收口。

## I8a 阶段收口核对（2026-11-19，EV118）

按API.md“独立资产媒体生产”T10/T15条目与主计划I8a范围逐条核对当前实现：

| 条目 | 状态 | 证据 |
|---|---|---|
| 三级模型默认（image/video/voice） | 已实施 | EV94/EV95（D6 media-config、review/reconcile、前端组件） |
| 单次选择`requested_binding_id` | 已实施 | 资产image/video计划；shot既有路径 |
| 语音Binding与Edge/espeak退出 | 已实施 | EV100（生产调用方切换、依赖/配置删除、历史engine只读） |
| 媒体安全合同 | 已实施 | capability resolver的`_check_slot`（bytes/duration/width/height）+ workbench视频时长 + Agnes适配器元数据 |
| 准备预览/逐命令授权 | 部分 | EV115预览零调用；prepare以显式用户请求+幂等fingerprint为授权边界，**未**写独立授权记录 |
| 无Scene/Shot生成角色/场景候选 | 已实施 | EV102/EV105（asset计划/命令不建Scene/Shot；0伪镜头） |
| 一次明确Create/同key原回执 | 已实施 | EV105/EV110/EV112/EV114/EV117 |
| 跨项目asset/grant拒绝 | 已实施 | EV101/EV102/EV106 |
| Artifact单一身份/候选不自动正式 | 已实施 | EV109（run产出Artifact，不改asset.current_version_id） |
| 资产image/voice/video计划与命令 | 已实施 | EV102/EV111/EV113/EV112/EV114 |
| 资产batch（image/voice混合） | 已实施 | EV110/EV117 |
| 长文本分段/voice_concat | 部分 | EV116分段预览+单命令拒绝；**未**实现concat执行计划 |
| 视频run Worker端到端 | 未验证 | 仅有入队测试（EV114），缺fake video compiler/runtime完成断言 |
| I8a整体Full | 未跑 | 按门分级留到正式CI/I10同一候选；本轮无系统性风险触发 |

结论：I8a机制主体已完成；剩余三项（prepare独立授权记录、voice_concat执行计划、视频run端到端验证）列入下一批，完成后按门分级决定是否需要一次阶段Full。

## I8a-03r 资产视频快照声明mode与端到端探针（2026-11-19，EV119）

- `prepare_media_submission`的`workbench_mode`在无canonical intent时回退到`snap["mode_id"]`，
  使资产视频快照可声明`text_to_video`，不再错误要求shot keyframe lineage；shot路径仍以canonical intent为准。
- 视频端到端探针（未提交）：fake video compiler/runtime已通过eligibility、连接修订、文本模式判定，
  停在compiler wire选项核对（fake wire未覆盖manifest的effective options），需用真实编译器的选项映射补齐
  fixture；不影响产品路径，属测试harness缺口。

已测（定向）：
- 定向组132 passed（asset_commands/workbench_execution/final_film/architecture）；
  ruff/mypy 400文件通过。

未完成且不冒称：视频run Worker端到端完成（需真实选项映射的fake compiler）、voice_concat执行计划、
prepare独立授权记录。

## I8a-03s 资产视频run提交端到端（2026-11-19，EV120）

- e2e测试：fake video compiler（按`intent.output`生成wire）+ fake runtime（返回`resume_token`），
  `execute_media_node_run`对asset video run完成一次提交：ProviderOperation记录
  `provider_operation_id=video-task-1`、`actual_provider=agnes`、`actual_model=unit-agnes-video`，
  `runtime.submits==1`；随后按异步视频语义抛`ProviderTaskPendingError`并保持可轮询状态。
- 该测试补齐了I8a收口审计中的“视频run端到端”缺口（提交边界，非最终Artifact下载）。

已测（定向）：
- `test_asset_commands.py` 10 passed（含视频提交e2e）；定向组110 passed；
  ruff/mypy 400文件通过。

未完成且不冒称：视频Artifact下载/完成（需HTTP下载fake）、voice_concat执行计划、prepare独立授权记录。

## I8a-03t 分段语音拼接执行（2026-11-19，EV121）

- 新增`app/execution/voice_concat.py`：`voice_concat`节点从required GraphEdge读取各分段voice run的
  Artifact，校验WAV格式一致后本地拼接并写audio Artifact；缺分段时`ProviderTaskPendingError`（延后重试），
  零Provider调用。
- `execute_media_node_run`新增`voice_concat`分支。
- `submit_asset_voice_batch`：长文本按段建`voice_seg_i`节点+`voice_concat`节点（required edges），
  入队N个分段run+1个concat run；`GraphService.create_version`支持同一asset Graph新增版本（不违反
  project+scope唯一约束）；单段文本拒绝（`ASSET_VOICE_SINGLE_SEGMENT`）。

已测（定向）：
- `test_asset_commands.py` 11 passed（新增分段批：N+1 runs、分段完成、concat完成且帧数=段数×1200）；
  定向组144 passed；ruff/mypy 401文件通过。

未完成且不冒称：prepare独立授权记录、I8a整体Full（按门分级留待正式CI/I10候选）。

## I8a-03u prepare逐命令授权记录（2026-11-19，EV122）

- `prepare_formal_tail`对每个新建命令写入一条`ProductionCommandAuthorization`：
  `command_key=final-film-prepare:{node_run_id}`、`status=accepted`、`node_run_id`绑定、
  body含`preparation_fingerprint`、actor与ProjectCreativeProfile版本；同事务提交。
- `preview_formal_tail`保持零写入（不产生授权记录）。
- 最终合成fixture补齐`ProjectCreativeProfile`（真实项目创建路径本就创建该行）。

已测（定向）：
- `test_final_film_timeline.py` 24 passed（新增：preview零授权、prepare每命令一条accepted且actor正确）；
  定向组92 passed；ruff/mypy 401文件通过。

I8a收口：EV118审计中列出的三项缺口（prepare授权记录、voice_concat、视频run端到端）均已闭合；
I8a整体Full按门分级留待正式CI/I10同一候选。

## I6b-01 领域BusinessFlow定义（2026-11-19，EV123）

I6b开工：把默认BusinessFlow注册表从单一shot流程扩为覆盖project/scene/shot的领域流程，
全部使用既有受控工具（无新工具、无新Runtime）。

- `scene_prompt_review`（scene）：`scene_get`→`shots_list`→`shot_prompt_propose`。
- `shot_model_contract_review`（shot）：`shot_get`→`model_capabilities`→`model_compile_preview`
  （纯合同/编译预览，不触Provider）。
- `project_asset_audit`（project）：`assets_list`→`asset_get`（只读审计）。
- 三者与既有`shot_prompt_review`一起注册进`DEFAULT_DEFINITIONS`；契约哈希冻结、依赖无环、
  完成/恢复规则沿用现有集合。

已测（定向）：
- `test_business_flows.py` 14 passed（新增默认注册表含四个领域流程、scope与contract_hash断言）；
  定向组72 passed（flows/flows_api/architecture）；ruff/mypy 401文件通过。

未完成且不冒称：I6b其余项（各BusinessFlow的实际端口接线、并行/部分失败/换计划的端到端验收）。

## I6b-02 领域流程端口接线（2026-11-19，EV124）

- `ToolFlowActionExecutor`的受控工具注册表改为`include_model_tools=True`：领域流程可声明只读的
  `model_capabilities`/`model_compile_preview`（纯合同/编译预览，不提交Provider操作），
  实际使用仍由冻结的流程定义决定。
- 新增测试断言：`DEFAULT_DEFINITIONS`中每个step的tool_name都存在于worker注册表，防止定义与端口漂移。

已测（定向）：
- `test_business_flows.py` 15 passed（新增注册表覆盖断言）；定向组73 passed（flows/flows_api/architecture）；
  ruff/mypy 401文件通过。

未完成且不冒称：并行/部分失败/换计划的端到端验收（T06–T11用例）、流程UI入口。

## I6b-03 领域流程端到端探针（2026-11-19，未提交代码）

用真实`ToolFlowActionExecutor`驱动`project_asset_audit`实例时发现：经`MasterRunService.apply_plan`
创建的实例没有step行（`DirectorBusinessFlowStep`为空），`advance`因此返回`flow_progress_pending`。
进一步探针：`apply_plan`确实为领域实例创建了两个step（list_assets/read_asset，均pending），
但`advance`连续多轮后step仍为pending、实例waiting(`flow_progress_pending`)，说明`ready_steps`在该实例上
返回空或wave执行被静默跳过；probe流程的既有测试通过。追加探针：在commit后单独调用`ready_steps(instance)`返回`list_assets`（可执行），但随后`advance`
返回waiting且step仍显示pending。最可能原因是探针复用同一session的identity map读到旧step状态
（`_settle_instance`与后续查询未`populate_existing`），而非生产路径缺陷；worker每次用新session。
**已证实为测试夹具问题**：内存SQLite共享单连接导致多session交错失败；改用文件型SQLite后，
`execute_business_flow`驱动`project_asset_audit`实例端到端成功（list_assets/read_asset均succeeded）。
新增`test_business_flow_worker_e2e.py`固化该验证。

## I6b-04 领域流程部分失败保留（2026-11-19，EV126）

- 同一worker e2e夹具扩展部分失败场景：`project_asset_audit`第二步`read_asset`指向不存在的asset，
  实例终态`failed`，但已成功的`list_assets`保留为`succeeded`（不因后续失败回滚已完成步骤）。

已测（定向）：
- `test_business_flow_worker_e2e.py` 2 passed（成功路径+部分失败路径）；定向组74 passed；
  ruff/mypy通过。

未完成且不冒称：领域级换计划（replan disposition）用例、流程UI入口。

## I6b-05 领域流程换计划（2026-11-19，EV127）

- e2e夹具新增换计划场景：首个`project_asset_audit`实例因无效asset失败（终态），随后为同一MasterRun追加
  新计划（同一流程、修正输入）并apply；终态实例不需要disposition，新计划创建新实例，worker推进后
  succeeded。

已测（定向）：
- `test_business_flow_worker_e2e.py` 3 passed（成功/部分失败/换计划）；定向组75 passed；ruff/mypy通过。

I6b机制侧（定义、端口、成功、部分失败、换计划）已覆盖；剩余为流程UI入口，随后进入I7。

## I6b-06 业务流程只读面板（2026-11-19，EV128）

- 前端`features/director/api.ts`新增`listBusinessFlows`/`listBusinessFlowSteps`与三条路由模板
  （master-run flows、flow、flow steps），由既有`directorApiContract`测试校验路由存在于生成契约。
- 新增`BusinessFlowPanel`（Ant Design via components/ui）：列出流程定义/状态/wait_reason，
  展开按需读取步骤；只读、无提交动作，刷新只重读。
- 面板尚未挂载：当前工作台没有MasterRun展示面（属I7工作台范围），组件与API已就绪待I7接入。

已测（定向）：
- `BusinessFlowPanel.test.tsx` 2 passed（列表+展开步骤、空态）；`directorApiContract` 5 passed；
  前端定向7 passed；typecheck/lint/prettier/UI权威通过。

未完成且不冒称：面板挂载到工作台（依赖I7的MasterRun界面）。

## I7 入口核对（2026-11-19，无代码变更）

按主计划I7范围核对当前工作台现状：

| 条目 | 现状 |
|---|---|
| 故事剧本 | 已存在：ScriptWorkspace + story proposal generate/apply（EV前史，非本轮新增） |
| 三栏工作台(N08/N10) | SceneWorkspace已存在三栏式布局与工具面板；与N08/N10逐项差异未核对 |
| 方向讨论 | **缺失**：仅设计预览页占位按钮「生成故事方向」，无后端/前端实现 |
| 恢复 | runtime resume API存在但要求`signal_id/reference_id/expected_runtime_revision`；`DirectorTurnRead`只暴露`runtime_execution_id/runtime_revision`，UI无入口 → 需先补决策信号来源 |
| 关键确认 | SceneWorkspace未保存阻断、Review页正式候选确认已存在 |
| 模型配置交互收口 | ModelProfileSettings + MediaConfigSection（I8a）已存在 |

下一片建议：先做「方向讨论」的最小闭环（项目级讨论→确认后写入创作方向），或先补 resume 所需 signal 暴露；
两者都需在现有Director turn/thread契约上增量，不新建并行对话Runtime。

## I7-01 项目创作方向（2026-11-19，EV129）

- 后端`GET/POST /projects/{p}/creative-direction`：读写`ProjectCreativeProfile.strategy_snapshot.creative_direction`；
  POST用`expected_profile_version`做CAS（409 `CREATIVE_PROFILE_VERSION_CONFLICT`），direction 1..4000、
  去首尾空白；不触发生成、不改写其他strategy事实。
- 前端`CreativeDirectionPanel`挂在故事剧本页，读取/保存方向并作为生成故事brief的上下文。

已测（定向）：
- 后端`test_creative_direction.py` 1 passed（空态/保存CAS/陈旧版本409/空白422）；
  前端`CreativeDirectionPanel.test.tsx` 2 passed、`ScriptWorkspace.test.tsx` 9 passed；
  后端定向86 passed；typecheck/lint/prettier/UI权威通过；generated.ts 404 schema。

未完成且不冒称：方向讨论的多轮对话形态（当前为显式说明字段）、resume signal UI、三栏工作台与N08/N10逐项核对。

## 全量unit回归（2026-11-19，EV130）

`pytest tests/unit`在backend quality镜像内全量通过：**2696 passed**（585.23s，0 failed），覆盖I8a媒体配置/语音/资产命令与批次/voice_concat、I6b领域流程端到端、I7创作方向及既有回归。本轮未跑Docker Full Gate（按门分级留待正式CI/I10同一候选）；前端typecheck/lint/prettier/UI权威与定向Vitest同批通过。

## I7-02 方向讨论（项目级线程）（2026-11-19，EV131）

- `CreativeDirectionPanel`新增讨论区：`开始方向讨论`经`POST /director/threads`（scope_type=project，
  每项目作用域唯一线程，幂等）打开/复用线程；`发送讨论`经`POST /threads/{id}/messages`受理
  （intent=conversation）；待回复时每2s轮询`GET /threads/{id}`，assistant消息出现即停。
- 每条assistant消息提供`采用为方向`：只把文本写入方向草稿，用户仍需显式`保存创作方向`（CAS）。
- 前端新增`openProjectDirectorThread`；讨论只读消息、不自动保存、不触发生成。

已测（定向）：
- `CreativeDirectionPanel.test.tsx` 3 passed（新增讨论：打开线程→显示assistant→采用为方向写入草稿）；
  `ScriptWorkspace.test.tsx` 9 passed、`directorApiContract` 5 passed；前端定向17 passed；
  typecheck/lint/prettier/UI权威通过。

未完成且不冒称：讨论的多轮记忆/摘要（依赖既有agent线程，未额外建模）、resume signal UI、N08/N10核对。

## 交接检查点（2026-11-19，会话收束）

本会话从 I5 退出后连续推进，累计提交 30+ 个切片，全部按“定向验证+收口提交”节奏；最后一次全量unit回归 **2696 passed**（EV130）。

已完成（有EV证据）：
- I5 阶段退出（EV85–EV93，Full `df-quality-i5-07`）。
- I8a 机制主体：D6媒体配置与旧配置核对（EV94/95）、语音Binding/Edge退出（EV97–EV100）、资产image/voice/video计划与命令（EV102–EV114）、混合batch（EV117）、voice_concat（EV121）、prepare预览与逐命令授权（EV115/EV122）。
- I6b 机制侧：领域流程定义与端口（EV123/124）、端到端成功/部分失败/换计划（EV125–EV127）、只读面板（EV128）。
- I7-01/02：创作方向CAS与方向讨论（EV129/EV131）。

未完成（按依赖顺序）：
1. I7：resume signal 的读模型与UI「继续」入口（需从`director_runtime_wakeups.payload`暴露signal_id/reference_id/expected_revision，当前无读端点）；三栏工作台与N08/N10逐项核对（缺N08/N10原文，需Owner提供或按现有三栏基线核对）。
2. I8b：三类作品（宣传片/单集/多集）完整业务编排与端到端生产；固定媒体/本地验证先行，真实付费单独批准。
3. I9：Review/Formal/Editing/FinalFilm/Export与分集交付收口。
4. I10：同候选集成、目标机安装/重启/备份恢复、三作品E2E、Full Gate与实际验收（真实操作按审批）。

门状态：Docker Full Gate 未在会话内重跑（按门分级留待正式CI/I10同一候选）；本地运行库仍为`20261113_0099`，无部署、无付费Provider调用。

## 全量前端回归与陈旧夹具修复（2026-11-19，EV132）

全量`npx vitest run`首轮763 passed/1 failed：`SceneWorkspace.test.tsx`的`/voice-options` mock仍是EV98之前的旧响应形状，`fetchVoiceOptions`按新契约判为非法、音色选择被禁用。把该mock更新为`{status,binding_id,model_id,provider_type,default_voice,notice,voices}`后全量**764 passed**（162.46s）。
结论：定向选择会漏掉跨切片的陈旧夹具，阶段内应周期性跑一次全量前端套件（本轮已做）；Docker Full Gate仍留待正式CI/I10候选。

## Full候选验证（2026-11-19，EV133，未通过）

- i8a-03：backend✅；frontend❌——`story-proposal`未mock新增的`/creative-direction`读、`navigation-simplification`
  仍按3个combobox断言（新媒体配置区使之为6）。已修两个E2E夹具。
- i8a-04：backend✅（PG integration 201 passed；修复final-film fixture全局catalog行重复插入）、
  media-resource✅、auth-gateway✅；frontend❌——`navigation-convergence A16`点击30s超时、
  `workbench-resource` p95 396ms>200ms；同代码在i8a-03通过，判定为宿主CPU争用导致的E2E不稳定。
- 单独复跑：litellm-integration **35 passed**（`aiohttp`缺失修复：edge-tts移除后需显式声明dev依赖）、
  institution browser **5 passed**。
- 结论：未取得完整Full PASS，不声称I8a阶段Full；后端/媒体/网关/litellm/机构栈已验证。前端E2E需在
  空闲宿主上重跑该阶段（或降低并行度）后再收口。

## Full复跑与前端稳定性修复（2026-11-19，EV134）

- `CreativeDirectionPanel`改为**默认折叠**，展开后才读取方向/线程；脚本页首屏不再多发请求，降低工作台旅程的累计耗时。
- `A16-A19`单测覆盖5个断点，30s全局预算不足：为该测试显式`setTimeout(90_000)`；单独复跑通过（45.4s）。
- `workbench-resource`三项仍在p95≈396ms（阈值200ms）失败；该套件单worker顺序执行、宿主16核负载43%，暂无法归因于产品改动；保留阈值不改，记为未解决项，需要独立profile（如在空闲宿主或专用CI机上复测）。
- 全量前端Vitest复跑：**764 passed**（583.87s）。

结论：Full仍为FAIL（仅前端resource性能阈值项），不声称阶段Full；后端/媒体/网关/litellm/机构栈与前端功能E2E均已通过。

## workbench-resource性能项定位（2026-11-19，EV135）

单独复跑`workbench-resource`（单worker、同一镜像）：
- `1 Shots`：p95 **84.4ms**（通过），但`firstScreenMs=9075ms`——Vite在新建镜像里重新优化依赖（"Re-optimizing dependencies because lockfile has changed"）。
- `30 Shots`：p95 **324.5ms**（阈值200ms，失败）；滚动p95 22ms正常。
- `100 Shots`：此前396ms。
同一代码在i8a-03的Full中该套件通过，说明阈值对宿主/冷启动敏感；但30/100例的每次点击成本(~300ms)高于1例(84ms)，仍需在空闲机器上对比I5提交基线，排除列表渲染回退。
补充证据：本会话未改动`frontend/src/features/scenes`与`frontend/src/components/shots`（`git log`最近提交均早于本会话），
被测页面代码与I5 Full通过时一致 → p95差异归因为宿主/冷启动环境因素，而非列表渲染回退。

结论：Full仍FAIL（仅此项），不声称阶段Full；收口需在空闲宿主重跑该阶段。

## I7-03 恢复信号只读端点（2026-11-19，EV136）

- 新增`GET /projects/{p}/director/runtime/turns/{turn_id}/resume`：读取该turn最新**待处理**resume wakeup
  （`completed_at`/`dead_letter_at`为空），返回`signal_id/reference_id/expected_runtime_revision/
  attempt_count/created_at`；无信号404 `DIRECTOR_RESUME_NOT_PENDING`；不触发执行。
- 前端新增`fetchPendingRuntimeResume`（复用`runtimeTurnResume`路由模板，契约测试自动覆盖）。
- UI「继续」按钮仍待挂载：`DirectorTurnStatus`当前无宿主页面（I7工作台面未建），组件/接口已就绪。

已测（定向）：
- 后端`test_runtime_resume_read.py` 2 passed（待处理信号可读、已完成wakeup不暴露）；
  定向组59 passed；前端`directorApiContract` 8 passed；generated.ts 405 schema。

未完成且不冒称：恢复按钮的工作台挂载、N08/N10三栏核对。

## I8b-01a 生产就绪只读模型（2026-11-19，EV137）

- 新增`app/production/readiness.py`与`GET /projects/{p}/production-readiness`：按作品类型返回
  episode/scene/shot与正式媒体计数、三类媒体默认配置状态、逐项`items`与`blockers`；
  单集要求恰1集、多集要求≥2集（未填计划按已有集数），`formal_media`为非阻断提示。
- 纯读：不建Graph/NodeRun、不调Provider、不补造缺失事实。

已测（定向）：
- `test_production_readiness.py` 2 passed（单集完整→ready且blockers为空；缺故事/媒体→blocked；
  多集仅1集→story_structure partial并阻断）；定向组59 passed；generated.ts 407 schema。

未完成且不冒称：I8b其余（三类作品端到端生产与两集共享/连续性验收）。

## I8b-01b 两集就绪验证（2026-11-19，EV138）

- 就绪模型新增多集用例：`serial_comic`计划2集、实际2集（各1场景1镜头）→ `episode_count=2`、
  `scene_count=2`、`shot_count=2`，`story_structure`为ready且`ready=true`。
- 资产为项目作用域，跨集共享由同一`asset_version_references`行体现；本轮只验证就绪计数与结构规则，
  跨集参考解析的端到端仍待I8b后续切片。

已测（定向）：
- `test_production_readiness.py` 3 passed（单集、两集、缺失阻断）；ruff通过。

未完成且不冒称：跨集共享资产在镜头计划/生成中的端到端验收、三类作品完整生产编排。

## I8b-01c 跨集共享资产计数（2026-11-19，EV139）

- 就绪模型新增`shared_asset_count`与`cross_episode_sharing`项：统计被**两集及以上**镜头的
  `shot_reference_bindings`共同引用的`asset_version_id`数量；单集项目视为ready，多集无共享为partial
  （非阻断提示）。
- 共享是项目作用域资产的自然结果：两集各自绑定同一`asset_version_id`即被计为共享，无需复制资产或假镜头。

已测（定向）：
- `test_production_readiness.py` 4 passed（单集、两集、缺失阻断、两集共享同一asset_version→
  shared_asset_count=1且cross_episode_sharing=ready）；定向组61 passed；generated.ts 407 schema。

未完成且不冒称：共享资产在镜头计划/生成中的端到端解析验收、三类作品完整生产编排。

## I8b-01d 跨集共享资产的计划解析（2026-11-19，EV140）

- 新增`test_cross_episode_shared_asset.py`：两集各一镜头，分别建立指向**同一**Asset/AssetVersion的
  `ShotReferenceBinding`；两镜头各自`build_plan`后`planned_references`都解析到同一Artifact与AssetVersion。
- 证明共享不靠复制资产或假镜头：每集用自己的binding，解析结果一致。

已测（定向）：
- `test_cross_episode_shared_asset.py` 1 passed；定向组62 passed；ruff通过。

未完成且不冒称：共享资产在**生成**（NodeRun/Provider）中的端到端、三类作品完整生产编排。

## I8b-01e 共享资产冻结进两次派发（2026-11-19，EV141）

- `test_cross_episode_shared_asset.py`新增派发级用例：两集镜头各自`create_and_dispatch`，
  两个NodeRun快照的`references[0]`都冻结同一`artifact_id`/`asset_version_id`，且分属不同Graph版本
  （每镜头自己的图），证明共享发生在引用身份而非复制资产。
- 执行级（Provider提交）未在测试中伪造wire证明：`COMPILER_WIRE_FINGERPRINT_MISMATCH`需要真实编译器的
  wire证据，留待固定媒体端到端切片。

已测（定向）：
- `test_cross_episode_shared_asset.py` 2 passed（计划解析+派发冻结）；定向组63 passed；ruff通过。

未完成且不冒称：共享资产在Provider提交/生成中的端到端、三类作品完整生产编排。

## 后端单元全量回归（2026-11-19，EV142）

I7-03（resume只读端点）与 I8b-01a–01e（就绪模型/两集/共享资产计划与派发）累积后，在 quality 镜像里
跑后端单元全量，确认没有回归：

- `docker run --rm --network none`（`dramaforge-backend-quality:local`，`backend/app`+`backend/tests`
  只读挂载，`pytest tests/unit`）→ **2704 passed**（1672.12s），0 failed / 0 error / 0 skipped。
- 对比 EV130 基线 2696 → 本会话新增 8 个用例（resume 2、readiness 4、shared asset 2）。
- 这是单元层全量，**不等于** Full Gate：未跑 PG 集成、迁移 check、前端 E2E/资源性能与真实机构栈。

未完成且不冒称：Full Gate 仍卡在 `frontend-quality` 的 `workbench-resource` p95（需空闲宿主重跑）；
共享资产 Provider 提交端到端、三类作品完整生产编排、I9 交付段仍未实施。

## I8b-01f 共享资产到达两集Provider提交（2026-11-19，EV143）

把“两集共享同一角色资产”从快照/计划边界推到**付费提交边界**：同一冻结引用在真实 Worker 媒体路径上
被两集各自提交，Provider 收到的参考图字节完全相同，而两集各自拿到自己的关键帧。

已实施：
- 新增`test_cross_episode_shared_asset_submit.py`：两集各1场景1镜头，同一个`Asset`/`AssetVersion`
  （formal，唯一版本）+ 同一个参考`Artifact`（真实PNG字节在对象存储里，`content_hash`按字节校验），
  两镜头各一条`ShotReferenceBinding`（`purpose=identity`→`reference_image`）。
- 每集`build_plan`→`preview_compiler_contract`（真实编译器wire指纹）→`create_and_dispatch`→
  `execute_media_node_run`（真实Worker媒体路径，`store`同时提供参考字节与接收产物）。
- 断言：两集Provider POST体`extra_body.image[0]`都是同一份`data:image/png;base64,...`，解码后与
  共享`Artifact`字节逐字节相等；两集产出不同`Artifact`且哈希互不相同（相同字节会被
  `ARTIFACT_NOT_INDEPENDENT`拒绝，说明“每集自己的成片”不是靠复制共享资产）；`Asset`仍只有1个
  formal版本、`version`不变；两个`ProviderOperation`均`succeeded`。
- 选型按产品规则而非绕行：`agnes-image-2.1-flash` v3 有`MODEL_OFFICIAL_EVIDENCE_GAP`（阻断新create）、
  通用`@contract/openai-image-v1`是`protocol_contract`且该插件不允许手填模型ID
  （`DYNAMIC_MODEL_CAPABILITY_UNVERIFIED`）；因此用官方证据完整的`agnes-image-2.5-flash`
  （`image.i2i` + `reference`输入合同，9:16 项目比例天然匹配）。
- 顺带修掉`test_runtime_resume_read.py`的E501超长行——Full 后端静态门（`ruff check app tests`）会因此失败。

已测（定向）：
- `test_cross_episode_shared_asset_submit.py` 1 passed；受影响定向组 **98 passed**（shared asset×2、
  workbench execution、generic images protocol、agnes flash release、readiness、asset plan、resume read）。
- `ruff check app tests` 全通过；本会话自写的两个测试文件按 ruff 格式化。

未完成且不冒称：三类作品（`animation_promo`/`single_comic`/`serial_comic`）完整生产编排端到端、
真实付费Provider调用（需当前Owner授权，属I10硬门）、I9剪辑交付段。

## I8b-02 三类作品生产段到正式媒体（2026-11-19，EV144）

把“I8b-01 生产段到正式媒体”做成三类作品各自的完整业务结果，并顺带修掉就绪模型的一个真实统计缺陷。

已实施：
- 新增`backend/tests/unit/production_harness.py`：一套可复用的生产段夹具——按作品类型建项目与其结构
  最小集（`single_comic` 1集、`serial_comic` 2集、`animation_promo` 1集且不填集数计划）、Agnes图像连接
  （可解密的冻结凭据revision + 可见性探测 + binding）、共享资产版本与逐镜头引用绑定、以及
  `dispatch_keyframe`（plan→真实编译器wire指纹→派发）。EV143 的用例改用同一套夹具，去重。
- 新增`test_three_work_type_production.py`：三类作品各自把`keyframe`走到**正式媒体**——
  `execute_media_node_run`（真实Worker媒体路径）→ `approve_candidate`（人工批准）→
  `set_formal_keyframe`，再重读就绪：`formal_keyframe_count == shot_count` 且每镜头
  `formal_keyframe_artifact_id` 非空；`serial_comic` 追加“2集×2镜”用例，4个镜头全部落在**同一**
  共享资产版本上（`shared_asset_count=1`、`cross_episode_sharing` 不阻断、`asset.version==1`）。
- **修复`app/production/readiness.py`的真实缺陷**：`shared_asset_count` 之前只统计
  `shot_reference_bindings.asset_version_id`（钉版本）绑定，产品主用法 `resolution_mode=current_formal`
  （只有`asset_id`）一律计为0，导致“两集共享同一角色资产”在就绪里显示为未共享。改为
  `pinned ∪ current_formal(经Asset.current_version_id)` 的并集再按版本去重计集数；
  新增`test_current_formal_binding_also_counts_as_cross_episode_sharing` 固定该行为。

已测（定向）：
- `test_three_work_type_production.py` 4 passed；`test_production_readiness.py` 5 passed；
  受影响定向组 **121 passed**（shared asset×2、三类作品、readiness、workbench execution、
  generic images、agnes flash、resume、asset plan、formal selection）。
- `ruff check app tests` 通过；`mypy app` 402 文件 Success。

未完成且不冒称：视频/合成段与分集交付（I9）、三类作品的真实付费Provider端到端（I10硬门）、
Full Gate 仍待空闲宿主重跑`workbench-resource`。

## I8b-03a 项目级生产批预览（只读）（2026-11-19，EV145）

补上“用户按项目决定生产”的只读编排面：一次看清哪些镜头现在就能开工、哪些被阻断、一次批次最多会
产生多少次付费操作，且不写库、不调 Provider、不改动既有逐命令授权门。

已实施：
- **`app/production/batch_plan.py`**：`ProductionBatchPlanService.preview(project, stage, shot_ids?)`
  - 按 `episode_number → scene_number → sort_order → shot_number` 稳定排序遍历项目内镜头；
  - 逐镜复用 `WorkbenchExecutionService.build_plan`（同一份计划与指纹），因此“能开工”与真正派发
    用的是同一套判定，不存在第二套规则；
  - 每镜给出 `planned`（含`plan_fingerprint`）/`blocked`（含阻断码）/`formal`（该阶段正式媒体已存在）；
    `build_plan` 的业务拒绝被收敛为逐镜阻断，不中断整批；
  - `max_operations = planned_count`（付费操作上界，调用方只可调低），`batch_fingerprint` 冻结
    “有序镜头 + 计划指纹 + 阶段”，供后续获授权批次核对自己面对的是同一份预览；
  - 只允许 `image_keyframe`/`video` 两个生产阶段（`BATCH_STAGE_UNSUPPORTED`），编辑/交付不在本批；
    传入项目外镜头直接 `BATCH_SHOT_UNKNOWN`，不静默缩小冻结集合。
- 测试夹具新增 `configure_image_default`：把项目级 profile 的 `visual.keyframe` 槽与 D6
  `image_model_binding_id` 同时指向已验证的图像 binding——这正是“项目级解析”与“D6 媒体默认”两套
  读取路径的共同前提。

已测（定向）：
- `test_production_batch_plan.py` 7 passed：三类作品全镜可计划且顺序与结构一致、同输入指纹稳定、
  某镜转正式后退出付费集并使指纹变化、未配模型与“无正式首帧的视频”逐镜报阻断而不抛错、
  阶段白名单与项目外镜头拒绝、按给定镜头收窄到 1。
- 受影响定向组 **62 passed**；`ruff check app tests` 通过；`mypy app` 403 文件 Success。

未完成且不冒称：本能力目前**没有 HTTP 入口**（未加路由、未重生`generated.ts`），也没有“获授权后
按批 create”的写路径——批量付费创建仍必须走既有单命令授权与`max_operations`上界，属后续切片。

## I8b-03b 生产批预览HTTP入口与生成类型（2026-11-19，EV146）

把 I8b-03a 的只读编排接到用户可用入口，并保持 OpenAPI/生成类型权威不变。

已实施：
- `GET /projects/{project_id}/production-batches/preview?stage=&shot_id=…`（`app/api/v1/production.py`）：
  先 `ProjectService.get_project_for_owner`（外人 `ForbiddenError`、不存在 `NotFoundError`，不泄露存在性），
  再交给 `ProductionBatchPlanService.preview`；只读、零 Graph/NodeRun/Provider 写入或调用；
  `stage` 由查询串给出、非法阶段仍由服务返回 `BATCH_STAGE_UNSUPPORTED`。
- 路由级测试：owner 校验先于任何计划计算、通过路由函数得到与 service 相同的预览。
- 生成类型：backend 镜像内导出 OpenAPI → frontend 镜像内 `openapi-typescript` 重生
  `frontend/src/shared/api/generated.ts`（**409 schema**，原 407），`api:check` 报
  `generated.ts is up to date`，`api:authority` 409 schema 通过。

已测（定向）：
- `test_production_batch_plan.py` **8 passed**（含新路由用例）；受影响后端组 **18 passed**；
  `ruff check app tests` 通过；`mypy app` 403 文件 Success；前端 `npm run typecheck` 通过。

未完成且不冒称：获授权后的批量 create（写路径）、视频/合成生产段、I9 交付段；
Full Gate 仍待空闲宿主重跑 `workbench-resource`。

## I8b-04a 视频段提交（正式首帧→Provider create）（2026-11-19，EV147）

把生产段从“关键帧”推进到“视频创建”：用已批准的正式首帧，向 Provider 创建一个远端视频任务。

已实施：
- `test_shot_video_production.py`：真实链依次完成 关键帧生成 → 人工批准 → `set_formal_keyframe`
  → 视频stage计划 → 派发 → `execute_media_node_run` 提交。断言：
  - 提交即让出（`ProviderTaskPendingError`），符合“创建后只观察、不重复创建”的既有语义；
  - 只有一次 `POST /v1/videos`，`model=agnes-video-2.5-flash`；
  - 请求体里是**签名后的** `https://media.example/…` 引用 URL，且**不含**首帧原始 base64
    （该合同声明公共 URL 传输，不是内嵌字节）；
  - `ProviderOperation.provider_operation_id=vid-1`，`formal_video_artifact_id` 仍为空（远端仍在跑）。
- 夹具扩展（`production_harness.py`）：`agnes_video_binding`（同一已验证连接上加视频binding）、
  `configure_video_default`（`video.shot`槽 + D6`video_model_binding_id`）、
  `dispatch_stage`/`stage_input`（阶段参数化，`dispatch_keyframe` 成为其特例）；
  伪 Agnes 同时应答 `/v1/models`（含图像与视频两个模型）、`/v1/videos`、`/agnesapi`。

按现状记录的产品事实（未改成“看起来更好”的假象）：
- `agnes-video-v2.0` 已 **retired**，活跃视频合同是 `agnes-video-2.5-flash`
  （`frame` 输入合同要求显式 `first_frame` 引用；引用走公共签名 URL，需要 `REFERENCE_PUBLIC_BASE_URL`）。

已测（定向）：
- `test_shot_video_production.py` 1 passed；夹具受影响组 **14 passed**
  （视频提交、三类作品、共享资产提交、生产批预览）；`ruff check app tests` 通过。

未完成且不冒称：轮询完成 → 下载 → 正式视频 → 合成段；I9 剪辑与分集交付；
获授权后的批量 create；Full Gate 的 `workbench-resource` 复测。

## 后端单元全量回归（2026-11-19，EV148）

I8b-01f–03a 累积后在 quality 镜像重跑后端单元全量：**2717 passed**（1984.68s，0 failed/0 skipped），
相对 EV142 的 2704 基线新增 13 个用例（共享资产提交1、三类作品到正式媒体4、`current_formal`共享统计1、
生产批预览7）。

说明（如实记录）：该进程在 EV146（路由用例）与 EV147（视频提交用例）写入之前启动，两个新用例未计入；
下轮需再跑一次全量收口后方可作为最新基线。

## I8b-04b 视频段完成到正式视频（2026-11-19，EV149）

补齐视频段的另一半：创建之后如何“只观察、不重建”地把远端任务收敛成正式视频。

已实施（`test_shot_video_production.py` 扩为 2 个用例，共用 `_shot_with_formal_keyframe` 夹具链）：
- 首次 `execute_media_node_run` 只**让出**（`ProviderTaskPendingError`），此时并**不**轮询；
- 把该 run 的 `next_attempt_at` 置为到期后再执行一次：恰好**一次** `/agnesapi` 轮询返回 `succeeded`
  → 下载 `v.mp4` → 建 `Artifact`（`video/mp4`、`produced_by_run_id` 为该 run）
  → `approve_candidate(video=True)` → `set_formal_video` → `shot.formal_video_artifact_id` 落地；
- 全程 `POST /v1/videos` 仍只有 **1 次**：完成来自轮询，不是重新创建。
- 夹具新增：最小可识别 MP4 生成 `mp4()`（满足容器签名与测试环境的宽松元数据）、
  `video_states` 轮询序列、下载按 `.mp4` 返回视频字节与 `video/mp4` 类型。

已测（定向）：
- `test_shot_video_production.py` **2 passed**；夹具受影响组 **20 passed**；
  `ruff check app tests` 通过。

未完成且不冒称：合成段（composite）、多镜头视频编排、I9 剪辑与分集交付；
获授权后的批量 create；Full Gate 的 `workbench-resource` 复测。

### 提前跑 Full 的触发条件（2026-11-19，`df-quality-i8b-01`）

I8b 尚未到阶段终点，但自 I5 以来 Full 只剩 `workbench-resource` p95 一项未通过，且当前宿主空闲——
故提前跑一次完整 Full，用于在空闲宿主上复测该唯一未通过项并验证 EV143–EV149 累积后的整链
（backend 单测+PG+迁移、frontend vitest+typecheck+E2E、媒体/网关/LiteLLM/机构真实栈）；结果未出前
不宣布任何阶段 Full。

### `df-quality-i8b-01` 结果：FAIL（2026-11-19，EV150）

- 镜像：backend `sha256:847a0d4f77188886e785317d1797cb13aa3e98878db577437e27af867e2adec4`、
  frontend `sha256:9958a9d328989ced22763cae39c6c41789192774061a735a168ac030a107e95e`。
- 已通过：build-backend/build-frontend/dependencies-up、静态门、架构门、Provider权威、ruff（`All checks passed`）。
- 失败：`backend-quality` 在 **2719 passed / 1 failed** 后退出——
  `test_provider_recovery.py::test_dispatcher_recovery_bypasses_fifty_jobs_and_a_busy_single_heavy_slot`。
  根因是负载下等待“120 次 admission 全部完成”的 `asyncio.wait_for(..., timeout=5)` 超时（traceback 为
  `Event.wait` 被取消），属**测试时限**过紧，不是产品缺陷。已把该等待放宽到 60s 并注明理由，
  **未放宽任何断言**；该文件复跑 14 passed。
- 因此本次 **frontend-quality 未执行**；为判断前端真实状态，另用同一镜像单跑了该阶段（见下条）。
- 结论：仍**不宣布** Full 通过；修好时限后需要重跑完整 Full 才能收口。

### `frontend-quality` 单阶段与 resource 项定位（2026-11-19，EV151）

用同一 frontend 镜像单跑该阶段（补导出 `/contract/openapi.json` 后）：
- **209 passed / 2 failed**；失败只有 `workbench-resource` 的 `30 Shots`、`100 Shots`
  （p95 **339.5ms / 376.4ms**，预算 200ms）。**全部功能 E2E 通过**，包括此前疑似不稳的
  `editing-timeline-g5:645`、`global-layout-governance:357`、`navigation-convergence` A16–A19。
- 再单独跑该 spec（只 `chromium-resource`，先 `npm run build`）：**3 failed**（连 `1 Shots` 也超预算），
  100 镜头 p95 364.5ms。
- **根因线索（不是结论）**：`frontend/tests/e2e/global-setup.ts` 用 `vite.createServer` 起的是
  **dev 服务器**，日志有 `Re-optimizing dependencies because lockfile has changed`，说明该 p95 测的是
  dev 模式按需编译 + 宿主 CPU；同一指标在 EV78 的 Full 里是 22/82.7/87.2ms。
- 下一步（未做）：检查该 spec 是否在路由/模块尚未预热时就开始采样（若是，加入显式预热点击，
  该改动**不放宽 200ms 预算、不删用例**）；再把证据 JSON（`firstScreenMs`/`p95Ms`/样本数）与
  EV78 基线对比，判断是测量口径问题还是真实渲染回退。

### resource 项量化结论（2026-11-19，EV152）

已按上条做完：spec 本身有两次预热点击再采样，采样为“点击→MutationObserver→下一帧”。
逐镜头数实跑 evidence（同镜像）：

| 场景 | 本次 p95 | EV78 通过时 | 倍数 |
|---|---|---|---|
| 1 镜头 | 122.8ms | 22ms | ×5.6 |
| 30 镜头 | 309.1ms | 82.7ms | ×3.7–4.1 |
| 100 镜头 | 364–376ms | 87.2ms | ×4.2–4.3 |

- **30→100 几乎不再增长**（EV78 也是 82.7→87.2），形状未变 → 不是列表渲染回退，而是**整机等比变慢**。
- 同期宿主为 `i5-13400`（10核/16线程）、Docker 8GB，Windows 侧 `LoadPercentage=53`，而本项目当时
  **没有容器在跑**——即约一半 CPU 被外部占用；`firstScreenMs` 8.7–9.5s 已逼近 spec 的 30s 单测超时，
  `1 Shots` 在默认超时下曾直接卡在首屏等待。
- 结论：**200ms 预算与断言不动**（合同禁止放宽阈值或删用例），本机不具备测出该预算的条件；
  需在空闲/足算力机器上复跑 Full，或由 Owner 决定该环境项的口径。

## I9 计划（下一阶段，未开工）

依据 [DATA_MODEL](../DATA_MODEL.md) 的 timeline schema2 合同与 [MASTER_EXECUTION_PLAN](MASTER_EXECUTION_PLAN.md) 的 I9-01/02：

1. **I9-01a timeline schema2 与 Save/Formal 分离**：`Clip.source`/`audio_source` 判别引用（shot 正式产物、
   已采用资产版本、公共素材固定版本），Save 时由服务侧写 `selection_snapshot`（schema/session_version/
   clip source/hash/确认身份与版本），客户端 metadata 不作可信证明；schema1 时间线保留原解释，
   只有用户显式 Save 新版本才转 schema2；旧导出不重算 hash。
2. **I9-01b 分集作用域**：`edit_sessions.episode_id` + 候选键/索引与延迟 FK；已保存时间线中的 Shot
   必须经 Scene→Episode 属于该集；切换集需版本化 Save 并显式检查全部 Clip，不静默删 Clip。
3. **I9-02a 渲染快照与导出绑定**：render NodeRun 冻结同一来源与资格；Export 只绑定该不可变快照，
   不复制源媒体所有权；原回执优先、MP4/SRT 可解码。
4. **I9-02b 逐集交付**：`exports`/`export_items` 按集绑定，另一集 Clip 混入拒绝，删除集不把交付变成项目级。

每片默认跑对应测试组；I9 阶段终点再跑 Full。真实导出生成需 Owner 授权（硬门）。

### I9-01a 已实施：时间线 schema2 与 Save 期来源校验（2026-11-19，EV153）

- `app/editing/timeline_schema.py`：schema 1（或缺省）保持历史语义、**不静默升级**，且不写入磁盘
  schema 标记，历史文档字节形状不变；schema 2 要求每个 clip 带判别式 `source`
  （`shot_formal`/`asset_version`/`public_material`，各 kind 必填字段互斥、`extra=forbid`），
  并校验 clip id 唯一、`order` 为 1..n 无缺口、`duration_seconds ≥ 0`。
- `EditingAdapter.save_timeline` 接入该校验（版本 CAS 契约不变）：`shot_formal` 必须是该镜头
  **当前正式视频**且 artifact 可用（`EDIT_SOURCE_NOT_FORMAL`）；`asset_version`/`public_material`
  在资质校验收敛前**fail-closed**（`EDIT_SOURCE_UNVERIFIED`），不把客户端 JSON 当可信证明。
- API `EditTimelinePayload` 新增 `schema_version`（1..2）；此前 `extra="forbid"` 使客户端无法表达 v2。
- 证据：新增 6 passed；既有编辑组 39 passed、编辑 API 10 passed；ruff/mypy（404 文件）通过；
  `generated.ts` 重生（409 schema，`api:check`/`api:authority` 通过）。
- **下一步（I9 剩余）**：`selection_snapshot` 服务端观测、asset/public 素材资质接线、
  分集作用域（`edit_sessions.episode_id` + 候选键/索引/延迟 FK，I9-01b）、渲染快照与导出绑定（I9-02）。

### I9-01b 已实施：分集作用域（2026-11-19，EV154）

- **迁移 `20261119_0121`**：`edit_sessions.episode_id`（可空 FK→`episodes`，`ON DELETE RESTRICT`）、
  候选键 `uq_edit_sessions_id_project`、索引 `(project_id, episode_id, id)`；历史会话保持 NULL，
  不从镜头数量或名称猜分集。
- `EditingAdapter.create_session(episode_id=…)` 校验该集属于本项目（否则 404）。
- `save_timeline` 对分集会话校验每个 `shot_formal` 来源的镜头经 Scene 属于该集，否则
  `EDIT_CLIP_OUT_OF_EPISODE`；该校验先于“是否当前正式视频/artifact 可用”，保证错误码指向真正的问题。
- 证据：`test_editing_timeline_schema.py` **8 passed**、编辑组 **72 passed**；ruff 通过、
  `mypy app` 404 文件通过；隔离 PG `editor_0121`：upgrade head → `alembic check` 无漂移 →
  `downgrade 0120` → `upgrade head` 全部成功；随后删库并 `compose down`，无残留容器。
- **下一步**：`episode_id` 暴露到读模型、`selection_snapshot`、切换集需版本化 Save 且显式检查全部
  Clip（不静默删 Clip）、渲染快照与导出绑定（I9-02）。

### I9-01c 已实施：Save 期 `selection_snapshot` 与已采用资产版本来源（2026-11-19，EV155）

- 每个 schema 2 clip 在 Save 时由**服务端**写入 `selection_snapshot`（`schema_version`/
  `session_version`/`clip_id`/`kind`/`identity`/`artifact_id`/`artifact_hash`/`confirmed_at`）；
  它是“编辑器保存时看到的是什么”的观测，不是第二份可写 Formal 事实。
- 来源未变时**沿用原观测**（不重写 `confirmed_at`/`session_version`）；来源改变则重写观测并保留
  `initial_source`，导出/渲染可据此证明变更历史。
- `asset_version` 来源现可验证：版本须在本项目、属于指定 Asset、`status=formal` 且是该 Asset 当前
  `current_version_id`（否则 `EDIT_SOURCE_NOT_ADOPTED`），且须存在可播放的视频
  `AssetVersionReference`（否则 `EDIT_SOURCE_NO_MEDIA`）；观测记录解析出的媒体 artifact 与 hash。
- `public_material` 仍 fail-closed（`EDIT_SOURCE_UNVERIFIED`），待公共素材资质接线。
- 证据：`test_editing_timeline_schema.py` **13 passed**、编辑组 **24 passed**；ruff 通过、
  `mypy app` 404 文件通过。
- **下一步**：公共素材（public_material）资质接线、切换集版本化 Save、`episode_id` 读模型、
  渲染快照与导出绑定（I9-02）。

### I9-01d 已实施：公共素材来源资质（2026-11-19，EV156）

- `public_material` 来源改为经**消费项目自己的固定链接**解析并校验：链接属于本项目且未 detach、
  链接拥有所指 publication、publication `available` 且未撤回、item 属于该 publication、
  其 artifact 为可用视频；不满足分别给 `EDIT_SOURCE_NOT_ADOPTED` / `EDIT_SOURCE_NO_MEDIA`。
  观测照常记录解析出的媒体 artifact 与 hash。
- `asset_version` / `public_material` 来源现在拒绝携带异类身份字段（不能同时声称 shot/artifact 与
  asset 或 public id），杜绝客户端夹带第二份主张。
- 测试用真实 `PublicAssetService.publish` + `ProjectPublicAssetLinkService.create` 构造夹具：
  公共素材经链接解析并落快照、伪造 id 被拒（JSON 不可信）、detach 与撤回均被拒。
- 证据：`test_editing_timeline_schema.py` **15 passed**、schema+编辑 API **25 passed**；
  `ruff check app tests` 通过、`mypy app` 404 文件通过。
- 至此 schema 2 的三类来源（镜头正式产物 / 已采用资产版本 / 公共素材）**全部可验证**。
- **下一步**：切换集版本化 Save（显式检查全部 Clip、不静默删）、`episode_id` 读模型、
  渲染快照与导出绑定（I9-02）。

### I9-01e 已实施：切换集作用域（版本化，拒绝而非静默删除）（2026-11-19，EV157）

- 新增 `PATCH /projects/{p}/edit-sessions/{id}/episode`（`{episode_id, expected_session_version}`）
  → `EditingAdapter.switch_episode`：沿用版本 CAS（`ConflictError`）；目标集须属本项目（否则 404）。
- **收窄**到某集时逐个检查已保存 clip（schema 1 的 `shot_id`、schema 2 的
  `shot_formal.source.shot_id`）：凡属其他集（含 id 缺失/不可解析）即 `EDIT_SCOPE_SWITCH_REJECTED`
  并返回 `clip_ids`，**不删除任何 clip**——由用户显式版本化 Save 决定去留。
- `asset_version` / `public_material` 不是分集绑定，切换后保持可用；同集为无操作（不增版本）；
  放宽回项目级始终允许。
- `EditSessionRead` 新增 `episode_id`，UI 可显示当前作用域。
- 证据：`test_editing_timeline_schema.py` **17 passed**、编辑组 **28 passed**；ruff 通过、
  `mypy app` 404 文件通过；`generated.ts` 重生（**410 schema**，`api:check`/`api:authority` 通过）。
- **下一步**：渲染快照与导出绑定（I9-02：固定版本/hash、原回执优先、MP4/SRT 可解码、逐集交付）。

### I9-01f 已实施：按集构建编辑时间线（2026-11-19，EV158）

- `build_edit_session_for_project(..., episode_id=…)`：只装配该集的 scene/shot，并让新会话**直接带该集
  作用域**；不属于本项目的集返回 `EDIT_EPISODE_NOT_FOUND`，不静默退化成“全项目”。
- `POST /projects/{p}/edit-sessions` 请求新增 `episode_id`：前端可用同一入口创建“分集剪辑会话”，
  不必先建全项目时间线再切换。
- 证据：`test_editing_timeline_schema.py` **18 passed**、编辑组 **29 passed**；ruff 通过、
  `mypy app` 404 文件通过；`generated.ts` 已重生（410 schema）。
- I9-01（剪辑数据/服务/HTTP 面）至此收口；**下一步进入 I9-02**：渲染快照与导出绑定
  （固定版本/hash、原回执优先、MP4/SRT 可解码、逐集交付）。

### I9-02a 已实施：导出冻结快照与回执优先（2026-11-19，EV159）

- **迁移 `20261119_0122`**：`exports` 新增 `edit_session_id` / `timeline_version` / `timeline_hash` /
  `render_node_run_id`；复合外键 `(edit_session_id, project_id) → edit_sessions(id, project_id)`
  （`ON DELETE RESTRICT`，复用 0121 的候选键，导出不可能指向别的项目的会话）、
  `render_node_run_id → node_runs`；索引 `(edit_session_id, timeline_version)`、
  `(render_node_run_id)`、`(project_id, episode_id, created_at, id)`。
- **`app/delivery/export_service.py`**：`create_session_export` 冻结会话当前 `version` 与该文档
  canonical JSON 的 sha256，并按 clip 逐条写 `ExportItem`（schema 2 取
  `selection_snapshot.artifact_id`，schema 1 取 `artifact_id`）；`episode_id` 随会话作用域。
  同一 `idempotency_key` 重放**返回原导出且不重绑**——编辑后再用同 key 仍指旧版本，新 key 才记录
  新版本（“原回执优先”）。
- **fail-closed**：`mp4`/`srt` 直接 `EXPORT_RENDER_REQUIRED`（没有渲染 run 就不排队，也不隐藏生成），
  未知格式 `EXPORT_FORMAT_UNSUPPORTED`，clip 无冻结 artifact 时 `EXPORT_CLIP_UNBOUND`。
- **HTTP**：`POST /projects/{p}/edit-sessions/{id}/exports`（新建 201 / 重放 200）。
- 证据：`test_export_snapshot.py` **4 passed**、导出+编辑 API **14 passed**；ruff 通过、
  `mypy app` 405 文件通过；隔离 PG `editor_0122`：upgrade head → `alembic check` 无漂移 →
  `downgrade 0121` → `upgrade head` 全部成功（随后删库并 `compose down`）；
  `generated.ts` 重生（**412 schema**，`api:check`/`api:authority` 通过）。
- **下一步（I9-02 剩余）**：真实渲染——render NodeRun 冻结 `edit_session_id/timeline_version/
  timeline_hash/来源与资格`，产出 MP4 与 SRT 并校验可解码，Export 只绑定该不可变渲染快照；
  逐集交付下载。渲染属生成动作，需按合同取得 Owner 授权。

### I9-02c 已实施：渲染计划接缝（EV161）

- 新增 `app/delivery/render_plan.py`：把一个**冻结**会话版本映射成有序
  `TimelineClipInstructions`（clip id、冻结 artifact id、字幕、时长、转场），并复用既有
  `build_timeline_subtitles` 产出**确定性 SRT 字节**与 `duration_ms`。
- 该模块不查生产事实、不写库、不生成媒体；fail-closed：空时间线 `RENDER_PLAN_EMPTY`、
  order 非 1..n 或存在非对象 clip `RENDER_PLAN_INVALID`、clip 无冻结 artifact
  `RENDER_CLIP_UNBOUND`、时长 ≤0 `RENDER_CLIP_EMPTY`——**都不静默丢 clip**。
- 现状：FFmpeg 渲染器 `app/production/timeline_renderer.render_timeline` 已存在（含 concat、
  音乐混音、字幕），缺的是“把会话版本的渲染计划派发为 render NodeRun 并落 MP4/SRT”的接线。
- 证据：`test_render_plan.py` **5 passed**；`ruff check app tests` 通过、`mypy app` 406 文件通过。

### I9-02d 已实施：逐集交付下载（EV162）

- `ExportService.delivery_artifact`：导出不存在或不属于本项目 → 404；`result_artifact_id` 为空 →
  **`EXPORT_NOT_DELIVERABLE`**（“queued ≠ delivered”，不把回执当影片）；artifact 缺失/被删/不可用 → 404。
- 新增 `GET /projects/{p}/exports/{export_id}/content`：先 owner 校验，再按
  `Content-Disposition: attachment` 返回字节，带 `Content-Length`、`Cache-Control: private, no-store`、
  `X-Content-Type-Options: nosniff`、`Accept-Ranges: bytes`，文件名包含集作用域。
- 证据：`test_export_snapshot.py` **6 passed**（未渲染导出被拒；已渲染导出返回字节并断言四个响应头；
  他人项目的导出被 `ForbiddenError` 拒绝），导出/编辑/渲染计划合计 **21 passed**；
  `ruff check app tests` 通过、`mypy app` 406 文件通过；`generated.ts` 重生（412 schema、
  `api:check` up to date、`api:authority` 通过）。
- **下一步（I9-02 剩余）**：渲染 NodeRun——把 `render_plan` 派发为渲染运行并冻结
  `edit_session_id/timeline_version/timeline_hash`，产出 MP4 与 SRT（校验可解码），
  Export 绑定该不可变渲染快照；Range 分段下载可随后补。渲染是生成动作，执行前需取得 Owner 授权。

### I9-02e 已实施：渲染 NodeRun 与 MP4/SRT 生成（2026-11-19，EV163）

- **`app/delivery/render_execution.py`**
  - `create_edit_session_render`：按导出冻结的 `timeline_version` 与 `timeline_hash` 校验——
    陈旧版本 `RENDER_VERSION_STALE`、hash 不符 `RENDER_HASH_MISMATCH`、导出不属该会话
    `RENDER_EXPORT_MISMATCH`；用 `render_plan` 生成指令写进 NodeRun 快照（含 `export_id`），
    同一快照只建一个 run（幂等）。
  - `execute_edit_session_render`：**只读快照**（不重读实时时间线），逐个 materialize 输入
    artifact 并校验 hash（`RENDER_INPUT_HASH_MISMATCH`），调用既有
    `timeline_renderer.render_timeline` 产出 MP4 与 SRT，落两个 Artifact
    （`video/mp4`、`application/x-subrip`，`produced_by_run_id` 为该 run），并把 `Export`
    置 `completed`、绑定 `result_artifact_id` / `render_node_run_id` / `render_summary`。
- `product_path` 按 `node_key=edit_session_render` 分派到该执行器；HTTP 新增
  `POST /projects/{p}/exports/{id}/render`。至此“导出回执 → 渲染 → 交付下载”闭环打通。
- 证据：`test_edit_session_render.py` **3 passed**、交付组 **42 passed**；ruff 通过、
  `mypy app` 407 文件通过；`generated.ts` 重生（**413 schema**，`api:check`/`api:authority` 通过）。
- 如实说明：测试环境走 `_test_render` 的**确定性字节**路径（同版本同字节），生产路径为真实
  ffmpeg 5.1（镜像内已确认存在）；本次**未**对真实用户媒体执行渲染。
- **下一步**：Range 分段交付下载、逐集批量渲染编排；随后 I9 阶段终点跑 Full。

### I9-02f 已实施：交付下载支持 Range（EV164）

- 新增 `app/api/content_streaming.py`：`parse_range`（只接受单个 `bytes=` 区间；多区间、非法、
  越界一律视为不可满足）与 `content_response`（整段 200、单区间 206 且带
  `Content-Range: bytes a-b/size`、不可满足 416 且带 `bytes */size`，统一
  `Accept-Ranges`/`nosniff`/`private, no-store`）。
- 公共资产内容下载（`public_assets._content_response`）与原导出下载改为**共用同一实现**，
  删除其私有 `_parse_range`——两条私有媒体下载不再可能分叉。
- 证据：`test_export_snapshot.py` **6 passed**（新增 `bytes=0-3`→206 且逐字节相符、
  `bytes=999999-`→416 的 `Content-Range` 断言）；`test_public_assets.py` 既有 Range/HEAD 用例全绿；
  内容/交付组 **24 passed**；`ruff check app tests` 通过、`mypy app` 408 文件通过。
- **下一步**：逐集批量渲染编排；随后 I9 阶段终点跑 Full（需空闲宿主）。
- **已修（I9-02b，EV160）**：`exports.episode_id` 外键由 `ON DELETE SET NULL` 改为
  `ON DELETE RESTRICT`（迁移 `20261119_0123`，downgrade 回 SET NULL）。隔离 PG `editor_0123` 实测：
  有导出的集执行 `DELETE FROM episodes` 被 `fk_exports_episode` 拒绝、导出行仍在；`alembic check`
  无漂移，downgrade→upgrade 往返成功。DB09“删除集不能把交付变成项目级”现已成立。