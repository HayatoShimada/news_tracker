import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from langchain_anthropic import ChatAnthropic
from langchain_community.document_loaders import JSONLoader
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

# --- Configuration ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# TODO: Notionから取得した過去データをFAISSに食わせるためのデータ保存先
VECTOR_STORE_PATH = "trend_vectorstore"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# --- Dummy Embeddings ---
# Note: For prototype with text data, using OpenAI embeddings is common, but 
# since we are using Claude, we might need a local embedding model or just use 
# FastEmbed / HuggingFace. For simplicity in this dummy setup, we will use a 
# mock or local embedding if needed.
# Since we only have ANTHROPIC_API_KEY, let's use HuggingFaceEmbeddings as it's free/local.
try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    # Use a small, fast sentence-transformers model
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
except ImportError:
    print("Please install sentence-transformers: pip install sentence-transformers")
    sys.exit(1)


def init_llm():
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY environment variable is missing.")
        sys.exit(1)
    return ChatAnthropic(
        model="claude-3-7-sonnet-20250219",
        temperature=0.7,
        max_tokens=2048
    )

def create_or_load_vectorstore():
    """
    Load vector store if exists, otherwise create a new one with dummy/initial Notion context.
    """
    if os.path.exists(VECTOR_STORE_PATH):
        logger.info(f"Loading existing vector store from {VECTOR_STORE_PATH}")
        return FAISS.load_local(VECTOR_STORE_PATH, embeddings, allow_dangerous_deserialization=True)
    
    logger.info("Creating new vector store with initial context...")
    # 過去の高評価トピックなどのダミーデータ（実際はNotion APIから取得する）
    initial_docs = [
        Document(
            page_content="ユーザーはNext.jsとSupabaseを組み合わせたフルスタック開発に強い関心がある。評価：★5",
            metadata={"source": "notion_past_topics", "rating": 5}
        ),
        Document(
            page_content="Rustを使ったCLIツールの作成による作業効率化のアイデア。評価：★4",
            metadata={"source": "notion_past_topics", "rating": 4}
        ),
        Document(
            page_content="LangChainとローカルLLMを用いたRAG(Retrieval-Augmented Generation)の構築。評価：★5",
            metadata={"source": "notion_past_topics", "rating": 5}
        ),
        Document(
            page_content="デザインシステム構築に関する一般的な記事。評価：★2",
            metadata={"source": "notion_past_topics", "rating": 2} # あまり関心がない例
        )
    ]
    
    vectorstore = FAISS.from_documents(initial_docs, embeddings)
    vectorstore.save_local(VECTOR_STORE_PATH)
    return vectorstore

def analyze_trend(query: str, vectorstore: FAISS):
    """
    RAG pipeline: Retrive context -> Generate analysis
    """
    llm = init_llm()
    retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

    template = """あなたは優秀なリサーチアシスタントです。
以下の過去のユーザーの関心事（コンテキスト）を踏まえて、入力された新しいトレンドニュースを分析し、
ユーザーにとってなぜ重要なのか、どうアクションすべきかを提案してください。

コンテキスト（過去の高評価トピックなど）:
{context}

新しいトレンドニュース（入力）:
{question}

回答のフォーマット:
1. ニュースの要約 (3行程度)
2. 過去の関心との関連性 (コンテキストを踏まえて)
3. 次のアクション提案 (1-2個)
"""
    prompt = ChatPromptTemplate.from_template(template)

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    # RAG Chain
    rag_chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    logger.info("Generating analysis using RAG...")
    result = rag_chain.invoke(query)
    return result

def main():
    parser = argparse.ArgumentParser(description="Analyze a trend using RAG (LangChain & Claude)")
    parser.add_argument("--trend", type=str, required=True, help="Trend text or JSON data from n8n")
    args = parser.parse_args()

    # n8nからJSON文字列が渡された場合を考慮してパースを試みる
    try:
        data = json.loads(args.trend)
        # JSONの場合は "title" や "description" などのフィールドを想定
        query = f"タイトル: {data.get('title', '')}\n内容: {data.get('description', '')}"
    except json.JSONDecodeError:
        query = args.trend

    logger.info(f"Input Trend: {query}")

    vectorstore = create_or_load_vectorstore()
    analysis_result = analyze_trend(query, vectorstore)

    print("\n" + "="*50)
    print("=== 分析結果 (Analysis Result) ===")
    print("="*50)
    print(analysis_result)

    # ここで実際はNotion APIを叩いて結果を書き込む（daily_digest.py の関数を再利用できる）
    # 今回はプロトタイプのため標準出力のみ

if __name__ == "__main__":
    main()
