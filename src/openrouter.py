"""vision.py / recipe.py가 함께 쓰는 오픈라우터 공용 코드."""
import requests
import streamlit as st

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"


def extract_content(body):
    """채팅 응답 본문에서 첫 choice의 message.content 문자열을 꺼낸다.

    choices가 비었거나 message/content가 없거나 content가 null(빈 답)·문자열이 아니면
    None을 돌려준다. 모델이 content를 비워 보내도 TypeError/KeyError로 멈추지 않게 한다.
    """
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) else None


def _trim_model_entry(m):
    """화면/필터에서 실제로 쓰는 필드만 남긴다."""
    architecture = m.get("architecture") or {}
    return {
        "id": m.get("id", ""),
        "name": m.get("name"),
        "context_length": m.get("context_length"),
        "created": m.get("created"),
        "architecture": {"input_modalities": architecture.get("input_modalities", [])},
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_free_models_payload():
    """오픈라우터 무료(:free) 모델 목록을 5분간 캐시한다. 비전/레시피가 이 캐시 하나를 공유한다.

    전체 목록(약 470개, 응답 약 850KB)을 그대로 캐시하면 st.cache_data가 호출마다
    역직렬화하는 비용이 크므로, :free 모델만 필요한 필드로 줄여서 캐시한다.
    실패하면 예외를 그대로 올려서 실패 결과가 캐시에 남지 않게 한다
    (일시적인 네트워크 오류가 5분 동안 굳어지지 않도록).
    """
    response = requests.get(MODELS_URL, timeout=10)
    response.raise_for_status()
    data = response.json().get("data", [])
    return [_trim_model_entry(m) for m in data if m.get("id", "").endswith(":free")]


def is_daily_limit_response(response):
    """429 응답이 계정 일일 한도 소진인지 판별한다 (app.rate_limit_message와 같은 기준).

    일일 한도는 초기화 전까지 어떤 무료 모델로 바꿔도 같은 429가 나므로 재시도할 의미가 없다.
    """
    if response.status_code != 429:
        return False
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        return False
    if not isinstance(error, dict):
        return False
    metadata = error.get("metadata") or {}
    return (
        "free-models-per-day" in str(error.get("message") or "")
        or metadata.get("limit_source") == "openrouter_free_tier_daily"
    )


def should_wait_before_next(response, model, next_model):
    """다음 시도 전에 대기가 필요한지 판단한다.

    대기는 혼잡(429)이 풀리기를 기다리기 위한 것이다. 같은 모델을 다시 부르거나 429를
    받은 경우에만 기다리고, 다른 모델로 넘어가는 파싱 실패/서버 오류 등에서는 바로 넘어간다.
    """
    return response.status_code == 429 or next_model == model
