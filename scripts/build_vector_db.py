"""构建向量库。

读取 data/papers/ 下的全部 PDF，切分、向量化后持久化到 data/chroma_db/。

    python scripts/build_vector_db.py

注意：此处使用的嵌入模型必须与 config.EMBEDDING_MODEL 一致，
否则查询阶段会因向量空间不匹配而检索到无关内容。
"""

import glob
import os
import shutil
import sys
import warnings
from pathlib import Path

# 允许以脚本方式直接运行（把项目根目录加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_community.document_loaders import PyPDFLoader  # noqa: E402
from langchain_community.embeddings import HuggingFaceEmbeddings  # noqa: E402
from langchain_community.vectorstores import Chroma  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from config import CHROMA_DIR, EMBEDDING_MODEL, PAPERS_DIR  # noqa: E402

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
BATCH_SIZE = 166  # 分批写入，避免上百篇论文撑爆内存


def build_vector_db() -> None:
    print(" [GraphRAG] 向量库构建程序启动")
    print(f" 读取数据源: {PAPERS_DIR}")
    print(f" 目标存储地: {CHROMA_DIR}")
    print(f" 使用模型:   {EMBEDDING_MODEL}")

    pdf_files = glob.glob(os.path.join(str(PAPERS_DIR), "*.pdf"))
    if not pdf_files:
        print(f" 错误: {PAPERS_DIR} 下没有找到 PDF 文件，请先放入论文。")
        return
    print(f" 扫描到 {len(pdf_files)} 篇论文，准备开始处理...")

    # 清理旧库，保证向量空间纯净
    if CHROMA_DIR.exists():
        print(" 检测到旧向量库，正在清理...")
        shutil.rmtree(CHROMA_DIR)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    all_chunks = []
    print(" 正在解析 PDF...")
    for index, pdf_path in enumerate(pdf_files):
        try:
            documents = PyPDFLoader(pdf_path).load()
            for doc in documents:
                doc.metadata["source"] = os.path.basename(pdf_path)  # 溯源标记
            all_chunks.extend(splitter.split_documents(documents))

            if (index + 1) % 10 == 0:
                print(f"   ...已处理 {index + 1}/{len(pdf_files)} 篇")
        except Exception as exc:  # noqa: BLE001
            print(f"    解析失败: {os.path.basename(pdf_path)} | 原因: {exc}")

    print(f"\n 解析完成，共生成 {len(all_chunks)} 个文本块。")
    print(" 正在向量化（首次运行需下载模型，请耐心等待）...")

    try:
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        vector_db = None

        for i in range(0, len(all_chunks), BATCH_SIZE):
            batch = all_chunks[i : i + BATCH_SIZE]
            if not batch:
                continue

            if vector_db is None:
                vector_db = Chroma.from_documents(
                    documents=batch,
                    embedding=embeddings,
                    persist_directory=str(CHROMA_DIR),
                )
            else:
                vector_db.add_documents(documents=batch)

            print(f"   -> 写入进度: {i + len(batch)}/{len(all_chunks)}")

        print("=" * 50)
        print(" 向量库构建完成！")
        print(f" 路径: {CHROMA_DIR}")

    except Exception as exc:  # noqa: BLE001
        print(f"\n 向量化阶段出错: {exc}")
        print(" 提示: 若为网络错误，请检查代理设置，或改用较小的嵌入模型。")


if __name__ == "__main__":
    build_vector_db()
