# front/main.py
import os
import requests
import streamlit as st

st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

# ---------------------------
# 환경 설정
# ---------------------------
API_BASE = os.getenv("API_BASE") or "http://127.0.0.1:8000"

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
# 버튼 2: RAG 근거 기반 답변 PDF 받기 (/qa/answer_pdf)
# ---------------------------
with c2:
    if st.button("근거 기반 답변 PDF 받기", use_container_width=True):
        msg = (user_msg or "").strip()
        if not msg:
            st.warning("메시지를 입력하세요.")
        else:
            payload = {
                "q": msg,
                "insurer": insurer,
                "top_k": int(topk),
            }

            # 1) 정식 경로
            url = f"{API_BASE}/qa/answer_pdf"

            try:
                r = requests.post(url, json=payload, timeout=(20, 180))
                if r.status_code != 200:
                    # 혹시 다른 라우팅일 때(옵션): /report/answer_pdf로 한 번 더 시도
                    if r.status_code == 404:
                        url_fallback = f"{API_BASE}/report/answer_pdf"
                        r = requests.post(url_fallback, json=payload, timeout=(20, 180))

                if r.status_code != 200:
                    st.error(f"요청 실패({r.status_code}): {r.text}")
                else:
                    ctype = r.headers.get("content-type", "").lower()
                    if ctype.startswith("application/pdf"):
                        fname = f"rag_answer_{insurer}_top{int(topk)}.pdf"
                        st.success("PDF 생성 완료. 아래 버튼으로 다운로드하세요.")
                        st.download_button(
                            "PDF 다운로드", data=r.content, file_name=fname, mime="application/pdf"
                        )
                    else:
                        # 서버가 PDF가 아닌 JSON/텍스트를 보냈을 때 디버깅용 출력
                        preview = r.text
                        if len(preview) > 800:
                            preview = preview[:800] + " …"
                        st.error("서버가 PDF가 아닌 응답을 보냈습니다.")
                        st.code(preview)
            except requests.RequestException as e:
                st.error(f"요청 실패: {e}")

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
