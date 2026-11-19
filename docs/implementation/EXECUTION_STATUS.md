# 机构版执行状态

更新：2026-11-19。此文件是本长期任务唯一执行状态，产品/架构规则仍由 [CURRENT](../CURRENT.md) 导航；本目录是合同12明确要求的执行管理材料，不是第二套架构宪法。

## 当前阶段与批次

当前：I4已按机制退出（EV72–EV84；无过滤Full `df-quality-i4-03-a/b/c2/d` 连续通过）。I5-01与I5-02各切片已交付（EV85–EV92），I5阶段终点Full `df-quality-i5-03` exit0通过（2690单测、204 PG、366 schema、757 Vitest、211 E2E，清理无残留）。I5暂不宣布阶段退出：`source:"public"`已进绑定/解析/token，但Production计划编译仍只消费私有Artifact解析结果，完成该片后复跑Full再判定。
按批次计：已完成14/26（I0-01/02、I1-01/02、I2a-01/02、I3-01/02、I2b-01、I6a-01、I4-01/02/03、I5-01）；未完成12（I5-02尾片、I8a-01/02/03、I6b-01、I7-01/02、I8b-01、I9-01/02、I10-01/02）。
D8冻结基线D8-20261117-r1保持，目标仍为完整I0–I10。

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

## 已完成与未完成

已完成：D0–D8设计收敛与冻结（D8-20261117-r1）；I0工程基线（EV50）；I1-01项目类型/目标/分集约束（EV51/EV52）；I1-02原件版本与不可变解析快照（EV53/EV54）；I2a-01 MasterRun/计划/控制回执（EV55–EV57）；I2a-02运行控制短事务与迟到写围栏（EV58/EV59）；I3-01外发策略与目的地管理面（EV60/EV61）；I3-02外发准入强制与来源用途（EV62–EV64）；I2b-01异步受理与受控文本执行（EV68，含EV66的intent/create_goal切片）；I6a-01 BusinessFlow核心与Worker驱动（EV69/EV70）；I4-01全格式处理器与受理合同（EV73–EV75）；I4-02研究结果/修订/引文、分析预览、202受理、执行引擎与Worker扫描（EV76–EV80）；I4-03独立知识库、固定引用、检索投影、前端首版与领域事件（EV81–EV84，I4按机制退出）；I5-01公共资产库、owner_preview窄读、采用回执与公共发布同事务（EV85–EV87）。
未完成：I5-02尾片（Production引用编译仍只消费私有Artifact解析结果，`source:"public"`已进绑定/解析/token）；I8a-01/02/03、I6b-01、I7-01/02、I8b-01、I9-01/02、I10-01/02；Flow读投影HTTP、执行/研究预览egress摘要、SourceUse跨项目owner授权计数与跨项目只读资格；I4的UI细节三件（Director研究解释、候选对照视图、共享范围预览）；所有新能力的真实作品与目标机验收。设计冻结结论见D8节；不将设计或单批通过当产品完成。

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
- 复跑无过滤Full见下条；通过后才宣布I5退出。
