"""GraphRAG 混合检索引擎。

架构：DeepSeek (LLM) + Neo4j (知识图谱) + Chroma (向量库) + BGE Cross-Encoder (重排)。

三路协同的查询流程：
    1. LLM 抽取问题中的核心实体关键词
    2. 图上做模糊匹配，召回结构化三元组（实体—关系—实体）
    3. 向量库粗召回 Top-K，再用 Cross-Encoder 精排，保留高分文献片段
    4. 图谱事实 + 文献片段拼装为混合上下文，交给 LLM 按思维链生成答案
"""

import logging
import os
import warnings
from pathlib import Path
from typing import Any

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import (
    CHROMA_DIR,
    EMBEDDING_MODEL,
    GRAPH_RELATION_LIMIT,
    RECALL_TOP_K,
    RERANK_TOP_K,
    RERANKER_MODEL,
    get_llm,
    get_neo4j_graph,
)

# HuggingFace 在 Windows 下的符号链接警告没有实际影响，屏蔽掉。
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [GraphRAG] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Engine")


class GraphRAGQueryEngine:
    """GraphRAG 混合检索查询引擎。"""

    def __init__(self, chroma_dir: Path | str | None = None):
        self.chroma_dir = Path(chroma_dir) if chroma_dir else CHROMA_DIR
        self._init_connections()

    # ------------------------------------------------------------ 初始化
    def _init_connections(self) -> None:
        try:
            self.llm = get_llm(temperature=0.1)  # 低温保证事实准确性
            self.graph = get_neo4j_graph()

            if not self.chroma_dir.exists():
                raise FileNotFoundError(
                    f"向量库未找到：{self.chroma_dir}\n"
                    "请先运行  python scripts/build_vector_db.py"
                )

            logger.info("正在加载 Embedding 模型 (%s)...", EMBEDDING_MODEL)
            self.embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
            self.vector_store = Chroma(
                persist_directory=str(self.chroma_dir),
                embedding_function=self.embeddings,
            )
            self.retriever = self.vector_store.as_retriever(
                search_kwargs={"k": RECALL_TOP_K}
            )

            logger.info("正在加载 Rerank 模型 (%s)...", RERANKER_MODEL)
            from sentence_transformers import CrossEncoder

            self.reranker = CrossEncoder(RERANKER_MODEL)

            logger.info(">>> GraphRAG 引擎初始化就绪 <<<")

        except Exception as exc:  # noqa: BLE001 - 向上抛出前统一记录
            logger.error("引擎初始化失败: %s", exc)
            raise

    # ------------------------------------------------------------ 步骤 1
    def _extract_keywords(self, question: str) -> list[str]:
        """从用户问题中抽取 1-3 个核心实体关键词。"""
        template = (
            "你是一个查询分析专家。请从用户的问题中提取 1-3 个核心实体关键词。\n"
            "要求：\n"
            "1. 只返回实体名称（如模型名、数据集名）。\n"
            "2. 用英文逗号分隔。\n"
            "3. 不要包含任何其他废话。\n"
            "用户问题: {question}"
        )
        chain = ChatPromptTemplate.from_template(template) | self.llm | StrOutputParser()
        result = chain.invoke({"question": question})

        keywords = [k.strip() for k in result.split(",") if k.strip()]
        logger.info("提取关键词: %s", keywords)
        return keywords

    # ------------------------------------------------------------ 步骤 2
    def _query_graph(self, keywords: list[str]) -> list[str]:
        """在知识图谱上做模糊匹配，返回格式化的三元组文本。"""
        context: list[str] = []
        cypher = """
        MATCH (n)-[r]->(m)
        WHERE toLower(n.name) CONTAINS toLower($key)
        RETURN n.name AS source, type(r) AS rel, m.name AS target
        LIMIT $limit
        """
        for key in keywords:
            for item in self.graph.run(
                cypher, key=key, limit=GRAPH_RELATION_LIMIT
            ).data():
                context.append(
                    f"图谱事实: {item['source']} --[{item['rel']}]--> {item['target']}"
                )

        unique_context = list(dict.fromkeys(context))  # 去重且保持顺序
        logger.info("图谱召回: %d 条关系", len(unique_context))
        return unique_context

    # ------------------------------------------------------------ 步骤 3
    def _query_vector_with_rerank(self, question: str) -> list[str]:
        """向量粗召回 + Cross-Encoder 精排。"""
        docs = self.retriever.invoke(question)
        if not docs:
            return []

        pairs = [[question, doc.page_content] for doc in docs]
        scores = self.reranker.predict(pairs)

        scored_docs = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        context = [
            f"文献片段 (相关性得分 {score:.2f}): {doc.page_content}"
            for doc, score in scored_docs[:RERANK_TOP_K]
        ]

        logger.info("向量检索(重排后): 返回 %d 条高分文档", len(context))
        return context

    # ------------------------------------------------------------ 对外接口
    def query(self, question: str) -> dict[str, Any]:
        """执行完整的 GraphRAG 查询流程，返回答案与两路溯源证据。"""
        keywords = self._extract_keywords(question)
        graph_context = self._query_graph(keywords)
        vector_context = self._query_vector_with_rerank(question)

        full_context = (
            "【结构化知识 (来自知识图谱)】:\n"
            + "\n".join(graph_context)
            + "\n\n"
            + "【非结构化细节 (来自文献原文)】:\n"
            + "\n".join(vector_context)
        )

        template = """
        你是一名计算机视觉(CV)领域的科研专家助手。请基于以下混合知识库回答用户的问题。

        【思维链要求】
        1. **优先分析图谱知识**：查看实体之间的明确关系（如 outperforms, evaluated_on）。
        2. **补充文献细节**：从文献片段中寻找具体的实验数据、架构细节或参数。
        3. **综合推理**：如果图谱和文本有冲突，以图谱中的事实关系为准。
        4. **学术风格**：回答应专业、逻辑严密，避免口语化。

        【知识上下文】
        {context}

        用户问题: {question}
        """
        chain = ChatPromptTemplate.from_template(template) | self.llm | StrOutputParser()
        answer = chain.invoke({"context": full_context, "question": question})

        return {
            "answer": answer,
            "source_graph": graph_context,
            "source_vector": vector_context,
        }


if __name__ == "__main__":
    print("--- 引擎自检程序启动 ---")
    test_q = "ViT 和 ResNet 的主要区别是什么？"
    try:
        engine = GraphRAGQueryEngine()
        print(f"\n正在提问: {test_q} ...")
        result = engine.query(test_q)
        print("\n" + "=" * 50)
        print("模型回答:")
        print("=" * 50)
        print(result["answer"])
        print("\n自检通过：Rerank 模型加载成功，中文 Prompt 生效。")
    except Exception as exc:  # noqa: BLE001
        print(f"\n自检失败: {exc}")
