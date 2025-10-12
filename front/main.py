# front/main.py
# 단일 화면: 대화형 Q&A(RAG) + PDF 생성
# - 상단: 입력/보험사/TopK/버튼
# - 중단: 상태/링크
# - 하단: 최근 대화
# 백엔드 의존 엔드포인트:
#   POST /chat/complete   (질문 → RAG + OpenAI 답변)
#   POST /qa/answer_pdf   (최근 질문/근거로 PDF 생성)
#   POST /chat/log        (선택, 없으면 자동 무시)

import os
import uuid
import requests
import streamlit as st

# ----------------------------
# 기본 설정
# ----------------------------
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE", "http://localhost:8000")
st.set_page_config(page_title="보험 문서 RAG", layout="wide")

# 세션 상태
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
if "chat" not in st.session_state:
    st.session_state.chat = []

# ----------------------------
# 헤더
# ----------------------------
st.markdown(
    """
    <div style="display:flex;align-items:end;gap:14px;margin-bottom:6px">
      <h1 style="margin:0">보험 문서 RAG 플랫폼</h1>
      <span style="color:#666;font-size:14px">대화 + 검색 + PDF 한 번에</span>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(f"API_BASE = {API_BASE}")

# ----------------------------
# 입력 영역
# ----------------------------
with st.container(border=True):
    st.subheader("대화형 Q&A (RAG + PDF)", divider="gray")

    c1, c2, c3 = st.columns([4, 2, 1])
    with c1:
        user_text = st.text_input("메시지 입력", placeholder="예) 실손 청구에 필요한 서류는?")
    with c2:
        insurers = ["", "DB손해", "현대해상", "삼성화재"]
        policy = st.selectbox("보험사(선택)", insurers, index=0)
    with c3:
        topk = st.slider("Top-K", 1, 10, 3)

    b1, b2 = st.columns([1, 1])
    with b1:
        send = st.button("보내기", use_container_width=True, disabled=not user_text)
    with b2:
        make_pdf = st.button("근거 기반 답변 PDF 받기", use_container_width=True)

# ----------------------------
# 보내기: /chat/complete
# ----------------------------
def post_json(url: str, payload: dict, timeout=(10, 90)):
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

if send:
    try:
        st.session_state.chat.append({"role": "user", "content": user_text})

        payload = {
            "question": user_text,
            "policy_type": policy or None,
            "top_k": int(topk),
            "session_id": st.session_state.session_id,
        }
        data = post_json(f"{API_BASE}/chat/complete", payload)
        answer = data.get("answer", "").strip()
        if not answer:
            answer = "(빈 응답)"
        st.session_state.chat.append({"role": "assistant", "content": answer})

        # (선택) 대화 로그 저장: 백엔드에 없으면 조용히 무시
        try:
            log = {
                "session_id": st.session_state.session_id,
                "items": [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": answer},
                ],
            }
            requests.post(f"{API_BASE}/chat/log", json=log, timeout=3)
        except Exception:
            pass

    except requests.HTTPError as e:
        st.error(f"요청 실패: {e} | {getattr(e.response, 'text', '')[:300]}")
    except Exception as e:
        st.error(f"요청 실패: {e}")

# ----------------------------
# PDF 생성: /qa/answer_pdf
# ----------------------------
if make_pdf:
    try:
        last_q = ""
        # 최근 user 메시지를 PDF 질문으로 사용
        for m in reversed(st.session_state.chat):
            if m["role"] == "user":
                last_q = m["content"]
                break

        if not last_q:
            st.warning("먼저 질문을 입력하고 '보내기'를 눌러주세요.")
        else:
            payload = {
                "question": last_q,
                "policy_type": policy or None,
                "top_k": int(topk),
                "session_id": st.session_state.session_id,
            }
            data = post_json(f"{API_BASE}/qa/answer_pdf", payload, timeout=(10, 120))
            st.success("PDF가 생성되었습니다.")
            if url := data.get("pdf_url"):
                st.markdown(f"[PDF 열기]({url})")
            else:
                st.info("pdf_url이 응답에 없습니다. 백엔드 응답을 확인하세요.")
    except requests.HTTPError as e:
        st.error(f"PDF 생성 실패: {e} | {getattr(e.response, 'text', '')[:300]}")
    except Exception as e:
        st.error(f"PDF 생성 실패: {e}")

# ----------------------------
# 최근 대화
# ----------------------------
st.markdown("### 최근 대화")
if not st.session_state.chat:
    st.write("아직 대화가 없습니다.")
else:
    for m in st.session_state.chat[-50:]:
        prefix = "🧑 " if m["role"] == "user" else "🤖 "
        st.markdown(f"{prefix}{m['content']}")
