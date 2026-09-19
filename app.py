"""CV-Mind 科研文献知识引擎 — Streamlit 前端。

启动::

    streamlit run app.py
"""

import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

from config import CHROMA_DIR
from engine import GraphRAGQueryEngine

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="CV-Mind | 科研文献知识引擎",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .stDeployButton {display:none;}
    footer {visibility: hidden;}
    [data-testid="stSidebar"] {
        background-color: #f7f9fc;
        border-right: 1px solid #e0e0e0;
    }
    .caption-text { font-size: 12px; color: #666; }
    .main .block-container { padding-top: 2rem; }
</style>
""",
    unsafe_allow_html=True,
)


# --- 2. 初始化核心 ---
@st.cache_resource
def get_engine() -> GraphRAGQueryEngine:
    return GraphRAGQueryEngine()


if not CHROMA_DIR.exists():
    st.error(
        "❌ 未找到向量库。请先放置论文 PDF 到 `data/papers/`，"
        "然后运行 `python scripts/build_vector_db.py`。"
    )
    st.stop()

try:
    engine = get_engine()
except Exception as exc:  # noqa: BLE001
    st.error(f"❌ 系统启动失败: {exc}")
    st.stop()

# --- 3. 侧边栏 ---
with st.sidebar:
    st.title("🕸️ CV-Mind 控制台")

    st.markdown("### 📚 知识库状态")
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("🟢")
    with col2:
        st.caption("CV 领域科研文献知识库")

    st.markdown("---")

    st.header("🔭 知识图谱透视")
    st.info("💡 提问后，此处将渲染 Neo4j 风格的动态实体关系网。")

    graph_container = st.empty()

# --- 4. 主界面 ---
st.title("🤖 计算机视觉科研文献助手")
st.markdown("#### 基于 GraphRAG 的混合推理引擎")

if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": (
            "你好！我是基于 GraphRAG 技术构建的 CV 领域科研专家。\n"
            "我的知识库覆盖 **Backbone 设计、目标检测、语义分割、多模态大模型** 等方向。\n\n"
            "你可以问我任何关于模型架构、实验对比或技术演进的问题。"
        ),
    }]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 5. 核心交互逻辑 ---
if prompt := st.chat_input("请输入科研问题... (例如: 介绍一下 YOLO 系列的发展历程)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("🧠 深度检索中 (DeepSeek Reasoning + Graph Traversal)..."):
            try:
                response = engine.query(prompt)
                answer = response["answer"]
                st.markdown(answer)

                # === 来源展示 ===
                with st.expander("🔍 溯源证据 (Evidence & References)"):
                    if response["source_graph"]:
                        st.markdown("**🔗 结构化知识链 (Knowledge Graph Path):**")
                        for idx, fact in enumerate(response["source_graph"]):
                            clean_fact = fact.replace("图谱事实: ", "").replace(
                                "Graph Fact: ", ""
                            )
                            st.markdown(f"**{idx + 1}.** {clean_fact}")

                    if response["source_vector"]:
                        st.divider()
                        st.markdown("**📄 文献原文片段 (Literature Context):**")
                        for idx, doc in enumerate(response["source_vector"]):
                            st.caption(f"**[{idx + 1}]** {doc}")

                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )

                # === Neo4j 风格图谱渲染 ===
                if response["source_graph"]:
                    nodes: list[Node] = []
                    edges: list[Edge] = []
                    node_ids: set[str] = set()

                    COLOR_SOURCE = "#57C7E3"
                    COLOR_TARGET = "#F79767"
                    COLOR_EDGE = "#A5ABB6"

                    for fact in response["source_graph"]:
                        try:
                            clean_fact = fact.split(": ", 1)[-1]
                            if "--[" not in clean_fact:
                                continue
                            parts = clean_fact.split(" --[")
                            src = parts[0].strip()
                            rel_part = parts[1].split("]--> ")
                            rel = rel_part[0].strip()
                            tgt = rel_part[1].strip()

                            if src not in node_ids:
                                nodes.append(Node(
                                    id=src, label=src, size=20, color=COLOR_SOURCE,
                                    symbolType="circle",
                                    font={"color": "black", "size": 12},
                                ))
                                node_ids.add(src)
                            if tgt not in node_ids:
                                nodes.append(Node(
                                    id=tgt, label=tgt, size=15, color=COLOR_TARGET,
                                    symbolType="circle",
                                    font={"color": "black", "size": 10},
                                ))
                                node_ids.add(tgt)

                            edges.append(Edge(
                                source=src, target=tgt, label=rel,
                                color=COLOR_EDGE, type="arrow",
                            ))
                        except (IndexError, ValueError):
                            continue

                    config = Config(
                        width=None, height=450, directed=True, physics=True,
                        hierarchy=False, nodeHighlightBehavior=True,
                        highlightColor="#F7A7A6", collapsible=True,
                        stabilization=True,
                    )

                    with st.sidebar:
                        graph_container.empty()
                        st.markdown("### 🕸️ 实体关系网络")
                        agraph(nodes=nodes, edges=edges, config=config)

            except Exception as exc:  # noqa: BLE001
                st.error(f"生成回答时发生错误: {exc}")
