"""集中配置模块。

所有环境变量、路径与模型名称统一在此处读取，业务代码不再出现
任何明文凭据或绝对路径。

用法::

    from config import CHROMA_DIR, get_neo4j_graph, get_llm
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- 路径
PROJECT_ROOT = Path(__file__).resolve().parent

# 优先读取项目根目录的 .env；不存在时静默跳过，交由调用方报错。
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()

DATA_DIR = PROJECT_ROOT / "data"
PAPERS_DIR = DATA_DIR / "papers"          # 原始论文 PDF 存放处
CHROMA_DIR = DATA_DIR / "chroma_db"       # 向量库持久化目录
OUTPUT_DIR = PROJECT_ROOT / "outputs"     # 评估报告等产物

# ---------------------------------------------------------------- 凭据
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# ---------------------------------------------------------------- 模型
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "moka-ai/m3e-base")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")

# ---------------------------------------------------------------- 检索参数
RECALL_TOP_K = int(os.getenv("RECALL_TOP_K", "15"))   # 向量粗召回条数
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "5"))    # 重排后保留条数
GRAPH_RELATION_LIMIT = int(os.getenv("GRAPH_RELATION_LIMIT", "5"))


class ConfigError(RuntimeError):
    """缺少必需配置时抛出，附带可操作的修复提示。"""


def require_api_key() -> str:
    """返回 DeepSeek API Key，缺失时给出明确指引。"""
    if not DEEPSEEK_API_KEY:
        raise ConfigError(
            "未找到 DEEPSEEK_API_KEY。\n"
            f"请复制 .env.example 为 .env 并填入密钥：{ENV_FILE}"
        )
    return DEEPSEEK_API_KEY


def get_neo4j_graph():
    """建立并返回 Neo4j 连接。凭据一律来自环境变量。"""
    from py2neo import Graph

    if not NEO4J_PASSWORD:
        raise ConfigError(
            "未找到 NEO4J_PASSWORD。\n"
            f"请复制 .env.example 为 .env 并填入图数据库密码：{ENV_FILE}"
        )
    return Graph(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def get_llm(temperature: float = 0.0):
    """构造指向 DeepSeek 的 ChatOpenAI 实例。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=LLM_MODEL,
        openai_api_key=require_api_key(),
        openai_api_base=LLM_BASE_URL,
        temperature=temperature,
    )


def ensure_dirs() -> None:
    """确保运行期需要的目录存在。"""
    for path in (DATA_DIR, PAPERS_DIR, CHROMA_DIR, OUTPUT_DIR):
        path.mkdir(parents=True, exist_ok=True)
