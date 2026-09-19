"""从论文 PDF 中抽取三元组，写入 Neo4j 知识图谱。

    python scripts/build_knowledge_graph.py

使用 DeepSeek 以 One-Shot 方式抽取 (头实体-关系-尾实体)，
实体类型限定为 [Model, Dataset, Metric, Task]，
关系类型限定为 [outperforms, evaluated_on, has_metric, uses_method]。
"""

import glob
import json
import os
import sys
import time
import warnings
from pathlib import Path

# 允许以脚本方式直接运行（把项目根目录加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_community.document_loaders import PyPDFLoader  # noqa: E402
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402
from py2neo import Node, Relationship  # noqa: E402

from config import PAPERS_DIR, get_llm, get_neo4j_graph  # noqa: E402

warnings.filterwarnings("ignore")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
API_COOLDOWN = 0.5  # 每次调用后的间隔，避免触发速率限制

ENTITY_TYPES = ["Model", "Dataset", "Metric", "Task"]
RELATION_TYPES = ["outperforms", "evaluated_on", "has_metric", "uses_method"]

EXTRACTION_PROMPT = """
你是一个CV领域科研助手。请阅读以下文本，提取 (实体-关系-实体) 三元组。

【非常重要：输出格式必须严格遵守以下 JSON 示例】
示例输入：ViT 在 ImageNet 上达到了 90% 的准确率。
示例输出：
[
  {{"head": "ViT", "head_type": "Model", "relation": "evaluated_on", "tail": "ImageNet", "tail_type": "Dataset"}},
  {{"head": "ViT", "head_type": "Model", "relation": "has_metric", "tail": "90% accuracy", "tail_type": "Metric"}}
]

【约束条件】
1. 实体类型(head_type/tail_type) 只能是：[Model, Dataset, Metric, Task]
2. 关系(relation) 只能是：[outperforms, evaluated_on, has_metric, uses_method]
3. 必须返回纯 JSON 列表，不要包含 Markdown 格式（如 ```json ... ```）。

【待处理文本】:
{text}
"""


def process_single_pdf(pdf_path: str, graph, chain) -> bool:
    """处理单篇论文，把抽取到的三元组合并进图数据库。"""
    filename = os.path.basename(pdf_path)
    print(f"\n [正在处理] {filename} ...")

    try:
        documents = PyPDFLoader(pdf_path).load()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
        )
        chunks = splitter.split_documents(documents)
        print(f"   -> 切分出 {len(chunks)} 段")

        triples_count = 0
        for i, chunk in enumerate(chunks):
            try:
                response = chain.invoke({"text": chunk.page_content})
                content = (
                    response.content.replace("```json", "").replace("```", "").strip()
                )
                if not content or content == "[]":
                    continue

                for item in json.loads(content):
                    try:
                        if "head_type" not in item or "tail_type" not in item:
                            print(f"    数据格式错误，跳过该条: {item}")
                            continue

                        head = Node(item["head_type"], name=item["head"])
                        tail = Node(item["tail_type"], name=item["tail"])
                        graph.merge(head, item["head_type"], "name")
                        graph.merge(tail, item["tail_type"], "name")
                        graph.merge(Relationship(head, item["relation"], tail))
                        triples_count += 1

                    except KeyError as key_err:
                        print(f"    键名缺失: {key_err} | 原始数据: {item}")
                        continue

                time.sleep(API_COOLDOWN)

            except json.JSONDecodeError:
                print(f"    片段 {i} JSON 解析失败，模型可能返回了非 JSON 内容。")
            except Exception as exc:  # noqa: BLE001
                print(f"    片段 {i} 未知错误: {exc}")

        print(f"    {filename} 处理完毕，入库 {triples_count} 条关系。")
        return True

    except Exception as exc:  # noqa: BLE001
        print(f"    {filename} 读取失败: {exc}")
        return False


def batch_process(folder_path: Path) -> None:
    pdf_files = glob.glob(os.path.join(str(folder_path), "*.pdf"))
    print("=" * 40)
    print(f" 发现 {len(pdf_files)} 篇论文")
    print("=" * 40)

    if not pdf_files:
        print(f" 错误: {folder_path} 下没有 PDF 文件。")
        return

    graph = get_neo4j_graph()
    llm = get_llm(temperature=0.0)
    chain = ChatPromptTemplate.from_template(EXTRACTION_PROMPT) | llm

    success_count = sum(
        1 for pdf in pdf_files if process_single_pdf(pdf, graph, chain)
    )
    print(f"\n 批量任务结束！成功处理 {success_count}/{len(pdf_files)} 篇。")


if __name__ == "__main__":
    batch_process(PAPERS_DIR)
