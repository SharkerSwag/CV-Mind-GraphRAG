"""清空 Neo4j 图数据库（危险操作，需二次确认）。

    python scripts/reset_neo4j.py

仅清空 Neo4j 中的节点与关系；向量库不受影响，
如需重建向量库请直接运行 scripts/build_vector_db.py（它会自动覆盖）。
"""

import sys
import warnings
from pathlib import Path

# 允许以脚本方式直接运行（把项目根目录加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import NEO4J_URI, get_neo4j_graph  # noqa: E402

warnings.filterwarnings("ignore")


def reset_neo4j_only() -> None:
    print("=" * 42)
    print("⚠️  准备重置图数据库")
    print("=" * 42)
    print("本次操作将：")
    print("1. [执行] 清空 Neo4j 中的所有节点和关系。")
    print("2. [跳过] 向量库（如需重建请运行 build_vector_db.py）。")

    confirm = input("\n确认继续清空 Neo4j 吗？(输入 yes 确认): ")
    if confirm.strip().lower() != "yes":
        print("操作已取消。")
        return

    try:
        print(f"\n🧹 正在连接 Neo4j ({NEO4J_URI}) ...")
        graph = get_neo4j_graph()

        count_before = graph.run("MATCH (n) RETURN count(n) AS c").data()[0]["c"]
        print(f"当前数据库节点数: {count_before}")

        print("🔥 正在执行 DELETE ALL...")
        graph.delete_all()

        count_after = graph.run("MATCH (n) RETURN count(n) AS c").data()[0]["c"]
        print(f"✅ Neo4j 清空完毕！当前节点数: {count_after}")

    except Exception as exc:  # noqa: BLE001
        print(f"❌ Neo4j 操作失败: {exc}")


if __name__ == "__main__":
    reset_neo4j_only()
