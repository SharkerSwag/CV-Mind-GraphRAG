# 发布前检查清单

本文档记录本仓库从当前状态到「可公开发布」之间还差的工作，按优先级排序。
完成一项勾掉一项。

状态时间：2026-09-19

---

## 当前完成度总览

| 维度 | 状态 | 缺口 |
|---|---|---|
| 核心功能代码 | ✅ 已脱敏、语法通过 | 迁移后未实机运行 |
| 配置分离 | ✅ `config.py` 统一收口 | — |
| 依赖声明 | ⚠️ 版本真实但未实测 | 需干净环境验证 |
| 文档 | ⚠️ README + AUDIT 齐全 | 缺截图、缺运行示例 |
| 许可证 | ✅ MIT | 署名待确认 |
| `.gitignore` | ✅ 已修正全局 `*.png` 误伤 | — |
| 测试 | ❌ 零测试 | 需至少补 smoke test |
| CI | ❌ 无 | 可选 |
| Git 仓库 | ❌ 未 `git init` | 待初始化 |
| 截图素材 | ⚠️ 有，但需筛选与裁剪 | 见 P1-1 |

**结论：开源发布可行，但需先完成 P0 全部 4 项。在线部署不建议（见文末）。**

---

## P0 · 阻塞项（不做完不应发布）

### ☑ P0-1　吊销并重新签发 DeepSeek API Key

**已完成（2026-09-19，作者操作）。** 旧密钥已吊销。

- ☑ 吊销旧 Key
- ☑ 新 Key 只写入本机 `.env`（该文件已被 `.gitignore` 屏蔽）
- ☑ 确认 `.env` 不在 `git status` 输出中

### ☐ P0-2　在干净环境跑通全链路

仓库内的 `requirements.txt` 版本号取自作者本机环境，**从未在干净环境中验证过**。
未经验证的依赖清单，对使用者等于没有。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

逐段验证：

- ☐ `python -c "import config"` 无报错
- ☐ 启动 Neo4j，`.env` 填好凭据
- ☐ `python scripts/build_vector_db.py`（可先只放 2-3 篇 PDF 试跑）
- ☐ `python scripts/build_knowledge_graph.py`
- ☐ `python scripts/unify_entities.py`
- ☐ `streamlit run app.py`，能提问并返回带溯源的回答

跑通后固化完整依赖树：

```bash
pip freeze > requirements.lock
```

> ⚠️ 风险最高的一步。LangChain 1.x 生态版本耦合紧密，
> 若 pip 解析出不同组合，可能出现导入失败。

### ☑ P0-3　确认 LICENSE 署名

**已完成（2026-09-19，作者确认署名 `Sharker` 无需调整）。**

### ☐ P0-4　初始化 Git 仓库并检查首提交内容

```bash
git init
git add -A
git status          # ← 关键：逐项确认没有误加数据文件或 .env
git commit -m "Initial commit: CV-Mind GraphRAG knowledge engine"
```

- ☐ 确认 `data/papers/` 与 `data/chroma_db/` 下除 `.gitkeep` 外无内容
- ☐ 确认 `.env` 未出现在待提交列表
- ☐ 确认仓库体积在 200KB 量级（当前 101KB）

---

## P1 · 发布质量项（建议发布前完成）

### ☐ P1-1　整理 README 配图

原项目 `Phrase4/` 下有可用截图，但**必须先筛选**：

| 素材 | 用途 | 可用性 |
|---|---|---|
| `Result/界面3.png` | 主视觉：完整问答 + 侧栏关系图 | ✅ 可用 |
| `Result/界面1.png` | 首屏 | ✅ 可用 |
| `运行结果/知识网络.png` | Neo4j 图谱全局（1000 节点 / 1300 关系） | ✅ 可用 |
| `Result/控制台输出.png` | — | ❌ **禁用** |

> 🚫 **`控制台输出.png` 不可发布**：画面中含
> `<系统盘>:\Users\<本机用户名>\.conda\...` 与 `<盘符>:\<原目录>\Phrase4`
> 两类本地路径信息，会直接暴露使用者身份与目录结构。

建议做法：把可用图裁剪后放入 `docs/images/`，在 README 架构图下方插入，
并顺手裁掉右下角的小块水印残留。

### ◐ P1-2　README 补充启动教程与运行示例

- ☑ **启动教程已完成（2026-09-19）**：六步图文流程、每步的成功标志、
  以及常见问题排查表已写入 README。
- ☐ 仍缺一段真实问答样例（可直接引用 `界面3.png`，或粘贴一次完整问答输出）。

### ☐ P1-3　README 明确定位为「本地运行型项目」

避免使用者误以为可以一键部署到云端。需说明三条硬性依赖：
Neo4j 实例、本地向量库、常驻 2-3GB 内存。

### ☐ P1-4　补一段「数据版权」声明

仓库不含任何论文原文，语料需自行获取。当前 README 文末有一句话，
建议在前言处再加一句显式声明。

### ☐ P1-5　补充已知数据瑕疵

Neo4j 导出数据显示，实际图谱中出现了 Schema 未声明的
`trained_on` 关系类型（1 条）——说明 LLM 抽取时的类型约束并非 100% 生效。
建议写入 README 「已知限制」，属诚实披露，也便于他人复现时对照。

---

## P2 · 可选增强项

### ☐ P2-1　最小化 smoke test

不依赖 Neo4j 与 API 的纯函数级测试即可，例如：

- `config` 在缺少环境变量时抛出 `ConfigError`
- 实体消歧的 `_filter_valid_groups()` 能剔除只有自己的组
- 图谱三元组文本的解析逻辑（`app.py` 中那段 `--[` 切分）

### ☐ P2-2　GitHub Actions

在 `.github/workflows/ci.yml` 中跑 `ruff` + `pytest`，
成本低，且能让仓库看起来是被认真维护的。

### ☐ P2-3　CHANGELOG

记录从毕设原始版本到本仓库的整理过程（可直接从 `docs/AUDIT.md` 的第二节提炼）。

### ☐ P2-4　技术债：迁移到 `langchain-huggingface`

`langchain_community.embeddings.HuggingFaceEmbeddings` 与
`langchain_community.vectorstores.Chroma` 均已标记弃用。
当前锁定版本中仍可用，故未改动。待 LangChain 生态稳定后再统一迁移。

---

## 关于「部署上线」

**不建议，且在当前架构下基本不可行。** 四条硬性阻碍：

| 需求 | 障碍 |
|---|---|
| Neo4j 图数据库 | 主流免费 PaaS 不提供托管实例 |
| ~103MB 向量库 + 语料 | 版权不允许随仓库分发，而在线 Demo 必须内置 |
| 嵌入 + 重排模型常驻 | 内存约 2-3GB，Streamlit 免费档仅 1GB |
| DeepSeek API | 需付费 Key，公开 Demo 会被他人消耗额度 |

**定位建议**：这是「可复现的开源研究代码」，不是「可在线体验的产品」。
硬要做在线 Demo，只能退化成预录回答加静态图谱展示，反而失去项目本身的意义。

> ⚠️ 若未来确实要挂公开 Demo，务必为 API Key 设置用量上限，
> 否则可能被他人脚本刷爆额度。
