"""GraphRAG vs Naive RAG 对照评测。

    python evaluate_system.py

用同一套问题分别问 GraphRAG 混合检索与纯向量检索（Naive RAG），
再由 LLM 充当裁判按 0-10 分打分，最后输出 Excel 明细与可视化面板。

产物写入 outputs/ 目录。
"""

import json
import logging
import time
import warnings
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
try:
    from langchain_core._api.deprecation import LangChainDeprecationWarning

    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except ImportError:
    pass

# 强制使用非交互后端，避免 Tcl/Tk 报错
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from langchain_core.output_parsers import StrOutputParser  # noqa: E402
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402

from config import OUTPUT_DIR  # noqa: E402
from engine import GraphRAGQueryEngine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [EVAL] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Evaluator")

API_COOLDOWN = 1  # 每题之间的间隔，避免触发速率限制


class SystemEvaluator:
    """对照评测器：GraphRAG vs Naive RAG。"""

    def __init__(self, engine: GraphRAGQueryEngine):
        self.engine = engine
        self.judge_llm = self.engine.llm

    # ------------------------------------------------------------ 基线实现
    def _generate_naive_rag_response(self, question: str) -> str:
        """Naive RAG 基线：仅使用向量检索，不做图谱增强。"""
        try:
            vector_context = self.engine._query_vector_with_rerank(question)
            context_str = "\n".join(vector_context) or "未检索到相关文档。"

            template = (
                "基于以下文献片段回答问题。如果不确定，请说明。\n"
                "【文献片段】:\n{context}\n\n"
                "问题: {question}"
            )
            chain = (
                ChatPromptTemplate.from_template(template)
                | self.engine.llm
                | StrOutputParser()
            )
            return chain.invoke({"context": context_str, "question": question})
        except Exception as exc:  # noqa: BLE001
            logger.error("Naive RAG generation failed: %s", exc)
            return "Error in generation."

    # ------------------------------------------------------------ LLM 裁判
    def _evaluate_answer(
        self, question: str, ground_truth: str, generated_answer: str
    ) -> dict[str, Any]:
        template = """
        你是一名严格的 CV 领域论文评审专家。请评估系统回答的质量。

        【标准答案】: {ground_truth}
        【用户问题】: {question}
        【系统回答】: {generated_answer}

        请打分 (0-10分):
        - 10分: 完美覆盖核心机制，逻辑严密，无事实错误。
        - 7-9分: 核心点正确，但细节稍有缺失或啰嗦。
        - 4-6分: 遗漏关键机制（如未提到Stop-gradient），或有轻微幻觉。
        - 0-3分: 答非所问，或存在严重事实错误。

        请严格按 JSON 格式输出:
        {{
            "score": <浮点数>,
            "reason": "<简短评语>"
        }}
        """
        try:
            chain = (
                ChatPromptTemplate.from_template(template)
                | self.judge_llm
                | StrOutputParser()
            )
            result = chain.invoke({
                "question": question,
                "ground_truth": ground_truth,
                "generated_answer": generated_answer,
            })
            cleaned = result.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except Exception:  # noqa: BLE001
            return {"score": 0.0, "reason": "Eval Error"}

    # ------------------------------------------------------------ 主流程
    def run_benchmark(self, dataset: list[dict]) -> pd.DataFrame:
        results = []
        logger.info("🚀 开始全量压测，共 %d 道题目...", len(dataset))

        for idx, item in enumerate(dataset):
            question = item["question"]
            ground_truth = item["ground_truth"]
            category = item["category"]

            logger.info("[%d/%d] 测试: %s...", idx + 1, len(dataset), question[:25])

            t0 = time.time()
            graph_answer = self.engine.query(question)["answer"]
            t_graph = time.time() - t0
            graph_eval = self._evaluate_answer(question, ground_truth, graph_answer)

            t0 = time.time()
            naive_answer = self._generate_naive_rag_response(question)
            t_naive = time.time() - t0
            naive_eval = self._evaluate_answer(question, ground_truth, naive_answer)

            results.append({
                "ID": idx + 1,
                "Category": category,
                "Question": question,
                "GraphRAG Score": graph_eval.get("score", 0),
                "NaiveRAG Score": naive_eval.get("score", 0),
                "GraphRAG Time": t_graph,
                "NaiveRAG Time": t_naive,
            })
            time.sleep(API_COOLDOWN)

        return pd.DataFrame(results)

    # ------------------------------------------------------------ 可视化
    def visualize_dashboard(
        self, df: pd.DataFrame, save_path=None
    ) -> None:
        """生成三合一评估面板：逐题对比 / 分类雷达 / 耗时箱线。"""
        save_path = save_path or (OUTPUT_DIR / "evaluation_dashboard.png")
        try:
            plt.style.use("ggplot")
            fig = plt.figure(figsize=(18, 10))
            fig.suptitle(
                "GraphRAG System Evaluation Report", fontsize=20, fontweight="bold"
            )

            # --- 子图1: 逐题得分对比 ---
            ax1 = fig.add_subplot(2, 2, 1)
            indices = np.arange(len(df))
            width = 0.35
            ax1.bar(indices - width / 2, df["GraphRAG Score"], width,
                    label="GraphRAG", color="#4c72b0")
            ax1.bar(indices + width / 2, df["NaiveRAG Score"], width,
                    label="Naive RAG", color="#dd8452")
            ax1.set_ylabel("Score (0-10)")
            ax1.set_title("Case-by-Case Performance")
            ax1.legend()

            # --- 子图2: 分类能力雷达 ---
            ax2 = fig.add_subplot(2, 2, 2, polar=True)
            categories = df["Category"].unique()
            g_means = df.groupby("Category")["GraphRAG Score"].mean().reindex(
                categories
            ).values
            n_means = df.groupby("Category")["NaiveRAG Score"].mean().reindex(
                categories
            ).values

            angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
            g_vals = np.concatenate((g_means, [g_means[0]]))
            n_vals = np.concatenate((n_means, [n_means[0]]))
            angles += [angles[0]]

            ax2.plot(angles, g_vals, "o-", linewidth=2, label="GraphRAG",
                     color="#4c72b0")
            ax2.fill(angles, g_vals, alpha=0.25, color="#4c72b0")
            ax2.plot(angles, n_vals, "o-", linewidth=2, label="Naive RAG",
                     color="#dd8452")
            ax2.fill(angles, n_vals, alpha=0.1, color="#dd8452")
            ax2.set_xticks(angles[:-1])
            ax2.set_xticklabels(categories, fontsize=12)
            ax2.set_title("Capability Analysis by Difficulty", pad=20)
            ax2.legend(loc="lower right", bbox_to_anchor=(1.3, 0))

            # --- 子图3: 耗时分布 ---
            ax3 = fig.add_subplot(2, 1, 2)
            ax3.boxplot(
                [df["GraphRAG Time"], df["NaiveRAG Time"]],
                tick_labels=["GraphRAG", "Naive RAG"],
                vert=False,
                patch_artist=True,
            )
            ax3.set_xlabel("Inference Latency (seconds)")
            ax3.set_title("System Latency Distribution")

            plt.tight_layout(rect=[0, 0.03, 1, 0.95])
            plt.savefig(save_path, dpi=300)
            plt.close(fig)
            logger.info("📊 评估面板已生成: %s", save_path)

        except Exception as exc:  # noqa: BLE001
            logger.error("绘图失败: %s", exc)


# ===================== 20 道测试集 =====================
# L1 基础事实 (7) / L2 对比分析 (7) / L3 深度原理 (6)
BENCHMARK_DATASET = [
    {
        "category": "L1_Basics",
        "question": "YOLOv7 的主要作者是谁？它提出了什么核心架构？",
        "ground_truth": (
            "YOLOv7 的主要作者是 Chien-Yao Wang 和 Alexey Bochkovskiy。"
            "核心架构提出了 E-ELAN 和基于拼接的模型缩放策略。"
        ),
    },
    {
        "category": "L1_Basics",
        "question": "Swin Transformer 中使用的注意力机制叫什么？",
        "ground_truth": (
            "Swin Transformer 使用了基于移动窗口的自注意力机制"
            " (Shifted Window Attention)，包括 W-MSA 和 SW-MSA。"
        ),
    },
    {
        "category": "L1_Basics",
        "question": "MAE (Masked Autoencoders) 论文中推荐的 Mask 比例是多少？",
        "ground_truth": (
            "MAE 论文推荐的 Mask 比例是 75%，这一高比例迫使模型学习更抽象的图像表征。"
        ),
    },
    {
        "category": "L1_Basics",
        "question": "DETR 是在哪一年发表的？它引入了什么概念到目标检测？",
        "ground_truth": (
            "DETR 发表于 2020 年。它首次将 Transformer 引入目标检测，"
            "并提出了基于集合预测和二分图匹配的端到端检测范式。"
        ),
    },
    {
        "category": "L1_Basics",
        "question": "ViT (Vision Transformer) 将图像切分为多少像素的 Patch？",
        "ground_truth": "ViT 标准实现通常将图像切分为 16x16 的 Patch。",
    },
    {
        "category": "L1_Basics",
        "question": "DeepSeek-V3 属于哪种类型的模型？",
        "ground_truth": "DeepSeek-V3 是一种基于 MoE (Mixture-of-Experts) 架构的大语言模型。",
    },
    {
        "category": "L1_Basics",
        "question": "RepVGG 的核心思想是什么？",
        "ground_truth": (
            "RepVGG 的核心思想是结构重参数化（Structural Re-parameterization）："
            "训练时使用多分支结构，推理时将其融合为单路 VGG 结构，兼顾精度与速度。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "请对比 ViT 和 ResNet 在归纳偏置 (Inductive Bias) 上的区别。",
        "ground_truth": (
            "ResNet (CNN) 具有平移不变性和局部性等强归纳偏置；"
            "而 ViT 基于全局注意力，缺乏这些偏置，需大规模数据预训练。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "SimCLR 和 BYOL 在防止模型塌缩的机制上有什么不同？",
        "ground_truth": (
            "SimCLR 依赖负样本 (Negative Pairs)；"
            "BYOL 依靠非对称架构（预测头）和动量更新的目标网络，不需要负样本。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "YOLOv7 相比于 YOLOv5 在架构上有哪些主要改进？",
        "ground_truth": (
            "YOLOv7 引入了 E-ELAN 结构增强特征学习，使用了重参数化卷积 (RepConv)，"
            "并提出了辅助头 (Auxiliary Head) 训练策略。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "Swin Transformer 和原始 ViT 在处理高分辨率图像时有何不同？",
        "ground_truth": (
            "原始 ViT 复杂度随分辨率呈平方增长；"
            "Swin 通过局部窗口注意力，将复杂度降低为线性增长，适合高分辨率。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "DETR 和 Faster R-CNN 在处理重叠目标时的策略有何不同？",
        "ground_truth": (
            "Faster R-CNN 依赖 NMS 去除重叠框；"
            "DETR 通过匈牙利算法进行一对一匹配，直接预测最终集合，无需 NMS。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "MoCo v1 和 MoCo v2 的主要改进点是什么？",
        "ground_truth": (
            "MoCo v2 吸取 SimCLR 经验，增加了 MLP 投影头 (Projection Head) "
            "和更多数据增强，显著提升性能。"
        ),
    },
    {
        "category": "L2_Comparison",
        "question": "MLP-Mixer 与 CNN 和 Transformer 的主要区别是什么？",
        "ground_truth": (
            "MLP-Mixer 既不用卷积也不用注意力机制，"
            "仅完全依赖多层感知机 (MLP) 在空间和通道维度上混合信息。"
        ),
    },
    {
        "category": "L3_DeepTheory",
        "question": "为什么 BYOL 在没有负样本的情况下不会发生表示塌缩？请解释其核心机制。",
        "ground_truth": (
            "BYOL 通过引入非对称架构防止塌缩。核心机制是 'Stop-gradient'（停止梯度），"
            "使目标网络成为缓慢变化的稳定目标，打破对称性。"
        ),
    },
    {
        "category": "L3_DeepTheory",
        "question": "SimSiam 论文证明了什么对于自监督学习是至关重要的？",
        "ground_truth": (
            "SimSiam 证明了 'Stop-gradient' 是防止塌缩的关键。"
            "即使无动量编码器或负样本，仅靠 Siamese 网络中的停止梯度也能学习有意义表征。"
        ),
    },
    {
        "category": "L3_DeepTheory",
        "question": "分析 Transformer 中的位置编码 (Positional Encoding) 为什么是必要的？",
        "ground_truth": (
            "Self-Attention 本质是置换不变的，无法感知顺序。"
            "位置编码注入位置信息，使模型能区分 Patch 的相对或绝对位置。"
        ),
    },
    {
        "category": "L3_DeepTheory",
        "question": "Focal Loss 是为了解决什么问题提出的？其数学原理是什么？",
        "ground_truth": (
            "Focal Loss 解决正负样本极端不平衡问题。"
            "通过增加调节因子 (1-pt)^gamma，降低简单负样本权重，使模型专注难分类样本。"
        ),
    },
    {
        "category": "L3_DeepTheory",
        "question": "在自监督学习中，BatchNorm 在防止塌缩中起到了什么潜在作用？",
        "ground_truth": (
            "BatchNorm 利用批次统计量归一化，引入了批次内的隐式对比效应，"
            "产生了样本间的相互依赖，起到了类似负样本的作用。"
        ),
    },
    {
        "category": "L3_DeepTheory",
        "question": "阐述 AdamW 相比于 Adam 优化器的主要修正点。",
        "ground_truth": (
            "AdamW 将权重衰减 (Weight Decay) 从梯度更新中解耦，直接作用于权重，"
            "在自适应学习率下能更正确地执行正则化。"
        ),
    },
]


if __name__ == "__main__":
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        engine = GraphRAGQueryEngine()
        evaluator = SystemEvaluator(engine)

        df_results = evaluator.run_benchmark(BENCHMARK_DATASET)

        excel_path = OUTPUT_DIR / "evaluation_report.xlsx"
        df_results.to_excel(excel_path, index=False)
        print(f"✅ 数据已保存: {excel_path}")

        evaluator.visualize_dashboard(df_results)

        print("\n=== 最终成绩单 ===")
        print(df_results.groupby("Category")[["GraphRAG Score", "NaiveRAG Score"]].mean())

    except Exception as exc:  # noqa: BLE001
        logger.error("Critical Error: %s", exc)
