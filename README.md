# 社媒行情洞察 Agent

一个多 Agent 协作的社媒行情洞察系统：输入一个研究主题，系统自动规划检索策略、并行采集 7 大社媒平台（小红书/抖音/快手/B站/微博/贴吧/知乎）的**图文帖子和真实评论**、多维度分析（市场热度/真实声音/痛点机会/竞品题材），产出带真实来源链接的行情洞察报告。

> 典型场景：独立游戏选题验证、品类趋势研究、玩家需求洞察。

## 核心特性

- **多 Agent 协作**：Planner（规划）→ Researcher（采集）→ Evaluate（质量评估）→ Analyst ×4（并行分析）→ Vision（多模态识图）→ Reporter（综合成报告）
- **Plan-Execute-Replan 闭环**：评估节点判定采集质量，失败反馈携带「平台 + 当时关键词」给 Planner 重规划（限次防震荡），单平台失败降级不炸全局
- **LangGraph 并行编排**：用 `Send` API 实现 fan-out/fan-in，4 个分析维度并行执行
- **真实社媒数据**：封装 MediaCrawler，CDP 模式复用浏览器登录态；跨平台并行采集，每平台独立 CDP 调试端口防端口竞态；运行目录隔离防跨主题数据串染
- **多模型轮询 + 兜底**：LLM 层支持多模型轮询、失败自动切换、结构化输出（tool-calling 强制 schema + 字段校验兜底）
- **反幻觉设计**：真实日期注入、sources 白名单机制，杜绝模型编造来源与过时年份关键词
- **量化评测**：LLM-as-judge 五维度对照实验（单 Agent vs 多 Agent）
- **Web UI**：Streamlit 暗色仪表盘，实时展示流水线执行进度

## 架构

```
输入主题
  │
  ▼
Planner ── 拆解成 3~5 个子问题 + 按平台定制的关键词（tool-calling 结构化输出）
  │
  ▼
Researcher ── 跨平台并行采集图文+评论（MediaCrawler，每平台独立 CDP 端口）
  │
  ▼
Evaluate ── 统计各平台采集量 ──(无效)──► Replanner 重规划一次后回到 Researcher
  │ (有效)
  ▼ (fan-out)
Analyst × 4 ── 市场热度 / 真实声音 / 痛点机会 / 竞品题材（并行）
  │
  ▼ (fan-in)
Vision ── 点赞 Top 帖子配图多模态分析（美术风格 / 视觉内容）
  │
  ▼
Reporter ── 注入真实日期，综合成 Markdown 报告 + 真实来源链接
```

## 技术栈

- **Python 3.12**
- **LangGraph** — 多 Agent 编排
- **MediaCrawler** — 采集底座（vendor 目录，CDP 模式）
- **OpenAI SDK** — LLM 调用（DeepSeek-V4-Flash / SenseNova-6.8-Flash-Lite）
- **SQLite** — 数据存储
- **Streamlit** — Web UI

## 目录结构

```
social-insight-agent/
├── app.py                      # Streamlit 前端
├── main.py                     # CLI：采集并落库
├── src/
│   ├── agents/                 # Planner / Analyst / Vision / Reporter / SearchAgent（单 Agent 基线）
│   ├── orchestration/graph.py  # LangGraph 编排图（含 Evaluate 重规划回路）
│   ├── llm/client.py           # LLM 客户端（轮询/兜底/tool-calling 结构化输出/识图）
│   ├── evaluation/benchmark.py # LLM-as-judge 对照评测
│   ├── tools/                  # 采集层 Adapter（封装 MediaCrawler）
│   ├── models/schemas.py       # 数据模型
│   └── storage/db.py           # SQLite 存储
├── vendor/MediaCrawler/        # 采集底座（不改源码）
├── data/                       # 原始数据 + 报告 + 数据库
└── docs/design.md              # 设计方案
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
pip install -r vendor/MediaCrawler/requirements.txt
```

### 2. 配置环境变量

复制 `.env` 并填写你的 LLM 配置：

```ini
LLM_BASE_URL=https://token.sensenova.cn/v1
LLM_API_KEY=你的key
LLM_MODELS=deepseek-v4-flash,sensenova-6.8-flash-lite
LLM_VISION_MODEL=sensenova-6.8-flash-lite
```

### 3. 采集配置（真实采集需要）

1. 浏览器登录目标平台（CDP 模式复用登录态；首次运行弹出浏览器扫码登录一次，之后自动复用）
2. 各平台使用独立的 CDP 调试端口与浏览器用户目录，可多平台同时采集

### 4. 运行

**Web UI（推荐）：**

```bash
streamlit run app.py
```

**CLI 采集：**

```bash
python main.py --platform xhs --keyword "独立游戏" --limit 20
```

## 使用说明

Web UI 提供两种采集模式：

- **演示模式**：复用已落库的数据，秒出结果（用于快速查看流水线效果）
- **真实采集**：启动浏览器联网抓取（较慢，约数分钟）

## 免责声明

本项目仅用于技术学习与研究，不用于商业用途。采集数据时请遵守目标平台的服务条款，控制请求频率，不对平台造成运营干扰。MediaCrawler 采用非商业学习许可，请一并遵守。
