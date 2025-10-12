# front/main.py
import os
import requests
import streamlit as st

st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

# ---------------------------
# 환경 설정
# ---------------------------
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"

# 기본 파라미터
DEFAULT_TEMP = 0.3
DEFAULT_MAXTOK = 512

# 보험사 옵션 (필요 시 추가)
INSURERS = ["DB손해", "현대해상", "삼성화재"]

# ---------------------------
# 유틸
# ---------------------------
def post_json(url: str, payload: dict, timeout=(10, 120)):
    """공통 POST 호출 (예외 문구를 화면에 보여줌)."""
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        return None, str(e)

def init_state():
    if "history" not in st.session_state:
        st.session_state.history = []  # [(role, text)]
init_state()

# ---------------------------
# 헤더
# ---------------------------
st.title("보험 문서 RAG 플랫폼")
st.caption(f"API_BASE = {API_BASE}")

# ---------------------------
# 입력 영역
# ---------------------------
with st.container():
    st.subheader("대화형 Q&A (RAG + PDF)")
    col1, col2, col3 = st.columns([6, 3, 2])

    with col1:
        user_msg = st.text_input("메시지 입력", value="", placeholder="예) 실손 청구에 필요한 서류가 뭐야?")
    with col2:
        insurer = st.selectbox("보험사(선택)", INSURERS, index=0)
    with col3:
        topk = st.slider("Top-K", 1, 10, 3)

    c1, c2 = st.columns([1, 1])

    # ---------------------------
    # 버튼 1: 일반 대화 (/chat/completion)
    # ---------------------------
    with c1:
        if st.button("보내기", use_container_width=True):
            msg = (user_msg or "").strip()
            if not msg:
                st.warning("메시지를 입력하세요.")
            else:
                payload = {
                    "messages": [{"role": "user", "content": msg}],  # ChatRequest 스키마에 맞춤
                    "insurer": insurer,
                    "top_k": int(topk),
                    "temperature": DEFAULT_TEMP,
                    "max_tokens": DEFAULT_MAXTOK,
                }
                data, err = post_json(f"{API_BASE}/chat/completion", payload)
                if err:
                    st.error(f"요청 실패: {err}")
                else:
                    reply = data.get("reply", "")
                    if not reply:
                        reply = "⚠️ 문서에서 관련 근거를 찾지 못했습니다. 보험사 선택/Top-K/인덱스를 확인해주세요."
                    st.session_state.history.append(("user", msg))
                    st.session_state.history.append(("assistant", reply))

    # ---------------------------
    # 버튼 2: RAG 근거 기반 답변 (/qa/ask)
    # ---------------------------
    with c2:
        if st.button("근거 기반 답변 PDF 받기", use_container_width=True):
            msg = (user_msg or "").strip()
            if not msg:
                st.warning("메시지를 입력하세요.")
            else:
                # 백엔드 스키마가 message 또는 query를 요구할 수 있어 둘 다 전송 (422 예방)
                payload = {
                    "message": msg,
                    "query": msg,
                    "insurer": insurer,
                    "top_k": int(topk),
                    "temperature": DEFAULT_TEMP,
                    "max_tokens": DEFAULT_MAXTOK,
                }
                data, err = post_json(f"{API_BASE}/qa/ask", payload)
                if err:
                    st.error(f"요청 실패: {err}")
                else:
                    answer = data.get("answer") or data.get("reply") or ""
                    pdf_url = data.get("pdf_url") or data.get("file_path")
                    if answer:
                        st.session_state.history.append(("user", msg))
                        st.session_state.history.append(("assistant", answer))
                    if pdf_url:
                        # 백엔드가 /files/... 형태로 주면 앞에 API_BASE 붙여 링크
                        if pdf_url.startswith("/"):
                            st.markdown(f"[📄 PDF 다운로드]({API_BASE}{pdf_url})")
                        else:
                            st.markdown(f"[📄 PDF 다운로드]({pdf_url})")

# ---------------------------
# 최근 대화
# ---------------------------
st.subheader("최근 대화")
if not st.session_state.history:
    st.caption("대화가 없습니다.")
else:
    for role, text in st.session_state.history[-20:]:
        if role == "user":
            st.markdown(f"🧑‍💻 **{text}**")
        else:
            st.markdown(f"🤖 {text}")
