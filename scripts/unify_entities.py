"""实体消歧与节点合并。

    python scripts/unify_entities.py

图谱构建阶段同一实体常以多种写法出现（如 ViT / Vision Transformer / ViT-B/16）。
本脚本借助 LLM 把这些别名归并到唯一主词，并把别名节点的出入边转移到主词节点，
最后删除冗余节点。

合并逻辑合并了原项目中 unify_entities.py 与 improved_unify_entities.py 两个版本，
采用后者更严格的 Prompt 约束与 Python 侧二次过滤。
"""

import json
import sys
import time
import warnings
from pathlib import Path

# 允许以脚本方式直接运行（把项目根目录加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.prompts import ChatPromptTemplate  # noqa: E402

from config import get_llm, get_neo4j_graph  # noqa: E402

warnings.filterwarnings("ignore")

BATCH_SIZE = 50  # 每次交给 LLM 的实体数量，过大易导致返回不稳定
API_COOLDOWN = 0.5
TARGET_LABEL = "Model"  # 当前仅对 Model 类实体做消歧

RESOLUTION_PROMPT = """
你是一个计算机视觉领域的术语标准化专家。请分析输入列表，找出指代【同一个概念】的同义词。

【输入列表】:
{entities}

【输出示例】
[
  {{"canonical": "ViT", "synonyms": ["Vision Transformer", "ViT-B/16", "ViT-L/14"]}},
  {{"canonical": "ResNet", "synonyms": ["Residual Network", "ResNet-50"]}}
]

【严格约束 - 必须遵守】
1. **仅返回**那些确实包含**两个及以上**不同名称的同义词组。
2. 如果一个实体在列表中没有其他别名，**绝对不要**包含在输出结果中（不要返回它自己）。
3. 保持"主词"（canonical）尽量短且通用。
4. 严格输出纯 JSON 列表，不要包含 Markdown 标记（如 ```json）。
"""


def get_all_entities(graph, label: str = TARGET_LABEL) -> list[str]:
    """读取图中某一类标签下的全部实体名（去重并排序）。"""
    query = f"MATCH (n:{label}) RETURN n.name AS name"
    names = [record["name"] for record in graph.run(query).data() if record["name"]]
    return sorted(set(names))


def merge_nodes(graph, canonical: str, synonym: str, label: str) -> None:
    """把 synonym 节点的出入边转移到 canonical 节点，然后删除 synonym 节点。"""
    print(f"      💉 执行合并: [{synonym}] -> [{canonical}]")

    # 1. 转移入边：别人 -> synonym  变成  别人 -> canonical
    query_in = (
        f"MATCH (other:{label} {{name: $syn}})<-[r]-(start) "
        "RETURN start.name AS start_name, TYPE(r) AS rel_type"
    )
    for record in graph.run(query_in, syn=synonym).data():
        graph.run(
            f"""
            MATCH (start {{name: $start_name}})
            MATCH (main:{label} {{name: $canonical}})
            MERGE (start)-[:{record['rel_type']}]->(main)
            """,
            start_name=record["start_name"],
            canonical=canonical,
        )

    # 2. 转移出边：synonym -> 别人  变成  canonical -> 别人
    query_out = (
        f"MATCH (other:{label} {{name: $syn}})-[r]->(end) "
        "RETURN end.name AS end_name, TYPE(r) AS rel_type"
    )
    for record in graph.run(query_out, syn=synonym).data():
        graph.run(
            f"""
            MATCH (main:{label} {{name: $canonical}})
            MATCH (end {{name: $end_name}})
            MERGE (main)-[:{record['rel_type']}]->(end)
            """,
            canonical=canonical,
            end_name=record["end_name"],
        )

    # 3. 删除旧的同义词节点
    graph.run(f"MATCH (n:{label} {{name: $syn}}) DETACH DELETE n", syn=synonym)


def _filter_valid_groups(groups: list[dict]) -> list[dict]:
    """Python 侧二次过滤：剔除只有自己的组，并去掉空别名。"""
    valid = []
    for group in groups:
        canonical = group.get("canonical", "").strip()
        raw_synonyms = group.get("synonyms", [])
        real_synonyms = [
            s.strip()
            for s in raw_synonyms
            if s.strip() and s.strip().lower() != canonical.lower()
        ]
        if canonical and real_synonyms:
            group["canonical"] = canonical
            group["synonyms"] = [canonical] + real_synonyms
            valid.append(group)
    return valid


def run_resolution() -> None:
    graph = get_neo4j_graph()
    llm = get_llm(temperature=0.0)
    chain = ChatPromptTemplate.from_template(RESOLUTION_PROMPT) | llm

    print(f"--- 1. 获取数据库中的 {TARGET_LABEL} 实体 ---")
    entity_names = get_all_entities(graph)
    total_count = len(entity_names)
    print(f"发现 {total_count} 个 {TARGET_LABEL} 实体，准备分批处理...")

    if total_count < 2:
        print("实体太少，无需消歧。")
        return

    for i in range(0, total_count, BATCH_SIZE):
        batch = entity_names[i : i + BATCH_SIZE]
        print(f"\n📦 正在处理第 {i + 1} 到 {min(i + BATCH_SIZE, total_count)} 个实体...")

        try:
            response = chain.invoke({"entities": json.dumps(batch, ensure_ascii=False)})
            content = (
                response.content.replace("```json", "").replace("```", "").strip()
            )

            if not content.startswith("["):
                print("   ⚠️ AI 返回非 JSON 内容（可能是无同义词），跳过。")
                continue

            groups = _filter_valid_groups(json.loads(content))
            if not groups:
                print("   ✅ 本批次无需要合并的同义词。")
                continue

            print(f"   🔍 发现 {len(groups)} 组有效同义词，开始合并...")

            for group in groups:
                canonical = group["canonical"]
                synonyms = group["synonyms"]

                # 防止 LLM 幻觉生造词：主词必须真实存在于图中
                if canonical not in entity_names:
                    candidates = [s for s in synonyms if s in entity_names]
                    if not candidates:
                        continue
                    canonical = candidates[0]

                for syn in synonyms:
                    if syn == canonical or syn not in entity_names:
                        continue
                    merge_nodes(graph, canonical, syn, TARGET_LABEL)
                    entity_names.remove(syn)

            time.sleep(API_COOLDOWN)

        except json.JSONDecodeError:
            print("   ❌ JSON 解析失败，跳过本批次。")
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ 本批次发生未知错误: {exc}")

    print("\n🎉 所有批次处理完成！实体消歧结束。")


if __name__ == "__main__":
    run_resolution()
