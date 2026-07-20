# AI短剧生成工作台（影视一体机）完整实施规划书

> **归档声明（2026-07-13）**：本文保留为早期调研与需求来源，**不再定义当前 P0 的范围、技术选型、数据模型、交付承诺或排期**。其中 Python RQ、WebSocket、PR 工程、无条件剪映草稿、DaVinci/EDL/AAF P0 承诺及旧阶段计划均已被后续文件替代。  
> **现行依据**：`01_项目总需求.md` 至 `06_受控混合Agent运行时规范.md` 为 P0 冻结包；`DramaForge架构决策与技术选型书.md` 记录当前决策理由与 Gate；`DramaForge双模式产品与架构汇报方案.md` 为立项汇报摘要。若本文与现行文件冲突，必须忽略本文并按现行文件执行。

**编制日期**: 2026-07-10  
**项目代号**: DramaForge  
**产品定位**: 面向短剧制作团队的私有化AI生产工作台

---

## 执行摘要

本规划基于ToonFlow、ArcReel、Jellyfish三个开源项目的调研，设计一款自主可控的AI短剧生产工作台。核心价值是将"小说/剧本→可交付视频工程"的周期从数周压缩至数小时，同时保持团队审核控制权和素材一致性。

**核心差异化**:
- 镜头级生产管理（非黑盒全自动）
- 跨镜头一致性引擎（角色、场景、道具状态追踪）
- 多模型供应商路由（用户自带密钥BYOK）
- 交付剪映草稿/DaVinci XML工程（而非仅MP4，不做PR私有格式）

---

## 第一部分：架构设计

### 1.1 五层架构总览

```
┌─────────────────────────────────────────────────┐
│  用户界面层 (Web Workstation)                    │
│  三栏工作台 + 分镜时间线 + 实时任务监控          │
└────────────────┬────────────────────────────────┘
                 │ REST + WebSocket/SSE
┌────────────────┴────────────────────────────────┐
│  策划与知识层 (Planning & Knowledge)             │
│  资产库 + 事件图谱 + 一致性引擎                  │
└────────────────┬────────────────────────────────┘
                 │ 结构化数据 + 约束规则
┌────────────────┴────────────────────────────────┐
│  Agent编排与任务层 (Orchestration)               │
│  状态机 + 多Agent协作 + 任务队列                 │
└────────────────┬────────────────────────────────┘
                 │ 生成任务 + 约束注入
┌────────────────┴────────────────────────────────┐
│  生成执行层 (Generation)                         │
│  模型适配器 + 队列Worker + FFmpeg后处理          │
└────────────────┬────────────────────────────────┘
                 │ 媒体产物 + 元数据
┌────────────────┴────────────────────────────────┐
│  交付与生态层 (Delivery)                         │
│  MP4 + 剪映草稿 + PR工程 + 素材包               │
└─────────────────────────────────────────────────┘
```

### 1.2 核心领域模型

```typescript
// 项目组织结构
Project {
  id, name, targetPlatform, aspectRatio, 
  styleBible, budget, createdAt
}
  └─ Episode[] {
    episodeNumber, synopsis, duration, status
  }
    └─ Scene[] {
      sceneNumber, location, timeOfDay, characters[], props[]
    }
      └─ Shot[] {
        shotNumber, shotType, duration, 
        cameraMove, visualDescription, dialogue,
        continuityRules[], artifacts[], reviews[]
      }

// 资产系统
AssetLibrary {
  characters[], locations[], props[], voiceProfiles[], styleReferences[]
}

Character {
  id, name, appearance, personality, costume[],
  referenceImages[], consistencyRules[], stateTimeline[]
}

// 生产任务
GenerationJob {
  id, type, shotId, provider, model,
  inputSpec, promptVersion, referenceAssets[],
  status, retryCount, cost, artifacts[]
}

// 一致性约束
ContinuityRule {
  id, type, scope, condition, enforcement,
  violationSeverity, repairSuggestion
}
```

### 1.3 技术栈选型

| 层次 | 技术选型 | 理由 |
|------|---------|------|
| 前端 | React 18 + TypeScript + Vite | 组件化、类型安全、快速HMR |
| 状态管理 | Zustand + TanStack Query | 轻量、服务端状态缓存 |
| UI组件 | Radix UI + Tailwind CSS | 无障碍、可定制 |
| 实时通信 | Server-Sent Events | 单向推送任务进度 |
| 后端API | FastAPI + Pydantic | 异步、自动文档、数据校验 |
| 任务队列 | Redis + Python RQ | 简单、可监控、支持重试 |
| 数据库 | PostgreSQL 15+ | JSONB、全文搜索、事务 |
| 对象存储 | MinIO (S3兼容) | 私有化、媒体文件存储 |
| 媒体处理 | FFmpeg + Pillow | 视频拼接、图像处理 |
| 容器化 | Docker Compose | 开发/生产环境一致 |

### 1.4 模型适配器设计

```python
# 统一接口层
class TextModel(ABC):
    @abstractmethod
    async def generate(self, prompt: str, schema: dict) -> dict:
        """结构化输出，必须符合JSON Schema"""
        
class ImageModel(ABC):
    @abstractmethod
    async def generate(self, prompt: str, reference_images: list) -> bytes:
        """返回图像二进制"""

class VideoModel(ABC):
    @abstractmethod
    async def generate_from_image(
        self, image: bytes, prompt: str, duration: float
    ) -> bytes:
        """图生视频"""

# 供应商实现（示例）
class ClaudeTextAdapter(TextModel):
    # Claude API调用，支持Prompt Caching
    
class OpenAITextAdapter(TextModel):
    # OpenAI API调用，支持Structured Outputs
    
class KlingVideoAdapter(VideoModel):
    # 可灵API调用（需要用户自带key）
    
    
class ComfyUIAdapter(ImageModel, VideoModel):
    # 本地ComfyUI工作流调用
```

> **接口演进说明**：上述 `ImageModel.generate(prompt, reference_images)` 为早期签名。第 3.7.8 节将其升级为结构化传参 `generate(shot_prompt, character_refs: list[CharacterReference])`，以携带角色参考图、Face Embedding、锁定 Prompt 与 Seed，实现角色一致性注入。**实现时以 3.7.8 版本为准**。

---

## 第二部分：P0 MVP实施计划

### 2.1 MVP验收标准

**核心闭环**: 用户导入5场短剧剧本 → 审核分镜 → 生成10个镜头 → 导出MP4+剪映草稿

**量化指标**:
1. 从剧本到分镜表：< 5分钟（AI辅助）
2. 单镜头图像生成：< 2分钟（依赖模型供应商）
3. 单镜头视频生成：< 10分钟（依赖模型供应商）
4. 一致性检查覆盖率：100%（所有镜头必须校验）
5. **角色人脸一致性**：主角首帧相似度 ≥ 该角色自校准阈值（详见3.7.13），视频抽帧漂移率 < 10%
6. 交付包完整性：MP4 + SRT + 镜头素材 + 元数据

### 2.2 开发里程碑

#### 阶段1：基础架构（2周）

**任务清单**:
- [ ] 项目初始化：前后端脚手架、代码规范、Git工作流
- [ ] 数据库设计：核心表结构、迁移脚本、种子数据
- [ ] 认证系统：JWT、用户管理、密钥加密存储
- [ ] 对象存储：MinIO集成、文件上传/下载API
- [ ] 任务队列：Redis配置、Worker基础框架
- [ ] Docker编排：开发环境Compose文件、健康检查

**交付物**:
```
项目结构：
├── frontend/           # Vite + React
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── api/
│   │   └── stores/
│   └── package.json
├── backend/            # FastAPI
│   ├── app/
│   │   ├── models/     # SQLAlchemy
│   │   ├── api/        # 路由
│   │   ├── services/   # 业务逻辑
│   │   ├── adapters/   # 模型适配器
│   │   └── workers/    # 任务处理
│   ├── alembic/        # 数据库迁移
│   └── requirements.txt
├── docker-compose.yml
└── docs/
```

#### 阶段2：项目与资产管理（2周）

**任务清单**:
- [ ] 项目CRUD：创建、编辑、删除、列表
- [ ] 剧本导入：解析文本、场次识别、角色提取
- [ ] 资产库UI：角色/场景/道具卡片、图片上传
- [ ] AI资产生成：调用TextModel生成角色描述
- [ ] 资产版本控制：编辑历史、锁定机制
- [ ] 分集管理：Episode CRUD、关联Scene

**交付物**:
- 能创建项目并导入剧本文本
- AI自动提取角色、场景、道具列表
- 用户可编辑资产信息并上传参考图
- 资产锁定后进入只读状态

#### 阶段3：分镜与生成系统（3周）

**任务清单**:
- [ ] 分镜生成：调用Agent生成Shot列表（景别、运镜、时长、描述）
- [ ] 分镜表UI：可视化编辑、拖拽排序、批量操作
- [ ] 生成任务模型：GenerationJob表结构、状态机
- [ ] 图像生成Worker：实现ImageModel适配器调用
- [ ] 视频生成Worker：实现VideoModel图生视频
- [ ] 任务队列UI：实时进度、取消、重试、错误日志
- [ ] 成本追踪：记录每个任务的Provider、Model、Token/Credit消耗

**交付物**:
- 从剧本自动生成分镜表（含镜头描述）
- 用户点击"生成首帧"后任务进入队列
- Worker异步调用模型API并回写Artifact
- 前端SSE实时显示进度和结果

#### 阶段4：一致性引擎（3周）

一致性引擎是护城河，含两个正交维度：剧情连续性 + 角色视觉一致性。

**任务清单（剧情连续性）**:
- [ ] 约束规则DSL设计：定义ContinuityRule数据结构
- [ ] 资产状态时间线：记录角色服装、道具持有在各Shot的变化
- [ ] 生成前校验：检查Shot引用的资产是否存在冲突
- [ ] 生成后质检：调用审核Agent分析Artifact是否违反规则
- [ ] 修复建议生成：基于冲突类型给出可执行修改方案
- [ ] 一致性报告UI：可视化展示问题Shot、冲突原因、修复按钮

**任务清单（角色视觉一致性）**:
- [ ] 参考图注入：ImageModel结构化传参（CharacterReference）
- [ ] Reference Set：多角度参考图库 + 按景别自动选图
- [ ] Face Embedding：集成InsightFace，角色特征提取入库
- [ ] 检测闭环：生成后相似度比对，低于阈值自动重生成
- [ ] 阈值自适应校准：每角色个性化基线 + 反馈反哺（3.7.13）
- [ ] 视频后校验：抽帧比对，漂移片段标记进修复队列

**交付物**:
- 系统能检测"角色服装突变"、"道具凭空出现"等剧情问题
- 系统能检测并拦截"人脸漂移"（首帧+视频帧）
- 质检报告能定位到具体Shot和违反的规则
- 用户点击修复后自动调整Prompt/参考图并重新生成

#### 阶段5：交付与导出（2周）

**任务清单**:
- [ ] 字幕生成：从对白生成SRT时间轴
- [ ] TTS集成：调用音频模型生成配音
- [ ] 时间线拼接：FFmpeg合成镜头、音频、字幕为MP4
- [ ] 剪映草稿导出：生成.draft_content文件（JSON结构）
- [ ] 素材包导出：打包所有Artifact、元数据、项目配置为ZIP
- [ ] 导出任务队列：异步处理大文件生成
- [ ] 导出历史管理：版本列表、下载链接、过期清理

**交付物**:
- 用户点击"导出"后生成MP4、SRT、剪映草稿、素材包
- 导出包可在剪映中打开并继续编辑
- 素材包包含所有镜头原始文件和项目JSON

### 2.3 开发时间表

| 阶段 | 周期 | 起止时间 | 关键里程碑 |
|------|------|---------|-----------|
| 阶段1 | 2周 | W1-W2 | Docker环境可运行，数据库Schema完成 |
| 阶段2 | 2周 | W3-W4 | 可创建项目、导入剧本、编辑资产 |
| 阶段3 | 3周 | W5-W7 | 分镜生成、任务队列、图像/视频生成 |
| 阶段4 | 3周 | W8-W10 | 剧情连续性+角色视觉一致性、质检、修复 |
| 阶段5 | 2周 | W11-W12 | MP4导出、剪映草稿、素材包 |
| **总计** | **12周** | | **MVP可交付验收** |

> 注：阶段4较初版增加1周，用于消化3.7的角色视觉一致性（Face Embedding检测闭环+阈值校准+视频后校验），这是护城河的核心，不宜压缩。

---

## 第三部分：一致性引擎详细设计

### 3.1 核心价值

一致性引擎是本产品的**核心护城河**，解决AI视频生成的最大痛点：跨镜头的角色、场景、道具不连贯。

**典型问题**:
- 角色服装突变（上一镜白衬衫，下一镜变西装）
- 道具凭空出现/消失（合同应该在手里但画面没有）
- 场景细节冲突（办公室窗户位置前后不一致）
- 角色状态错误（上一镜受伤，下一镜完好）

> **两套"层"的关系（重要）**：本产品的一致性由两个正交维度组成，不要混淆——
> - **剧情连续性（3.2 四层架构）**：管"资产状态在时间线上是否合逻辑"（服装/道具/伤痕是否该变、何时变），是**语义层**，靠状态时间线+规则引擎+视觉LLM质检。
> - **角色视觉一致性（3.7 七层架构）**：管"同一角色的脸/外形在每张图里是否是同一个人",是**像素层**，靠参考图注入+Face Embedding比对。
>
> 举例：剧情连续性负责"这一镜她该不该还穿白西装"；视觉一致性负责"就算穿对了白西装，这张脸还是不是林雨薇"。两者叠加才是完整一致性。

### 3.2 四层架构（剧情连续性）

```
┌─────────────────────────────────────┐
│ 1. 资产状态时间线 (State Timeline)  │
│    记录每个资产在各Shot的状态变化    │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│ 2. 约束规则引擎 (Constraint Rules)  │
│    定义一致性检查规则和优先级        │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│ 3. 生成前注入 (Pre-generation)      │
│    在Prompt中强制包含约束信息        │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│ 4. 生成后质检 (Post-generation)     │
│    AI视觉分析 + 规则匹配检测冲突    │
└─────────────────────────────────────┘
```

### 3.3 资产状态时间线

**数据结构**:
```python
class AssetStateTimeline(Base):
    """记录资产在剧情时间线上的状态"""
    id: UUID
    asset_id: UUID  # 关联Character/Prop/Location
    asset_type: Enum["character", "prop", "location"]
    
    # 时间定位
    episode_id: UUID
    scene_id: UUID
    shot_id: UUID
    
    # 状态快照
    state_snapshot: JSONB  # {
    #   "costume": "白色西装",
    #   "injury": "右手缠绷带",
    #   "holding": ["合同", "手机"],
    #   "emotion": "愤怒",
    #   "location_in_scene": "靠窗位置"
    # }
    
    # 变化事件
    state_changes: JSONB  # [
    #   {"action": "put_down", "target": "合同", "reason": "剧本台词：她把合同扔在桌上"}
    # ]
    
    # 元数据
    locked: bool  # 锁定后不可自动修改
    verified_by_user: bool  # 人工确认过
    created_at: datetime

class ContinuityRule(Base):
    """一致性约束规则"""
    id: UUID
    name: str  # "角色服装连续性"
    type: Enum["character_appearance", "prop_continuity", "scene_layout", "lighting"]
    
    # 适用范围
    scope: Enum["project", "episode", "scene"]
    
    # 规则定义
    condition: JSONB  # {
    #   "if": "character.costume 在 shot_N 已确定",
    #   "then": "shot_N+1 必须保持相同，除非剧本明确说明换装"
    # }
    
    # 执行策略
    enforcement: Enum["block", "warn", "suggest"]
    violation_severity: Enum["critical", "high", "medium", "low"]
    
    # 修复建议
    repair_template: str  # "将Prompt改为：角色穿着{previous_costume}"
```

### 3.4 生成前注入机制

**工作流程**:
1. 用户点击"生成Shot #15的首帧"
2. 系统查询Shot #15引用的角色、场景、道具
3. 查询这些资产在Shot #14的状态快照
4. 构造约束Prompt片段：
```
【一致性约束】
- 角色"李雨薇"：穿白色西装，右手缠绷带，表情愤怒
- 道具"合同"：在桌面上（上一镜被扔下）
- 场景"办公室"：窗户在角色左后方，夜晚室内灯光
```
5. 将约束片段注入到生成Prompt的开头
6. 调用ImageModel生成

**Prompt注入示例**:
```python
def build_generation_prompt(shot: Shot) -> str:
    # 1. 获取约束
    constraints = get_continuity_constraints(shot)
    
    # 2. 构造约束文本
    constraint_text = format_constraints(constraints)
    
    # 3. 组合最终Prompt
    final_prompt = f"""
{constraint_text}

【镜头描述】
{shot.visual_description}

【画面要求】
景别：{shot.shot_type}
运镜：{shot.camera_move}
"""
    return final_prompt
```

### 3.5 生成后质检机制

**质检Agent设计**:
```python
class ConsistencyCheckAgent:
    """一致性质检Agent"""
    
    async def check_artifact(
        self, 
        artifact: Artifact, 
        shot: Shot
    ) -> ConsistencyReport:
        """检查生成产物是否符合一致性要求"""
        
        # 1. 获取应该遵守的规则
        rules = get_applicable_rules(shot)
        
        # 2. 获取参考状态
        expected_states = get_expected_states(shot)
        
        # 3. 调用视觉LLM分析图像
        vision_analysis = await self.vision_model.analyze(
            image=artifact.file_data,
            prompt=f"""
分析这张图像，检查以下要素：
1. 角色"{expected_states['character']['name']}"是否穿着"{expected_states['character']['costume']}"
2. 是否存在道具：{expected_states['props']}
3. 场景布局是否符合：{expected_states['scene_layout']}

对每个要素，回答：符合/不符合/无法判断，并说明原因。
"""
        )
        
        # 4. 规则匹配
        violations = []
        for rule in rules:
            if not self.check_rule(vision_analysis, rule, expected_states):
                violations.append({
                    "rule": rule,
                    "severity": rule.violation_severity,
                    "detected_issue": vision_analysis.issue_description,
                    "repair_suggestion": self.generate_repair(rule, expected_states)
                })
        
        # 5. 生成报告
        return ConsistencyReport(
            artifact_id=artifact.id,
            passed=len(violations) == 0,
            violations=violations,
            confidence_score=vision_analysis.confidence
        )
```

### 3.6 智能修复建议

**修复策略**:

| 冲突类型 | 检测方法 | 修复建议 |
|---------|---------|---------|
| 角色服装变化 | 视觉LLM对比 | 在Prompt中强调"{previous_costume}"，重新生成 |
| 道具缺失 | 对象检测 | 在Prompt中添加"特写{prop_name}在{location}"，或使用图像编辑添加道具 |
| 场景布局冲突 | 空间关系分析 | 使用上一Shot的首帧作为参考图，控制视角 |
| 光照不一致 | 色调分析 | 调整Prompt的时间/光照描述，或后期调色 |

**修复UI流程**:
1. 质检报告显示红色警告：Shot #15违反3条规则
2. 用户点击"查看详情"，展开：
   - ❌ 角色服装从白西装变成了黑T恤（Critical）
   - ⚠️ 合同道具未出现在画面中（High）
   - ⚠️ 窗户位置从左侧变成右侧（Medium）
3. 系统自动生成修复建议：
   - 建议1：重新生成（已自动调整Prompt强调白西装+合同）
   - 建议2：使用Shot #14的首帧作为参考图
   - 建议3：手动编辑Prompt后重试
4. 用户点击"应用建议1"，任务重新入队

---

### 3.7 角色视觉一致性（多层一致性引擎）

#### 3.7.1 核心问题与设计哲学

分镜首帧各自独立生成，即使文字描述完全相同，扩散模型每次采样的初始噪声不同，画出的人脸也不同。**纯文字描述无法锁定角色外观**——这是短剧生成最致命的痛点。

**关键判断**：随着 Flux Kontext、GPT-Image、即梦角色参考、可灵人物参考、Nano Banana(Gemini Image)、MJ `--cref` 等模型原生支持参考图注入，**LoRA 已不再是保持一致性的首选，而是最后一层可选增强**。真正有效的是**多层一致性**——每一层解决一部分问题，叠加起来才稳。

核心原则：
```
预防层（参考图/Prompt/Seed）负责"尽量对"
检测层（Face Embedding 比对）负责"保证发现错"
LoRA 是最后一层增强，不是地基
```

#### 3.7.2 七层一致性架构

```
第一层：角色参考图      ← 最重要，解决约80%
第二层：Reference Set   ← 多角度参考图库
第三层：Prompt锁定      ← 固定角色Prompt
第四层：Seed固定        ← 可复现采样
第五层：Face Embedding  ← 检测闭环（最值得做）
第六层：Reference Injection ← 综合注入
第七层：Video后校验     ← 视频漂移检测
──────────────────────────────
可选增强：LoRA（仅超高频主角）
```

#### 3.7.3 第一层：角色参考图（80%的效果）

现在几乎所有先进模型都支持参考图，不靠 LoRA：
```
Prompt + Character Reference Image  →  Image

人物：28岁中国女性 (附Reference Image)
穿白色西装，站在办公室
→ 模型优先匹配参考图的人脸
```
这一层已能解决大部分问题。系统为每个角色确定一张**权威参考图 (Canonical Image)**，生成任意分镜时默认注入。

#### 3.7.4 第二层：Reference Set（多角度参考）

不要只有一张图，为角色建立多角度、多状态参考库：
```
林雨薇
├── 正脸 (canonical)      ├── 微笑
├── 左侧脸                ├── 生气
├── 右侧脸                ├── 白西装
├── 全身                  └── 黑风衣
```
**镜头自动选参考图**：
- 近景 → 用正脸
- 全景 → 用全身
- 侧脸镜头 → 用侧脸

按 Shot 的景别/角度自动匹配最合适的参考图，一致性比单图 LoRA 更高。

#### 3.7.5 第三层：Prompt锁定（固定角色Prompt）

常见错误：每个镜头重新写角色描述。正确做法是**角色拥有固定不变的 Prompt**：
```
Character Prompt (永不变):
  28-year-old Chinese woman, long black hair, oval face,
  sharp eyes, white suit, minimal makeup, slim body, cinematic lighting

每个Shot = Character Prompt + Shot Prompt
  例：Character + Office + Close-up + Looking outside
```
角色 Prompt 存在 `Character.locked_prompt`，任何镜头都拼接而非重写。

#### 3.7.6 第四层：Seed固定

模型支持 Seed 时（Flux/SDXL/ComfyUI），为角色绑定固定 Seed：
```
林雨薇 → Seed 9283746
同一 Seed + 参考图 + Prompt → 出来的人几乎一致
```
存在 `Character.anchor_seed`。闭源 API 不支持 Seed 时此层自动跳过，靠其余层兜底。

#### 3.7.7 第五层：Face Embedding（检测闭环，最值得做）

**这一层比 LoRA 更重要。LoRA 是预防，Embedding 是真正的检测。**

流程：
```
Reference Image → InsightFace → Embedding → 存入数据库

任何生成图/视频帧完成后：
  Generated → InsightFace → Embedding B
  Cosine Similarity(Reference Embedding, B)
  相似度 < 0.75 → 直接重新生成
```

数据结构：
```python
class Character(Base):
    id: UUID
    face_embedding: bytes          # InsightFace 512维特征向量
    reference_images: list[str]    # 多角度参考图
    canonical_reference: str       # 正脸权威图
    locked_prompt: str             # 固定角色Prompt
    anchor_seed: int | None        # 固定Seed
    reference_set: JSONB           # {"front": url, "left": url, "full_body": url, ...}

class FaceConsistencyCheck:
    async def verify(self, generated: bytes, character: Character) -> float:
        gen_emb = insightface.get_embedding(generated)
        ref_emb = deserialize(character.face_embedding)
        similarity = cosine_similarity(ref_emb, gen_emb)
        return similarity  # < 0.75 触发重生成
```

#### 3.7.8 第六层：Reference Injection（综合注入）

生成时不是只传 Prompt，而是把所有锚定信息一起注入——这是当前商业产品的标准做法：
```
生成输入 = Canonical Image
         + Face Embedding
         + Character Prompt (locked)
         + Shot Prompt
         + Seed (if supported)
         ↓
       模型 (Flux Kontext / 即梦 / 可灵 / ComfyUI)
```

适配器接口（结构化传参，替代原笼统的 `reference_images: list`）：
```python
class CharacterReference:
    character_id: str
    canonical_image: bytes
    selected_reference: bytes       # 按景别自动选中的参考图
    face_embedding: bytes
    locked_prompt: str
    seed: int | None
    weight: float
    region: BBox | None             # 多角色同框区域绑定

class ImageModel(ABC):
    @abstractmethod
    async def generate(
        self, shot_prompt: str,
        character_refs: list[CharacterReference]
    ) -> bytes: ...
```

生成前组装：
```python
def build_keyframe_job(shot: Shot) -> GenerationJob:
    refs = []
    for char_id in shot.characters:
        char = get_character(char_id)
        refs.append(CharacterReference(
            character_id=char_id,
            canonical_image=load(char.canonical_reference),
            selected_reference=pick_by_shot_type(char, shot.shot_type),  # 景别选图
            face_embedding=char.face_embedding,
            locked_prompt=char.locked_prompt,
            seed=char.anchor_seed,
            weight=0.85 if char.is_lead else 0.7,
            region=resolve_character_region(shot, char_id)
        ))
    return GenerationJob(shot_id=shot.id, character_refs=refs)
```

#### 3.7.9 第七层：Video后校验（关键且常被忽略）

**图片一致 ≠ 视频一致**。可灵首帧很好，第三秒脸可能已经变了。

```
视频生成完成后：
  每 5 帧抽样 → InsightFace → Cosine Similarity(canonical)
  相似度 < 0.8 的片段 → 标记漂移 → 重新生成 / 逐帧换脸修正
```

实现：
```python
async def verify_video_consistency(video: bytes, character: Character):
    frames = extract_frames(video, interval=5)
    drifts = []
    for idx, frame in enumerate(frames):
        sim = FaceConsistencyCheck().verify(frame, character)
        if sim < 0.8:
            drifts.append({"frame": idx*5, "similarity": sim})
    if drifts:
        await mark_for_repair(video, drifts)  # 进入修复队列
    return drifts
```

#### 3.7.10 多角色同框处理

单人脸注入好做，两个主角对话时人脸易"串味"（A 带上 B 的特征）：
- **区域绑定**：Regional Prompting，每个角色参考图只作用于其 BBox 区域
- **分步换脸**：先生成构图，再用 InsightFace 对每个人脸区域分别精确替换
- 本地 ComfyUI 可控性最强，多数闭源 API 做不到精确分区

#### 3.7.11 LoRA：可选的最后一层增强

LoRA 不再是地基，仅在以下情况使用：
- 超高频出场的核心主角（出场数百次，值得训练成本）
- 前六层叠加后相似度仍不稳定的疑难角色
- 需要极致风格统一的品牌级项目

即"预防层已足够时不训 LoRA，只在检测层反复报警时才追加"。

#### 3.7.12 MVP推荐组合

完全自主可控、不依赖闭源黑盒的最小组合：
```
参考图注入(第一层) + 固定Prompt(第三层) + Reference Set按景别选图(第二层)
     ↓
Face Embedding 生成后比对(第五层) —— 核心保障，<0.75 自动重生成
     ↓
视频后逐帧校验(第七层) —— 拦截图生视频漂移
     ↓
[可选] 疑难主角追加 LoRA
```
关键投入优先级：**第五层 Face Embedding 检测闭环 > 第一层参考图 > 第七层视频校验 > 其余**。检测闭环是唯一能"保证发现错误"的层，最该先做。

#### 3.7.13 阈值自适应校准（落地关键）

**为什么固定阈值会翻车**：第五层的 0.75、第七层的 0.8 只是经验起点。InsightFace 的余弦相似度分布受多种因素影响，固定阈值会同时导致**误杀**（好图被判漂移，反复重生成烧钱）和**漏检**（脸变了却没报警）：

| 影响因素 | 相似度分布偏移 |
|---------|--------------|
| 人种 | 东亚人脸类内相似度普遍偏高，欧美偏低 |
| 配饰 | 戴眼镜/口罩/帽子显著拉低相似度 |
| 角度 | 侧脸对正脸的相似度天然低于正脸对正脸 |
| 年龄/性别 | 儿童、老人特征提取稳定性差 |
| 表情 | 夸张表情（大笑、痛哭）拉低相似度 |
| 模型 | 不同底模生成的人脸"数字质感"不同，基线各异 |

同一个 0.75 阈值，对戴眼镜的东亚男性可能太松（漏检），对正脸欧美女性可能太紧（误杀）。

**解决方案：每角色个性化基线**

用角色自己的参考图集，先算出"这个角色的正常相似度长什么样"，再据此动态定阈值：

```python
def calibrate_threshold(character: Character) -> ThresholdProfile:
    """用角色参考图集自校准阈值"""
    ref_set = character.reference_set  # 正脸/侧脸/全身/表情...
    ref_emb = deserialize(character.face_embedding)  # 以正脸为锚

    # 1. 类内相似度：每张参考图 vs 锚点，得到"这个角色正常波动范围"
    intra_sims = [
        cosine_similarity(ref_emb, insightface.get_embedding(load(img)))
        for img in ref_set.values()
    ]
    mu, sigma = mean(intra_sims), std(intra_sims)

    # 2. 阈值 = 均值 - k倍标准差（k控制严格度，默认2）
    #    低于此值说明比"该角色最差的合法参考图"还差 → 判定漂移
    base_threshold = mu - 2 * sigma

    # 3. 分景别细化：侧脸镜头用侧脸基线，避免拿正脸标准卡侧脸
    per_shot_type = {
        shot_type: calibrate_for_reference(ref_set[ref_key], ref_emb)
        for shot_type, ref_key in SHOT_TYPE_TO_REF.items()
    }

    return ThresholdProfile(
        base=clamp(base_threshold, 0.55, 0.85),  # 兜底夹逼，防止极端值
        per_shot_type=per_shot_type,
        sample_size=len(intra_sims),
        confidence="low" if len(intra_sims) < 4 else "high"
    )
```

**校验时按景别取阈值**：
```python
async def verify_with_adaptive_threshold(generated, shot, character):
    profile = get_or_calibrate(character)
    threshold = profile.per_shot_type.get(shot.shot_type, profile.base)
    sim = FaceConsistencyCheck().verify(generated, character)
    return sim, sim >= threshold  # 侧脸镜头用侧脸阈值，不误杀
```

**运行期漂移修正（闭环反哺）**：
- 用户在质检环节手动"通过"了一张低于阈值的图 → 说明阈值偏紧，把该样本纳入基线重算
- 用户手动"打回"了一张高于阈值的图 → 说明阈值偏松，收紧该角色阈值
- 每角色积累足够人工反馈后，阈值从"统计估计"过渡到"数据驱动"

```python
def update_threshold_from_feedback(character, sample_sim, user_verdict):
    profile = get_threshold_profile(character)
    if user_verdict == "approved" and sample_sim < profile.base:
        profile.expand_lower_bound(sample_sim)   # 放宽
    elif user_verdict == "rejected" and sample_sim >= profile.base:
        profile.tighten(sample_sim)              # 收紧
    persist(profile)
```

**冷启动策略**：参考图不足（<4张）时 `confidence=low`，此时：
- 阈值取保守值（偏松，宁可漏检也不狂烧重生成成本）
- 强制人工复核比例提高，用人工反馈快速积累基线
- 参考图补齐后自动重新校准

**落地要点**：阈值 Profile 存 `Character.threshold_profile (JSONB)`，随参考图集变化和用户反馈持续演进——**不要在代码里写死任何一个相似度常数**。

---

## 第三部分补：Production Graph（生产图）—— 系统真正的核心

### 3.8.1 为什么需要生产图

`Project → Episode → Scene → Shot` 只是**数据组织层级**，它无法表达"一个 Shot 内部的加工步骤之间的依赖关系"。而短剧生产的真实痛点是**局部重跑**：

```
改字幕 → 不该重跑视频
换视频 → 不该重画首帧
重配音 → 不该重新导出整集
```

要做到这点，必须把每个 Shot 的生产过程建模成一张 **DAG（有向无环图）**，每个加工步骤是一个 **Node**，各自带独立的输入哈希与 checkpoint。ComfyUI、n8n 的可恢复性都是基于这种图结构。

**这是本系统真正的核心——不是 Agent，而是 Production Graph。所有 Agent、FFmpeg、TTS、LLM、ComfyUI 调用都只是图里的一个 Node。**

### 3.8.2 Shot 级生产图

```
Shot001
  ├─[Node] Keyframe   (图像生成)
  │    ↓
  ├─[Node] Video      (图生视频，依赖Keyframe)
  │    ↓
  ├─[Node] Voice      (TTS，可与Video并行，仅依赖dialogue)
  │    ↓
  ├─[Node] Subtitle   (字幕，依赖dialogue+时长)
  │    ↓
  ├─[Node] Composite  (合成，依赖Video+Voice+Subtitle)
  │    ↓
  ├─[Node] Review     (一致性质检，依赖Composite)
  │    ↓
  └─[Node] Export     (交付，依赖Review通过)
```

关键：`Voice` 和 `Video` 只依赖各自输入，互不依赖——**可并行**；改了 `Subtitle` 只需重跑 `Subtitle→Composite→Export`，`Keyframe/Video/Voice` 全部命中缓存。

### 3.8.3 节点抽象

```python
class GraphNode(Base):
    id: UUID
    graph_id: UUID              # 所属Shot的生产图
    node_type: str             # "keyframe"|"video"|"voice"|"subtitle"|"composite"|"review"|"export"
    executor: str              # 执行器: "agent:generation" | "tool:ffmpeg" | "tool:tts" | "model:flux" ...
    depends_on: list[UUID]     # 上游节点
    input_hash: str            # 输入指纹（上游产物哈希+参数），决定是否命中缓存
    status: Enum["pending","running","cached","completed","failed","stale"]
    artifact_id: UUID | None   # 本节点产物
    cost: Decimal
    checkpoint: JSONB

    def is_stale(self) -> bool:
        """上游产物或参数变了 → 本节点及所有下游标记stale，需重跑"""
        return self.input_hash != self.compute_current_hash()
```

**统一执行器接口**——Agent 与工具同构，都是 Node 的 executor：
```python
class NodeExecutor(ABC):
    @abstractmethod
    async def run(self, node: GraphNode, inputs: dict) -> Artifact: ...

# 注册表：加新能力 = 注册新执行器，无需改编排逻辑
EXECUTOR_REGISTRY = {
    "agent:generation": GenerationAgentExecutor(),
    "agent:review":     ConsistencyCheckExecutor(),
    "tool:ffmpeg":      FFmpegExecutor(),
    "tool:tts":         TTSExecutor(),
    "model:flux":       FluxImageExecutor(),
    "model:comfyui":    ComfyUIExecutor(),
    # 未来任意新Node：注册即用
}
```

### 3.8.4 增量重跑（核心价值）

```python
async def rerun_from(graph: ProductionGraph, changed_node_id: UUID):
    """只重跑变更节点及其下游，上游命中缓存"""
    dirty = graph.descendants(changed_node_id) | {changed_node_id}
    for node in graph.topological_order():
        if node.id in dirty:
            node.status = "stale"

    for node in graph.topological_order():
        if node.status == "stale":
            inputs = gather_upstream_artifacts(node)      # 上游产物直接复用
            node.artifact = await EXECUTOR_REGISTRY[node.executor].run(node, inputs)
            node.status = "completed"
        # 非stale节点：status="cached"，零成本跳过
```

效果：改字幕的重跑成本 ≈ 字幕节点 + 合成 + 导出，而非整个 Shot 重来。**这直接决定生产成本和迭代速度。**

### 3.8.5 对整体架构的影响

生产图确立后，系统模块重新划分为：

```
DramaForge
├── Project           项目/剧集/场次/镜头（数据层级）
├── Asset Library     角色/场景/道具/声音
├── Story Bible       世界观/风格/剧情设定
├── Knowledge Graph   事件图谱/线索/人物关系
├── Production Graph  ⭐ 生产DAG，编排与恢复的核心
├── Consistency Engine 剧情连续性(四层)+角色视觉一致性(七层)
├── Model Router      多Provider路由/BYOK/成本路由
├── Render Pipeline   Node执行器：LLM/图像/视频/TTS/FFmpeg/ComfyUI
└── Delivery          MP4/剪映/DaVinci XML/EDL/AAF/素材包
```

**认知转变**：原"六类 Agent 编排"（第四部分）不再是顶层控制者，而是 Production Graph 中 `executor="agent:*"` 的一类 Node。状态机（4.4）负责推进图的执行，Agent 负责在节点内做创作决策。这样加任何新能力（新模型、新后处理、新导出格式）都只是注册一个新 Node 类型，编排逻辑零改动——扩展性提升一个量级。

---

## 第四部分：Agent编排详细设计

> **架构定位（重要）**：结合 3.8 节，本部分的"六类 Agent"应理解为 **Production Graph 中 `executor="agent:*"` 的节点**，而非系统的顶层控制者。真正的编排核心是生产图 + 状态机；Agent 只在节点内产出结构化内容或判断。下文的职责划分与交互模式，都是在"Agent 作为 Node"这一前提下展开。

### 4.1 六类Agent职责

| Agent类型 | 核心职责 | 输入 | 输出 | 调用时机 |
|---------|---------|------|------|---------|
| **策划Agent** | 剧本拆解、分集规划、事件图谱构建 | 原始文本、项目配置 | 结构化大纲、Episode列表、角色/场景/道具初始清单 | 项目创建后 |
| **资产Agent** | 角色卡、场景卡、道具卡生成，参考图推荐 | 策划输出、用户上传的参考图 | Character/Scene/Prop实体，初始PromptTemplate | 策划完成后 |
| **分镜Agent** | Shot列表生成、镜头语言设计 | Episode剧本、资产库 | Shot[]（含景别、运镜、时长、描述、角色、道具引用） | 单集剧本确认后 |
| **生成Agent** | 调度图像/视频生成任务、Prompt优化 | Shot定义、一致性约束 | GenerationJob入队、约束注入后的FinalPrompt | 用户点击"生成" |
| **质检Agent** | 一致性校验、质量评估、冲突检测 | Artifact、Shot定义、历史状态 | ConsistencyReport、违规列表、修复建议 | 生成完成后 |
| **导出Agent** | 时间线拼接、字幕生成、剪映草稿导出 | 确认的Artifact[]、音频、字幕 | MP4、SRT、.draft_content、素材包ZIP | 用户点击"导出" |

**职责边界**：
- Agent只输出结构化建议，不直接修改数据库状态
- 所有写操作由Orchestrator通过Tool执行
- Agent不能绕过审核节点推进流程状态

### 4.2 Agent交互模式

**协作模式1：串行依赖**
```
策划Agent → 资产Agent → 分镜Agent → 生成Agent → 质检Agent → 导出Agent
```
每个Agent的输出是下一个Agent的输入，人工审核节点在每个箭头处。

**协作模式2：并行执行**
```
分镜Agent输出50个Shot
   ├─ Shot 1-10  → 生成Agent实例A
   ├─ Shot 11-20 → 生成Agent实例B
   ├─ Shot 21-30 → 生成Agent实例C
   └─ ...
```
同一类型Agent可并行处理不同数据分片，通过Redis队列协调。

**协作模式3：迭代修复**
```
生成Agent → Artifact → 质检Agent → 发现冲突
   ↓                                    ↓
   ← 修复建议（调整Prompt/参考图）  ←  ←
   ↓
重新生成
```

### 4.3 Agent状态管理

**Stateless设计**：
- Agent本身不保存状态，所有状态存储在数据库
- 每次调用传入完整上下文（Project、Episode、Scene、Shot、AssetLibrary）
- Memory通过向量检索动态加载相关历史记录

**上下文注入机制**：
```python
def invoke_agent(agent_type: str, task: dict) -> dict:
    # 1. 构造上下文
    context = {
        "project": get_project(task["project_id"]),
        "assets": get_asset_library(task["project_id"]),
        "memory": retrieve_relevant_memory(task),
        "rules": get_continuity_rules(task),
        "budget": get_remaining_budget(task["project_id"])
    }
    
    # 2. 调用Agent
    agent = agent_registry.get(agent_type)
    result = await agent.execute(task, context)
    
    # 3. 写入记忆
    await store_memory(task["project_id"], result)
    
    return result
```

### 4.4 工作流编排

**状态机驱动模式**：
```python
class ProductionOrchestrator:
    """生产编排器，控制项目状态流转"""
    
    async def advance_stage(self, project_id: UUID, user_approval: dict):
        project = await get_project(project_id)
        current_stage = project.stage
        
        # 状态转移表
        transitions = {
            "CREATED": self._stage_parse_source,
            "SOURCE_PARSED": self._stage_extract_assets,
            "ASSETS_READY": self._stage_generate_storyboard,
            "STORYBOARD_READY": self._stage_generate_keyframes,
            "KEYFRAMES_READY": self._stage_generate_videos,
            "VIDEOS_READY": self._stage_generate_audio,
            "AUDIO_READY": self._stage_assemble_timeline,
            "TIMELINE_READY": self._stage_export
        }
        
        handler = transitions.get(current_stage)
        if handler:
            await handler(project, user_approval)
    
    async def _stage_generate_storyboard(self, project, approval):
        # 1. 调用分镜Agent
        shots = await invoke_agent("storyboard", {
            "project_id": project.id,
            "episode_id": approval["episode_id"],
            "script": approval["approved_script"]
        })
        
        # 2. Schema校验
        validated_shots = validate_shots(shots)
        
        # 3. 写入数据库
        await batch_create_shots(validated_shots)
        
        # 4. 进入待审核状态
        await update_project_stage(project.id, "STORYBOARD_WAITING_REVIEW")
        
        # 5. 发送通知
        await notify_user(project.id, "storyboard_ready_for_review")
```

**人工审核节点**：
- 系统不会自动跳过审核，必须收到用户明确的`approve`或`revise`指令
- 审核时可局部修改（单个Shot、单个角色卡）
- 修改后自动触发下游依赖检查（如Shot引用的角色被修改，该Shot进入待确认状态）

### 4.5 错误处理与重试

**分级重试策略**：

| 错误类型 | 重试次数 | 退避策略 | Fallback |
|---------|---------|---------|----------|
| 模型API超时 | 3次 | 指数退避（2s, 4s, 8s） | 切换到备用Provider |
| 模型拒绝生成（内容审核） | 1次 | 调整Prompt去敏感词 | 人工介入 |
| 一致性校验失败 | 无限次 | 人工修复后重试 | 锁定违规Shot |
| 资源不足（GPU队列满） | 延迟重试 | 每分钟检查 | 降级到低优先级队列 |
| Schema校验失败 | 2次 | 立即重试 | 记录错误，通知开发 |

**断点续传机制**：
```python
class GenerationJob(Base):
    id: UUID
    shot_id: UUID
    status: Enum["pending", "running", "completed", "failed"]
    checkpoint: JSONB  # {"stage": "prompt_built", "artifacts": [...]}
    
    def resume(self):
        """从上次checkpoint恢复"""
        if self.checkpoint["stage"] == "prompt_built":
            # 跳过Prompt构建，直接调用模型
            return self._call_model(self.checkpoint["prompt"])
        elif self.checkpoint["stage"] == "model_called":
            # 模型已返回，执行后处理
            return self._post_process(self.checkpoint["raw_output"])
```

---

## 第五部分：成本预算与资源规划

### 5.1 模型API成本估算

**单集短剧成本拆解**（以30个镜头、每镜头4秒为例；模型名为**示例**，实际按当前可用版本选择）：

| 环节 | 模型类型（示例） | 调用次数 | 单次成本 | 小计 |
|-----|---------|---------|---------|------|
| 剧本拆解 | 高质量文本模型 | 1次 | ￥1.5 | ￥1.5 |
| 资产生成（角色卡×5） | 高质量文本模型 | 5次 | ￥0.8 | ￥4 |
| 分镜生成 | 高质量文本模型 | 1次 | ￥2 | ￥2 |
| 首帧生成（每镜2候选） | Flux/SD类图像模型 | 60次 | ￥0.2 | ￥12 |
| 视频生成（图生视频） | 可灵/Runway类视频模型 | 30次 | ￥2 | ￥60 |
| 配音TTS | 火山/Azure TTS类 | 30次 | ￥0.1 | ￥3 |
| 一致性质检 | 视觉LLM（Face比对本地免费） | 30次 | ￥0.5 | ￥15 |
| **子计（首次生成）** | | | | **￥97.5** |
| 一致性检测触发重生成 | 图像重生成×约30%镜头 | ~18次 | ￥0.2 | ￥3.6 |
| 一致性检测触发重生成 | 视频重生成×约20%镜头 | ~6次 | ￥2 | ￥12 |
| **子计（重生成）** | | | | **￥15.6** |
| **单集总计（含重跑）** | | | | **约￥113** |

> **重生成是成本大头之一，易被低估**：检测闭环（3.7.7）会主动重跑不达标镜头。上表按图像30%、视频20%的重跑率估算——实际重跑率取决于所选模型质量与阈值松紧。**这正是 3.8 Production Graph 增量重跑的价值**：改字幕/配音不触发图像视频重跑，能把重生成成本压到最低。视频重跑率每降5%，单集省约￥3。

**成本优化策略**：
- 草稿阶段使用便宜模型（Haiku、DeepSeek）
- 定稿阶段切换高质量模型（Sonnet、GPT-4o）
- 首帧生成支持本地ComfyUI（成本降至电费）
- 视频生成支持批量折扣或企业包月套餐

### 5.2 基础设施成本

**MVP阶段（支持10个并发项目）**：

| 资源项 | 规格 | 月成本 | 说明 |
|--------|------|--------|------|
| Web服务器 | 4核8G × 2 | ￥600 | 前端+API，负载均衡 |
| Worker服务器 | 8核16G × 2 | ￥1200 | 处理生成任务、FFmpeg |
| PostgreSQL | 4核16G + 500GB SSD | ￥800 | 主数据库 |
| Redis | 8GB内存 | ￥200 | 任务队列+缓存 |
| 对象存储 | 2TB + 流量 | ￥300 | MinIO或OSS |
| CDN流量 | 500GB/月 | ￥150 | 视频预览加速 |
| 监控告警 | 基础版 | ￥100 | Prometheus+Grafana |
| **月度总计** | | **￥3350** | |
| **年度总计** | | **￥40200** | |

**商业化阶段（支持100个并发项目）**：
- 服务器扩展至10+节点：￥15000/月
- 数据库升级至集群：￥5000/月
- CDN流量扩容至5TB：￥800/月
- **预计月成本：￥25000-30000**

### 5.3 开发团队成本

**MVP阶段（11周）**：

| 角色 | 人数 | 周薪（参考） | 总周数 | 成本 |
|-----|------|------------|--------|------|
| 全栈/后端负责人 | 1 | ￥8000 | 11周 | ￥88000 |
| 前端工程师 | 1 | ￥6000 | 11周 | ￥66000 |
| AI/Agent工程师 | 1 | ￥7000 | 11周 | ￥77000 |
| 产品经理 | 0.5 | ￥5000 | 11周 | ￥27500 |
| **人力总成本** | | | | **￥258500** |

**其他成本**：
- 模型API测试额度：￥10000
- 域名+SSL证书：￥500
- 第三方服务（监控、日志）：￥2000
- **MVP总成本预算：￥271000**

### 5.4 成本控制策略

**用户侧成本控制**：
```python
class BudgetGuard:
    """项目预算守卫"""
    
    async def check_before_generation(self, project_id: UUID, job: GenerationJob):
        budget = await get_project_budget(project_id)
        spent = await get_spent_amount(project_id)
        estimated_cost = self.estimate_job_cost(job)
        
        if spent + estimated_cost > budget.hard_limit:
            raise BudgetExceededError(
                f"项目预算￥{budget.hard_limit}已用完￥{spent}，"
                f"本次任务预计￥{estimated_cost}将超限"
            )
        
        if spent + estimated_cost > budget.soft_limit:
            await notify_user(project_id, "approaching_budget_limit")
```

**平台侧成本优化**：
- 相似Prompt去重（避免重复调用相同生成）
- 首帧缓存复用（同角色同场景可复用）
- 批量任务合并（降低API调用次数）
- 闲时生成折扣（非高峰期降低优先级换取低价）

---

## 第六部分：风险管理与合规考量

### 6.1 技术风险

| 风险类型 | 影响程度 | 发生概率 | 缓解措施 |
|---------|---------|---------|---------|
| 模型API不稳定 | 高 | 中 | 多Provider备份、失败重试、降级策略 |
| 视频生成质量差 | 高 | 高 | 首帧确认机制、多候选选择、人工介入 |
| 一致性引擎误判 | 中 | 中 | 置信度阈值、人工复核、规则可调 |
| 队列积压 | 中 | 中 | 动态扩容、优先级调度、超时熔断 |
| 数据库性能瓶颈 | 中 | 低 | JSONB索引优化、读写分离、缓存层 |
| FFmpeg处理失败 | 低 | 中 | 容器隔离、资源限制、错误重试 |

**应对方案**：
- **模型降级链**（示例）：高质量文本模型 → 备用文本模型 → 低成本文本模型 → 人工介入
- **视频降级链**（示例）：可灵 → Runway → Pika → 本地ComfyUI → 跳过该镜头
- **数据备份**：每日全量备份+实时增量备份，RTO < 4小时

### 6.2 内容合规风险

**平台审核规则**：
```python
class ContentModerationAgent:
    """内容审核Agent"""
    
    async def check_script(self, script: str) -> ModerationReport:
        """剧本合规检查"""
        checks = [
            self._check_political_sensitivity(),  # 政治敏感
            self._check_violence(),                # 暴力血腥
            self._check_sexual_content(),          # 色情低俗
            self._check_illegal_content(),         # 违法信息
            self._check_minor_protection(),        # 未成年保护
            self._check_trademark_infringement()   # 商标侵权
        ]
        
        violations = []
        for check in checks:
            result = await check(script)
            if result.violated:
                violations.append(result)
        
        return ModerationReport(
            passed=len(violations) == 0,
            violations=violations,
            risk_level=self._calculate_risk(violations)
        )
```

**合规检查点**：
1. 剧本导入后立即检查
2. 分镜生成前再次检查
3. 视频生成完成后抽帧检查
4. 导出前最终审核

**风险等级处理**：
- **低风险**：警告提示，允许继续
- **中风险**：强制人工审核确认
- **高风险**：阻断流程，要求修改

### 6.3 数据安全与隐私

**密钥安全**：
```python
from cryptography.fernet import Fernet

class KeyVault:
    """用户密钥加密存储"""
    
    def encrypt_api_key(self, user_id: UUID, provider: str, api_key: str):
        # 使用用户专属密钥加密
        cipher = Fernet(self._get_user_master_key(user_id))
        encrypted = cipher.encrypt(api_key.encode())
        
        await db.execute(
            "INSERT INTO user_keys (user_id, provider, encrypted_key) VALUES (?, ?, ?)",
            (user_id, provider, encrypted)
        )
    
    def get_api_key(self, user_id: UUID, provider: str) -> str:
        """获取解密后的密钥（仅在Worker内存中存在）"""
        encrypted = await db.fetchone(
            "SELECT encrypted_key FROM user_keys WHERE user_id=? AND provider=?",
            (user_id, provider)
        )
        cipher = Fernet(self._get_user_master_key(user_id))
        return cipher.decrypt(encrypted).decode()
```

**数据隔离**：
- 多租户Row-Level Security（PostgreSQL RLS）
- 对象存储按用户分桶，签名URL限时访问
- Worker进程隔离，禁止跨项目数据访问
- 日志脱敏（API密钥、用户手机号、身份证号自动打码）

**敏感数据处理规范**：
| 数据类型 | 处理方式 |
|---------|---------|
| 用户API密钥 | AES-256加密存储，仅Worker解密使用，禁止写入日志 |
| 剧本内容 | 用户可标记为"保密"，跳过云端模型，仅使用本地模型 |
| 角色参考图 | 打水印，禁止未授权下载 |
| 生成Prompt | 可选脱敏模式（隐藏角色真实姓名、IP信息） |
| 项目元数据 | 导出包不包含用户ID、团队信息、成本数据 |

### 6.4 知识产权合规

**开源依赖管理**：
```yaml
# 许可证白名单（示例）
allowed_licenses:
  - MIT
  - Apache-2.0
  - BSD-3-Clause
  - ISC

blocked_licenses:
  - GPL-3.0        # 传染性开源
  - AGPL-3.0       # 服务端开源要求
  - SSPL           # 商业限制
  - Commons Clause # 禁止商业化

review_required:
  - LGPL-2.1       # 需法务评估
  - MPL-2.0        # 需法务评估
```

**第三方内容使用规范**：
- 参考图必须用户自行上传或授权获取
- 不预置任何影视剧、明星、商标相关素材
- 模型训练数据合规性由Provider负责，平台不承担连带责任
- 用户协议明确：生成内容版权归用户，用户需自行承担侵权风险

**AI生成内容声明**：
```python
# 导出包自动附加声明
CONTENT_DISCLAIMER = """
本作品由AI辅助生成，使用了以下技术：
- 文本生成模型：{text_models}
- 图像生成模型：{image_models}
- 视频生成模型：{video_models}

创作者：{user_name}
生成时间：{timestamp}
平台：DramaForge AI短剧工作台

根据《互联网信息服务深度合成管理规定》，本内容已标注为AI生成。
"""
```

---

## 附录A：核心API设计规范

### A.1 项目管理API

**创建项目**：
```http
POST /api/projects
Content-Type: application/json

{
  "name": "霸总的秘密",
  "targetPlatform": "douyin",
  "aspectRatio": "9:16",
  "styleBible": {
    "genre": "urban_romance",
    "visualStyle": "cinematic_realism",
    "colorPalette": ["#1a1a2e", "#16213e", "#e94560"]
  }
}

Response 201:
{
  "id": "proj_abc123",
  "name": "霸总的秘密",
  "stage": "CREATED",
  "createdAt": "2026-07-10T10:30:00Z"
}
```

**导入剧本**：
```http
POST /api/projects/{projectId}/source
Content-Type: multipart/form-data

file: script.txt (或 script.docx)

Response 202:
{
  "jobId": "job_xyz789",
  "status": "processing",
  "estimatedTime": 180  // 秒
}
```

### A.2 资产管理API

**创建角色卡**：
```http
POST /api/projects/{projectId}/characters
Content-Type: application/json

{
  "name": "林雨薇",
  "gender": "female",
  "age": 28,
  "appearance": "黑色长发，冷艳气质，职业装",
  "personality": "表面高冷，内心善良",
  "referenceImages": ["char_ref_001.jpg"],
  "continuityRules": [
    {
      "type": "costume",
      "value": "白色西装套装",
      "scope": "episode_1",
      "locked": true
    }
  ]
}

Response 201:
{
  "id": "char_001",
  "name": "林雨薇",
  "status": "draft",
  "promptTemplate": "A 28-year-old Chinese woman with long black hair..."
}
```

### A.3 生成任务API

**生成镜头首帧**：
```http
POST /api/shots/{shotId}/generate-keyframe
Content-Type: application/json

{
  "provider": "flux",
  "model": "flux-pro-1.1",
  "candidates": 2,
  "seed": null,
  "enhancePrompt": true
}

Response 202:
{
  "jobId": "gen_001",
  "status": "queued",
  "position": 3,
  "estimatedWaitTime": 120
}
```

**SSE事件订阅**：
```http
GET /api/projects/{projectId}/events
Accept: text/event-stream

event: job.started
data: {"jobId": "gen_001", "shotId": "shot_015"}

event: job.progress
data: {"jobId": "gen_001", "progress": 0.45}

event: job.completed
data: {"jobId": "gen_001", "artifacts": [{"id": "art_001", "url": "..."}]}

event: job.failed
data: {"jobId": "gen_001", "error": "API rate limit exceeded"}
```

### A.4 导出API

**导出格式优先级**（`format` 字段取值）：

| 优先级 | 格式 | 规范来源 | 目标用户 | 说明 |
|-------|------|---------|---------|------|
| P0 | `mp4` + `srt` + 素材包 | 通用 | 所有人 | 保底交付，必做 |
| P0 | `jianying_draft` | 逆向兼容 | 国内短剧团队 | 最实际需求，可继续调节奏/字幕/BGM |
| P1 | `davinci_xml`(FCPXML) | 公开规范 | 专业剪辑 | DaVinci Resolve / FCP 通用 |
| P2 | `edl` | 公开规范(CMX3600) | 行业交换 | 最通用的时间线交换格式 |
| P2 | `aaf` | 公开规范(SMPTE) | 广电/专业后期 | 带媒体引用的交换格式 |
| ~~✗~~ | ~~`pr_proj`~~ | ~~私有二进制~~ | ~~—~~ | **不做**：无公开规范、逆向维护成本极高，PR用户经FCPXML/EDL中转导入 |

> **为何删除 PR 工程导出**：Premiere `.prproj` 是私有二进制格式，无公开规范，只能逆向且版本极不稳定，维护成本与收益不成正比。DaVinci XML / EDL / AAF 均有公开规范，一次实现长期可用，且能覆盖 PR 用户（通过中转导入）。

**导出剪映草稿**：
```http
POST /api/projects/{projectId}/export
Content-Type: application/json

{
  "format": "jianying_draft",
  "episodeId": "ep_001",
  "options": {
    "includeSubtitles": true,
    "includeAudio": true,
    "resolution": "1080p"
  }
}

Response 202:
{
  "exportId": "exp_001",
  "status": "processing",
  "estimatedTime": 300
}

// 轮询或SSE获取结果
GET /api/exports/{exportId}
Response 200:
{
  "status": "completed",
  "downloadUrl": "https://storage.../draft_20260710.zip",
  "expiresAt": "2026-07-17T10:30:00Z",
  "fileSize": 524288000
}
```

---

## 附录B：数据库Schema设计

### B.1 核心表结构

**users 表**：
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    role VARCHAR(20) DEFAULT 'member',   -- 'owner'|'admin'|'member'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**user_keys 表**（BYOK密钥，见6.3）：
```sql
CREATE TABLE user_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,       -- 'openai'|'kling'|'jimeng'...
    encrypted_key BYTEA NOT NULL,        -- Fernet加密，禁止明文/入日志
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)
);
```

**projects 表**：
```sql
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    target_platform VARCHAR(50),
    aspect_ratio VARCHAR(10),
    stage VARCHAR(50) NOT NULL DEFAULT 'CREATED',
    style_bible JSONB,
    budget_limit DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_projects_user ON projects(user_id);
CREATE INDEX idx_projects_stage ON projects(stage);
```

**episodes / scenes 表**（层级骨架）：
```sql
CREATE TABLE episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    episode_number INT NOT NULL,
    synopsis TEXT,
    duration_sec INT,
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_episodes_project ON episodes(project_id);

CREATE TABLE scenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    scene_number INT NOT NULL,
    location VARCHAR(200),
    time_of_day VARCHAR(50),
    characters UUID[],
    props UUID[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_scenes_episode ON scenes(episode_id);
```

**characters 表**（含3.7角色一致性字段）：
```sql
CREATE TABLE characters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    gender VARCHAR(20),
    age INT,
    appearance TEXT,
    personality TEXT,
    reference_images TEXT[],
    -- 3.7 角色视觉一致性
    canonical_reference TEXT,            -- 权威正脸图
    reference_set JSONB,                 -- {"front":url,"left":url,"full_body":url,...}
    face_embedding BYTEA,                -- InsightFace 512维特征
    locked_prompt TEXT,                  -- 固定角色Prompt（3.7.5）
    anchor_seed BIGINT,                  -- 固定Seed（3.7.6）
    threshold_profile JSONB,             -- 自适应阈值Profile（3.7.13）
    is_lead BOOLEAN DEFAULT FALSE,
    -- 通用
    prompt_template TEXT,
    continuity_rules JSONB,
    locked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_characters_project ON characters(project_id);
```

**shots 表**：
```sql
CREATE TABLE shots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_id UUID NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    shot_number INT NOT NULL,
    shot_type VARCHAR(50),
    camera_move VARCHAR(50),
    duration_sec DECIMAL(4,2),
    visual_description TEXT,
    dialogue TEXT,
    characters UUID[],
    props UUID[],
    continuity_notes TEXT[],
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_shots_scene ON shots(scene_id);
CREATE INDEX idx_shots_status ON shots(status);
```

**generation_jobs 表**：
```sql
CREATE TABLE generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_id UUID REFERENCES shots(id),
    job_type VARCHAR(50) NOT NULL,  -- 'keyframe', 'video', 'audio'
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    input_spec JSONB NOT NULL,
    prompt_version INT,
    status VARCHAR(50) DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    cost DECIMAL(8,4),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    checkpoint JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_jobs_shot ON generation_jobs(shot_id);
CREATE INDEX idx_jobs_status ON generation_jobs(status);
CREATE INDEX idx_jobs_created ON generation_jobs(created_at);
```

**asset_state_timeline 表**：
```sql
CREATE TABLE asset_state_timeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL,
    asset_type VARCHAR(50) NOT NULL,
    episode_id UUID REFERENCES episodes(id),
    scene_id UUID REFERENCES scenes(id),
    shot_id UUID REFERENCES shots(id),
    state_snapshot JSONB NOT NULL,
    state_changes JSONB,
    locked BOOLEAN DEFAULT FALSE,
    verified_by_user BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_timeline_asset ON asset_state_timeline(asset_id, shot_id);
```

**artifacts 表**（所有生成产物）：
```sql
CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_id UUID REFERENCES shots(id),
    job_id UUID REFERENCES generation_jobs(id),
    artifact_type VARCHAR(50) NOT NULL,  -- 'keyframe'|'video'|'audio'|'subtitle'
    storage_path TEXT NOT NULL,          -- 对象存储key
    file_hash VARCHAR(64),               -- 内容哈希，去重+增量重跑
    version INT DEFAULT 1,
    approved BOOLEAN DEFAULT FALSE,       -- 审核通过（修复不覆盖已审核版本）
    face_similarity DECIMAL(4,3),         -- 人脸相似度（3.7.7）
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_artifacts_shot ON artifacts(shot_id);
CREATE INDEX idx_artifacts_hash ON artifacts(file_hash);
```

**reviews 表**（质检结果，可回链）：
```sql
CREATE TABLE reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    review_type VARCHAR(50),             -- 'consistency'|'face'|'moderation'
    passed BOOLEAN NOT NULL,
    violations JSONB,                    -- 违规列表，含rule_id/severity/repair
    confidence DECIMAL(4,3),
    reviewer VARCHAR(50),                -- 'agent'|'user'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_reviews_artifact ON reviews(artifact_id);
```

**continuity_rules 表**（3.3规则持久化）：
```sql
CREATE TABLE continuity_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50) NOT NULL,           -- 'character_appearance'|'prop_continuity'...
    scope VARCHAR(20) NOT NULL,          -- 'project'|'episode'|'scene'
    condition JSONB NOT NULL,
    enforcement VARCHAR(20) NOT NULL,    -- 'block'|'warn'|'suggest'
    violation_severity VARCHAR(20),      -- 'critical'|'high'|'medium'|'low'
    repair_template TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_rules_project ON continuity_rules(project_id);
```

**production_graphs / graph_nodes 表**（3.8生产图）：
```sql
CREATE TABLE production_graphs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_id UUID NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_graphs_shot ON production_graphs(shot_id);

CREATE TABLE graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_id UUID NOT NULL REFERENCES production_graphs(id) ON DELETE CASCADE,
    node_type VARCHAR(50) NOT NULL,      -- 'keyframe'|'video'|'voice'|'subtitle'|'composite'|'review'|'export'
    executor VARCHAR(100) NOT NULL,      -- 'agent:generation'|'tool:ffmpeg'|'model:flux'...
    depends_on UUID[],                   -- 上游节点
    input_hash VARCHAR(64),              -- 输入指纹，决定缓存命中
    status VARCHAR(20) DEFAULT 'pending',-- pending|running|cached|completed|failed|stale
    artifact_id UUID REFERENCES artifacts(id),
    cost DECIMAL(8,4),
    checkpoint JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_nodes_graph ON graph_nodes(graph_id);
CREATE INDEX idx_nodes_status ON graph_nodes(status);
```

**cost_ledger 表**（镜头级成本追踪）：
```sql
CREATE TABLE cost_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    shot_id UUID REFERENCES shots(id),
    job_id UUID REFERENCES generation_jobs(id),
    provider VARCHAR(50),
    model VARCHAR(100),
    cost DECIMAL(8,4) NOT NULL,
    is_rerun BOOLEAN DEFAULT FALSE,       -- 是否重生成（区分一致性检测触发的重跑成本）
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_cost_project ON cost_ledger(project_id);
```

**exports 表**（导出历史）：
```sql
CREATE TABLE exports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    episode_id UUID REFERENCES episodes(id),
    format VARCHAR(30) NOT NULL,         -- 'mp4'|'jianying_draft'|'davinci_xml'|'edl'|'aaf'
    status VARCHAR(20) DEFAULT 'processing',
    download_url TEXT,
    file_size BIGINT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_exports_project ON exports(project_id);
```

### B.2 关系约束

**外键级联删除策略**：
- Project删除 → 级联删除 Episode、Scene、Character、ContinuityRule、CostLedger、Export
- Episode删除 → 级联删除关联Scene；Scene删除 → 级联删除Shot
- Shot删除 → 级联删除ProductionGraph、GraphNode；**保留GenerationJob和Artifact**（置shot_id为NULL，用于审计）
- Artifact删除 → 级联删除其Review

**审核保护（重要）**：
```sql
-- 修复/重生成不得覆盖已审核通过的版本，只能追加新version
-- 应用层约束：approved=TRUE 的artifact只读
UPDATE artifacts SET approved = TRUE WHERE id = ? AND approved = FALSE;
-- 新版本以 version+1 追加，旧审核版本永久保留
```

**回链能力**：reviews.violations 中的每条记录携带 `rule_id`/`shot_id`/`asset_id`，质检结果可反向定位到 Scene、Shot、Asset、Rule（对应P0验收第5条）。

**并发控制**：
```sql
-- 乐观锁：Shot编辑
ALTER TABLE shots ADD COLUMN version INT DEFAULT 1;

-- 更新时检查版本
UPDATE shots 
SET visual_description = ?, version = version + 1
WHERE id = ? AND version = ?;
```

---

## 附录C：部署架构

### C.1 Docker Compose配置

> **注意**：以下为**开发环境**配置（源码热挂载、`--reload`、明文密码、端口全暴露）。生产部署须：移除源码volume与`--reload`、密码改用Docker secrets/环境注入、数据库与Redis不对外暴露端口、前端改为构建产物由Nginx托管。

```yaml
services:
  web:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      # 前端为 Vite（见1.3技术栈），环境变量须用 VITE_ 前缀，非 NEXT_PUBLIC_
      - VITE_API_URL=http://api:8000
    depends_on:
      - api

  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://drama:password@postgres:5432/dramaforge
      - REDIS_URL=redis://redis:6379/0
      - S3_ENDPOINT=http://minio:9000
    depends_on:
      - postgres
      - redis
      - minio
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --reload

  worker:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://drama:password@postgres:5432/dramaforge
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
    command: python -m app.workers.main
    deploy:
      replicas: 2

  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=drama
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=dramaforge
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    volumes:
      - minio_data:/data
    command: server /data --console-address ":9001"

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

### C.2 生产环境架构

```
                    ┌─────────────┐
                    │   Cloudflare│
                    │   CDN + WAF │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   Nginx LB  │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
    │ Web #1  │      │ Web #2  │      │ Web #3  │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
                    ┌──────┴──────┐
                    │  API Gateway│
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
    │ API #1  │      │ API #2  │      │ API #3  │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
    │Worker#1 │      │Worker#2 │      │Worker#3 │
    │ (Image) │      │ (Video) │      │(FFmpeg) │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
         ┌─────────────────┴─────────────────┐
         │                                   │
    ┌────┴──────┐                    ┌──────┴────┐
    │PostgreSQL │                    │   Redis   │
    │  Cluster  │                    │  Cluster  │
    │(主+2从)    │                    │(3节点)     │
    └───────────┘                    └───────────┘
                                           │
                                    ┌──────┴────┐
                                    │  MinIO    │
                                    │  Cluster  │
                                    │(4节点)     │
                                    └───────────┘
```

### C.3 监控与告警

**Prometheus指标采集**：
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'api'
    static_configs:
      - targets: ['api:8000']
  
  - job_name: 'worker'
    static_configs:
      - targets: ['worker:9090']
  
  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']
```

**关键指标**：
- API响应时间（P50/P95/P99）
- Worker队列长度
- 生成任务成功率
- 数据库连接池使用率
- 对象存储上传/下载速率
- 成本消耗速率（每小时）

**告警规则**：
```yaml
groups:
  - name: dramaforge
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        annotations:
          summary: "API错误率超过5%"
      
      - alert: QueueBacklog
        expr: redis_queue_length > 100
        annotations:
          summary: "任务队列积压超过100个"
      
      - alert: HighCostBurn
        expr: rate(generation_cost_total[1h]) > 1000
        annotations:
          summary: "成本消耗速率超过￥1000/小时"
```

---

## 结语

本规划书为DramaForge AI短剧工作台提供了完整的技术实施路线图。核心设计理念包括：

1. **Production Graph 生产图**：系统真正的核心，每个加工步骤是可缓存、可局部重跑的 Node，Agent 只是其中一类 Node
2. **镜头级可控生产**：非黑盒全自动，每个环节可人工介入
3. **双维度一致性引擎**：剧情连续性（四层）+ 角色视觉一致性（七层，含 Face Embedding 检测闭环）
4. **多模型路由**：用户自带密钥，支持多Provider无缝切换
5. **可交付工程**：导出剪映草稿 / DaVinci XML / EDL / AAF（不做 PR 私有格式），团队可继续编辑

**MVP验收标准**：
- ✅ 从5场剧本生成10个镜头的完整流程可运行
- ✅ 一致性检查能识别服装/道具冲突并给出修复建议
- ✅ 角色人脸相似度达自校准阈值，视频漂移可检测
- ✅ 成本追踪到镜头级，预算超限阻断生成
- ✅ 改字幕/配音不触发图像视频重跑（增量重跑）
- ✅ 导出包含MP4、SRT、剪映草稿、素材包
- ✅ 任务失败可重试，项目可断点续传

**下一步行动**：
1. Week 1-2：搭建开发环境，初始化代码仓库，配置CI/CD
2. Week 3-4：实现核心领域模型和数据库Schema
3. Week 5-7：完成策划Agent、分镜Agent、生成队列、Production Graph骨架
4. Week 8-10：实现双维度一致性引擎（剧情连续性+角色视觉一致性+阈值校准）
5. Week 11-12：导出功能和端到端集成测试

预计**12周**完成MVP，人力成本约￥28万（阶段4扩1周，按周薪顺延），加其他开支总预算约￥29万（不含商业化阶段投入）。

> **建议第一个动手验证的模块**：3.7 角色视觉一致性的 Face Embedding 检测闭环——它是护城河核心，且技术不确定性最高（不同模型的相似度分布差异大）。先用选定图像模型跑通"提特征→算类内分布→定阈值→生成比对"最小链路，确认可用性，再规模化。
---

## 归档文档关系（2026-07-13）

本文不再维护。后续实施、评审和 AI 编码代理必须阅读并遵从根目录 `01_项目总需求.md` 至 `06_受控混合Agent运行时规范.md`；双模式产品决策见 `DramaForge双模式产品与架构汇报方案.md`，技术取舍与实施 Gate 见 `DramaForge架构决策与技术选型书.md`。
