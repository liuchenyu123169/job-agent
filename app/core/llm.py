from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatZhipuAI

from app.core.config import MODEL_NAME, ZHIPU_BASE_URL, get_api_key


def invoke_llm(prompt: str) -> str:
    llm = ChatZhipuAI(
        api_key=get_api_key(),
        base_url=ZHIPU_BASE_URL,
        model=MODEL_NAME,
        temperature=0.7,
    )
    response = llm.invoke(prompt)
    return str(response.content)
