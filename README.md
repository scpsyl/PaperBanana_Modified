# <div align="center">PaperBanana 🍌 (Modified)</div>
<div align="center">基于 <a href="https://github.com/dwzhu-pku/PaperBanana">PaperBanana</a> / <a href="https://github.com/google-research/papervizagent">PaperVizAgent</a> 二次开发</div>

<br>

> 本项目基于 [PaperBanana](https://github.com/dwzhu-pku/PaperBanana)（原始版本：[PaperVizAgent by Google Research](https://github.com/google-research/papervizagent)）进行修改和扩展。原始论文：[arXiv:2601.23265](https://huggingface.co/papers/2601.23265)。感谢原作者的开源贡献。

---

## 改动

### 1. 第三方 API / 代理转发支持

原版仅支持使用官方 API。我们扩展了完整的多 Provider 支持，方便国内用户或使用第三方中转服务：

- **多 Provider 支持**：除 Gemini 外，新增 OpenAI（含 DeepSeek、SiliconFlow 等兼容接口）和 Anthropic (Claude) 的完整调用链路
- **自定义 Base URL**：三个 Provider 均支持自定义 API 端点（`google_base_url`、`openai_base_url`、`anthropic_base_url`），可接入任意第三方中转/代理服务
- **Provider 强制覆盖**：通过 `provider_override` 配置，可在模型名称不符合自动检测规则时（如第三方服务以 `gemini-xxx` 命名但走 OpenAI 协议），手动指定 Provider 路由
- **HTTP 代理支持**：自动读取 `https_proxy` / `HTTPS_PROXY` 环境变量，为 Gemini 客户端配置代理
- **API Version 控制**：`google_api_version` 字段支持自定义 API 版本（留空使用 SDK 默认值）

配置示例（`configs/model_config.yaml`）：
```yaml
provider_override:
  text_model_provider: ""      # 留空=自动检测，可设为 "google"/"openai"/"anthropic"
  image_model_provider: ""

api_base_urls:
  google_base_url: "https://your-proxy.com/v1"
  openai_base_url: "https://api.deepseek.com"
  anthropic_base_url: ""
```

实际测的时候，用初始提供的接口就行，经过实际测试是可以正常走第三方流量。


### 2. Token 消耗优化

原版默认配置下，单次生成会产生 **~90 次 API 调用**（10 个候选 × 9 次调用/候选），导致 第一次跑可能会token 消耗极高。做了以下调整：

| 配置项 | 原版默认 | 修改后 | 效果 |
|--------|---------|--------|------|
| 候选数量 | 10 | **3** | API 调用减少 70% |
| Critic 迭代轮数 | 3 | **1** | 每个候选从 ~9 次调用降到 ~5 次 |
| Retrieval 默认 | auto | **none** | 省掉 Retriever 的 LLM 调用 |
| 并发数 | 硬编码 10 | **跟随候选数** | 避免资源浪费 |

修改后默认配置：3 候选 × 4 调用 = **~12 次 API 调用**，但为了效果好请自己尝试调整。确实critic和refine的次数越多，效果越好

另外，在前端增加了 **费用预估警告**，生成前会显示预计 API 调用次数（绿/黄/红三级提示），避免意外高消费。

### 3. SVG 矢量图导出（vtracer 集成）

集成了 [vtracer](https://github.com/visioncortex/vtracer)（GitHub 5.5k star 的光栅转矢量工具），支持将生成的 PNG 图转换为 SVG 矢量格式，方便在 **Adobe Illustrator / Inkscape** 中二次编辑。

- 安装在独立子目录 `tools/vtracer_converter/` 的隔离虚拟环境中，不影响主项目依赖
- 通过 subprocess 调用，与主流程完全解耦
- 前端每个候选图下方提供 "Export SVG" 按钮，按需转换
- **零 API 成本**：纯本地计算，不消耗任何 token
- 内置 `diagram` 预设参数，针对学术论文图优化（高色彩精度、spline 拟合）

> 这个功能很垃圾，因为这个是基于光栅的，提取出来效果非常不好。建议生成时选4K，自己用illustrator处理一下

### 4. Event Loop 修复

修复了 Streamlit 中多次触发异步操作时的 `Event loop is closed` 错误。将所有 `asyncio.run()` 替换为安全的 `run_async()` 辅助函数，每次创建新的 event loop，确保多次点击按钮不会报错。

---

## 快速开始

### Step 1: 克隆仓库

```bash
git clone https://github.com/scpsyl/PaperBanana_Modified.git
cd PaperBanana_Modified
```

### Step 2: 安装环境

推荐使用 [uv](https://docs.astral.sh/uv/getting-started/installation/) 管理依赖（也可直接用 pip）：

```bash
# 方式一：使用 uv（推荐）
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv python install 3.12
uv pip install -r requirements.txt

# 方式二：直接 pip
pip install -r requirements.txt
```

### Step 3: 配置 API Key 和模型

复制模板配置文件并编辑：

```bash
cp configs/model_config.template.yaml configs/model_config.yaml
```

编辑 `configs/model_config.yaml`，至少需要填写：

```yaml
defaults:
  model_name: "gemini-3.1-pro-preview"            # 文本模型（Planner/Critic 等）
  image_model_name: "gemini-3-pro-image-preview"  # 图像生成模型（Visualizer）

api_keys:
  google_api_key: "你的 API Key"     # Gemini 用户必填
  openai_api_key: ""                  # 使用 OpenAI/DeepSeek 等时填写
  anthropic_api_key: ""               # 使用 Claude 时填写

# 如果使用第三方中转/代理服务，配置自定义 Base URL：
api_base_urls:
  google_base_url: ""                 # 如 "https://your-proxy.com/v1"
  openai_base_url: ""                 # 如 "https://api.deepseek.com"
  anthropic_base_url: ""
```

> 注意：如需大量并发生成候选图，请确保你的 API Key 支持高并发。

### Step 4: 下载数据集（可选）

下载 [PaperBananaBench](https://huggingface.co/datasets/dwzhu/PaperBananaBench) 并放置到 `data/PaperBananaBench/` 目录下。不下载数据集也能正常运行，但会跳过 Retriever Agent 的 few-shot 检索功能。

### Step 5: 安装 vtracer（SVG 导出功能，可选）

```bash
python3 -m venv tools/vtracer_converter/venv
tools/vtracer_converter/venv/bin/pip install vtracer Pillow
```

### 启动 Demo

```bash
streamlit run demo.py
```

### 命令行运行（批量处理）

```bash
# 基础用法
python main.py

# 自定义参数
python main.py \
  --dataset_name "PaperBananaBench" \
  --task_name "diagram" \
  --split_name "test" \
  --exp_mode "dev_full" \
  --retrieval_setting "auto"
```

**可用参数：**
- `--dataset_name`：数据集名称（默认 `PaperBananaBench`）
- `--task_name`：任务类型 `diagram`（论文图）或 `plot`（统计图）
- `--split_name`：数据集分片（默认 `test`）
- `--exp_mode`：实验模式（见下方说明）
- `--retrieval_setting`：检索策略 `auto` / `manual` / `random` / `none`

**实验模式说明：**
| 模式 | 流水线 | 说明 |
|------|--------|------|
| `vanilla` | 直接生成 | 无规划无迭代 |
| `dev_planner` | Planner → Visualizer | 仅规划 |
| `dev_planner_stylist` | Planner → Stylist → Visualizer | 规划+美化 |
| `dev_planner_critic` | Planner → Visualizer → Critic 多轮 | 规划+迭代优化 |
| `dev_full` | 全流水线 | 所有 Agent 参与 |
| `demo_planner_critic` | 同上（跳过评估） | Demo 模式 |
| `demo_full` | 同上（跳过评估） | Demo 模式 |

### 使用说明

1. **生成候选图**：在 "Generate Candidates" 标签页输入方法内容和 caption，点击生成
2. **下载 PNG**：每个候选图下方点击 "⬇️ PNG"
3. **导出 SVG**：点击 "🔄 Export SVG"，转换完成后点击 "⬇️ SVG" 下载
4. **图片精修**：在 "Refine Image" 标签页上传图片进行 2K/4K 精修

### 可视化工具

```bash
# 查看流水线中间结果和演化过程
streamlit run visualize/show_pipeline_evolution.py

# 查看评估结果
streamlit run visualize/show_referenced_eval.py
```

---

## 项目结构

```
├── agents/                        # Agent 模块
│   ├── base_agent.py              # Agent 基类
│   ├── retriever_agent.py         # 检索 Agent
│   ├── planner_agent.py           # 规划 Agent
│   ├── stylist_agent.py           # 美化 Agent
│   ├── visualizer_agent.py        # 可视化 Agent（图像/代码生成）
│   ├── critic_agent.py            # 评审 Agent（迭代优化）
│   ├── vanilla_agent.py           # 基线 Agent（直接生成）
│   └── polish_agent.py            # 精修 Agent
├── configs/
│   ├── model_config.template.yaml # 配置模板
│   └── model_config.yaml          # 用户配置（需自行创建，已 gitignore）
├── utils/
│   ├── config.py                  # 实验配置
│   ├── paperviz_processor.py      # 流水线处理器
│   ├── generation_utils.py        # API 调用工具（支持多 Provider + 自定义 Base URL）
│   ├── eval_toolkits.py           # 评估工具
│   └── image_utils.py             # 图像处理工具
├── tools/                         # [新增] 独立工具
│   └── vtracer_converter/         # SVG 转换工具
│       ├── venv/                  # 隔离的 Python 虚拟环境
│       └── convert.py             # 转换脚本（vtracer 封装）
├── data/PaperBananaBench/         # 数据集（需手动下载）
├── prompts/                       # 评估 Prompt
├── style_guides/                  # 风格指南生成
├── visualize/                     # 可视化工具
├── results/                       # 输出结果
├── demo.py                        # Streamlit 前端（已修改）
├── main.py                        # 命令行入口
├── requirements.txt               # Python 依赖
└── README.md
```

---

## 原版信息

原始项目由 Dawei Zhu, Rui Meng, Yale Song, Xiyu Wei, Sujian Li, Tomas Pfister, Jinsung Yoon 开发。

- 原始论文：[PaperBanana: Automating Academic Illustration for AI Scientists](https://huggingface.co/papers/2601.23265)
- 原始仓库：[PaperBanana](https://github.com/dwzhu-pku/PaperBanana) / [PaperVizAgent](https://github.com/google-research/papervizagent)
- 数据集：[PaperBananaBench](https://huggingface.co/datasets/dwzhu/PaperBananaBench)

```bibtex
@article{zhu2026paperbanana,
  title={PaperBanana: Automating Academic Illustration for AI Scientists},
  author={Zhu, Dawei and Meng, Rui and Song, Yale and Wei, Xiyu and Li, Sujian and Pfister, Tomas and Yoon, Jinsung},
  journal={arXiv preprint arXiv:2601.23265},
  year={2026}
}
```

## License

Apache-2.0（继承自原版）
