# 代码审查与脱敏记录

本文件记录从毕设原始目录（下称「原目录」）迁移到本仓库过程中，
逐文件审查的结果：发现的安全隐患、修正方式，以及遗留问题。

> 出于安全考虑，本文件不记录任何真实凭据、账号口令或本机路径，
> 涉及处一律以占位符表述。

审查日期：2026-09-19
审查范围：原 `Phrase4/` 下全部 Python 脚本与配置文本（19 个 `.py` + 4 个 `.txt` 伪脚本）

---

## 一、安全隐患

### S1 · LLM API Key 明文泄露 — 🔴 严重

**发现位置（3 处）：**

| 文件 | 形式 |
|---|---|
| `.env` | `DEEPSEEK_API_KEY="<密钥明文>"` |
| `Phrase1/1.1环境配置/testAPI.py` | 直接写在 `openai_api_key=` 参数里 |
| `Phrase1/1.1环境配置/DeepSeek-API Key.txt` | 独立文本文件，文件名即标明用途 |

**处置：**

- 新仓库中三处全部移除，仅保留 `.env.example` 占位符；`.env` 已进 `.gitignore`。
- `config.require_api_key()` 改为从环境变量读取，缺失时抛出带修复指引的 `ConfigError`。

> ⚠️ **待办**：该密钥已在本地明文存放多处，等同于已泄露。
> 请前往 DeepSeek 控制台**吊销并重新签发**，不要直接复用。

### S2 · 数据库口令硬编码 — 🟠 中等

**发现位置（11 处 `.py`）：**

```
Phrase2/2.2图数据库存储/batch_build_graph.py:20
Phrase2/2.2图数据库存储/build_graph_single.py:17
Phrase2/2.2图数据库存储/test_neo4j_import.py:4
Phrase2/2.3知识融合与消歧/unify_entities.py:16
Phrase3/3.1混合检索/test_hybrid_retrieval.py:19
Phrase3/3.2核心引擎/graphrag_engine.py:62
Phrase4/batch_build_graph.py:20
Phrase4/graphrag_engine.py:63
Phrase4/improved_unify_entities.py:21
Phrase4/unify_entities.py:20
Phrase4/reset_database.txt:29
```

统一写作 `Graph("bolt://localhost:7687", auth=("neo4j", "<口令明文>"))`，
即连接地址与账号口令同时以字面量形式散落在源码中。
口令本身属于**弱可猜测模式**（由缩写与常见常数拼接而成），而非随机串，
一旦源码外流极易被字典攻击命中。

**处置：**

- 引入 `config.get_neo4j_graph()` 统一收口，全仓库**再无一处硬编码连接信息**。
- 口令改由 `NEO4J_PASSWORD` 环境变量注入。

> ⚠️ **待办**：若该口令曾在其他项目复用，建议一并更换。

### S3 · 硬编码绝对路径 — 🟡 轻微

**发现 16 处**，形如 `Path(r"<盘符>:\\<原目录>\\.env")`，
分散在 `Phrase1` 至 `Phrase4` 的引擎、应用与流水线脚本中。

**处置：** 全部替换为基于 `Path(__file__).resolve().parent` 的相对定位，
项目整体可迁移到任意路径。

### S4 · 系统用户名泄露 — 🟡 轻微

`Phrase1/1.2非结构化数据 ETL/关于test_vector_store测试的备注.txt` 中粘贴了报错日志，
内含 `<系统盘>:\Users\<本机用户名>\.conda\envs\<虚拟环境名>\...`，
暴露操作系统用户名与虚拟环境名。

**处置：** 该文件属于调试笔记，未迁入新仓库。

### S5 · 个人身份信息（非代码层面）— 🔴 严重

姓名、学号、指导教师姓名出现在**目录名与文件名**中，另有成绩单 PDF。
经 `grep` 确认：**代码内容中零命中**，因此仅涉及文件命名。

**处置：** 相关文件全部留在原目录，未迁入新仓库。详见 `README` 的语料说明。

### S6 · 第三方版权内容 — 🟠 中等

- 向量库 `chroma.sqlite3`（90MB）内含 **10178 条向量及论文原文切片**；
- `papers/` 与 `processed_papers/` 共 **143 篇已发表论文 PDF**。

**处置：** 均不入库。`data/` 下仅保留目录占位符，`.gitignore` 已屏蔽。
README 中说明语料需自行从 arXiv 获取。

---

## 二、代码缺陷

迁移过程中顺带发现以下问题，除标注「保留」外均已修正。

### B1 · 引擎构造参数被静默忽略 — 已修正

`Phrase4/graphrag_engine.py:36` 声明了 `env_path` 参数，
但 `:38` 无条件覆盖为硬编码路径，参数形同虚设，且无法从外部覆盖。
新 `engine.py` 移除该无效参数，改以 `chroma_dir` 提供可控覆盖点。

### B2 · 向量库与引擎的嵌入模型不一致 — 已修正（重要）

| 文件 | 使用的嵌入模型 |
|---|---|
| `Phrase4/build_vector_db_only.txt` | `all-MiniLM-L6-v2` |
| `Phrase4/build_final_db.py` | `moka-ai/m3e-base` |
| `Phrase4/graphrag_engine.py` | `moka-ai/m3e-base` |

若误运行前一个脚本，将得到一个**向量空间不匹配**的向量库——
查询不会报错，只会静默返回无关内容，属于极难排查的隐蔽故障。

新仓库合并为唯一的 `scripts/build_vector_db.py`，模型统一取自
`config.EMBEDDING_MODEL`，保证构建与查询两端永远一致。

### B3 · 无效的环境变量赋值 — 已修正

`Phrase4/build_final_db.py:24` 写入 `os.environ["HF_HOME"] = "1"`。
`HF_HOME` 应指向缓存目录，赋值为 `"1"` 无意义，疑似误写。
新脚本中移除，改为仅设置有效的 `HF_HUB_DISABLE_SYMLINKS_WARNING`。

### B4 · 重复实现 — 已合并

| 重复项 | 处理 |
|---|---|
| `unify_entities.py` × 3（含 `improved_` 版） | 合并为一份，采用 improved 版的严格 Prompt + Python 侧二次过滤 |
| `batch_build_graph.py` × 2 | 保留 Phrase4 版 |
| `graphrag_engine.py` × 2（Phrase3 / Phrase4） | 保留 Phrase4 版 |

### B5 · 模块级副作用 — 已修正

原 `batch_build_graph.py` 在**导入时**即连接 Neo4j 并初始化 LLM，
导致该模块无法被安全 import，任何测试或工具链都会被强制触发外部连接。
已改为在 `batch_process()` 内按需创建。

### B6 · 裸 `except` 吞异常 — 已修正

`Phrase4/app.py:181` 使用裸 `except:` 捕获图谱渲染中的所有异常，
连 `KeyboardInterrupt` 也会被吞掉。已收窄为 `except (IndexError, ValueError)`。

### B7 · 去重丢失顺序 — 已修正

`Phrase4/graphrag_engine.py:132` 用 `list(set(context))` 去重，
集合无序导致每次运行拼给 LLM 的上下文顺序不稳定。
已改为 `list(dict.fromkeys(context))`，去重同时保持插入顺序。

### B8 · SQL 参数未参数化 — 已修正

原图谱查询把 `LIMIT 5` 写死在 Cypher 字符串里。
已改为 `LIMIT $limit` 参数绑定，并把返回列重命名为可读别名。

### B9 · 已弃用的 matplotlib 参数 — 已修正

`evaluate_system.py:179` 的 `boxplot(labels=...)` 自 matplotlib 3.9 起弃用，
已替换为 `tick_labels=`（当前锁定的 3.10.8 支持）。

### B10 · 未修正项（保留原状）

- `langchain_community.embeddings.HuggingFaceEmbeddings` 属已弃用导入路径，
  官方已迁移至 `langchain-huggingface`。经确认该路径在锁定的
  `langchain-community==0.4.1` 中**仍可用**（`__all__` 中仍导出），
  为避免增加未经验证的依赖，暂保留原写法。
- `scripts/unify_entities.py` 的合并 Cypher 使用 f-string 拼接 `rel_type`。
  该值来自数据库自身的关系类型（非用户输入），且 Cypher 不支持参数化
  关系类型，风险可控，保留并在代码中标注。
- 实体消歧仍仅覆盖 `Model` 类型，与原始实现一致。

---

## 三、迁移后的验证

### 3.1 语法与导入结构

对全部 8 个 Python 模块执行 `python -m py_compile`：

```
OK  config.py
OK  engine.py
OK  app.py
OK  evaluate_system.py
OK  scripts/build_vector_db.py
OK  scripts/build_knowledge_graph.py
OK  scripts/unify_entities.py
OK  scripts/reset_neo4j.py
```

### 3.2 敏感信息反向扫描

对新仓库整体执行与审查阶段相同的扫描规则，结果：

| 扫描项 | 规则 | 结果 |
|---|---|---|
| LLM 密钥 | `sk-` 前缀长串 | 0 命中 |
| 数据库口令 | 已知口令字面量 | 0 命中 |
| 绝对路径 | 盘符 + 反斜杠 | 0 命中 |
| 本机路径 | `C:/`、`/Users/`、`/home/` | 0 命中 |
| 个人身份信息 | 姓名 / 学号 / 导师 / 用户名 | 0 命中 |

初次扫描曾在 `docs/AUDIT.md` 自身命中——审计文档为说明问题而复述了凭据原文。
已全部改为占位符表述，复查通过。

> 说明：扫描中 `https://` 会被宽松的路径正则误伤，最终以「盘符 + 反斜杠」
> 严格规则为准。

### 3.3 尚未验证

**端到端运行未验证。** 本仓库未安装依赖、未启动 Neo4j、未准备语料，
因此下列链路需在目标环境中实际跑通一次方可确认：

```
pip install -r requirements.txt
  → scripts/build_vector_db.py
  → scripts/build_knowledge_graph.py
  → scripts/unify_entities.py
  → streamlit run app.py
```

其中风险最高的是 `requirements.txt` 的版本匹配——LangChain 1.x 生态
版本耦合紧密，若安装时解析出不同版本组合，可能出现导入失败。

---

## 四、遗留待办

1. **吊销并重新签发 DeepSeek API Key**（S1）。
2. 若 Neo4j 口令曾在他处复用，一并更换（S2）。
3. 在目标环境执行 `pip install -r requirements.txt` 并跑通全链路；
   通过后建议 `pip freeze > requirements.lock` 固化完整依赖树。
4. 确认 `LICENSE` 中的版权署名是否需要调整。
5. 中期考虑迁移至 `langchain-huggingface`，消除 B10 中的弃用告警。
