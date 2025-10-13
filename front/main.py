# front/main.py
import os
import requests
import streamlit as st

# ---------------------------
# 페이지/환경설정
# ---------------------------
st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"

INSURERS = ["DB손해", "현대해상", "삼성화재"]
DEFAULT_TEMP = 0.3
DEFAULT_MAXTOK = 512

# ---------------------------
# 유틸
# ---------------------------
def post_json(url: str, payload: dict, timeout=(20, 180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r, None
    except requests.RequestException as e:
        return None, str(e)

def ensure_state():
    if "messages" not in st.session_state:
        # [{"role":"user"/"assistant","content": "...", "meta":{...}}]
        st.session_state.messages = []
    if "insurer" not in st.session_state:
        st.session_state.insurer = INSURERS[0]
    if "top_k" not in st.session_state:
        st.session_state.top_k = 3
    if "temperature" not in st.session_state:
        st.session_state.temperature = DEFAULT_TEMP
    if "max_tokens" not in st.session_state:
        st.session_state.max_tokens = DEFAULT_MAXTOK

ensure_state()

# ---------------------------
# 사이드바 (설정)
# ---------------------------
with st.sidebar:
    st.subheader("⚙️ 설정")
    st.caption(f"API_BASE: {API_BASE}")
    st.session_state.insurer = st.selectbox("보험사", INSURERS, index=INSURERS.index(st.session_state.insurer))
    st.session_state.top_k = st.slider("Top-K (근거 개수)", 1, 10, st.session_state.top_k)
    st.session_state.temperature = st.slider("온도(창의성)", 0.0, 1.0, st.session_state.temperature, 0.05)
    st.session_state.max_tokens = st.slider("최대 토큰", 128, 2048, st.session_state.max_tokens, 64)
    st.markdown("---")
    st.caption("• Enter로 전송 · Shift+Enter 줄바꿈\n• 메시지 클릭 없이 바로 PDF 생성도 가능")

# ---------------------------
# 헤더
# ---------------------------
st.title("보험 문서 RAG 플랫폼")
st.divider()

# ---------------------------
# 채팅 영역 (과거 대화 표시)
# ---------------------------
for msg in st.session_state.messages:
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(msg["content"])
        meta = msg.get("meta") or {}

        # 근거/소스 표시 (있을 때만)
        sources = meta.get("sources") or []
        if sources:
            with st.expander("🔎 근거 문서/소스 보기", expanded=False):
                for i, h in enumerate(sources, 1):
                    title = h.get("clause_title") or h.get("doc_id") or f"source {i}"
                    score = h.get("score")
                    snippet = (h.get("content") or "").strip()
                    if len(snippet) > 320:
                        snippet = snippet[:320] + "…"
                    st.markdown(f"**{i}. {title}**  (score: {score})\n\n> {snippet}")

        # PDF 링크/버튼
        pdf = meta.get("pdf")
        if isinstance(pdf, dict):
            pdf_url = pdf.get("url")
            pdf_bytes = pdf.get("bytes")
            if pdf_url:
                href = pdf_url if not pdf_url.startswith("/") else f"{API_BASE}{pdf_url}"
                st.link_button("📄 PDF 열기", href)
            elif pdf_bytes:
                st.download_button("📄 PDF 다운로드", data=pdf_bytes, file_name="rag_answer.pdf", mime="application/pdf")

# ---------------------------
# 전송 함수들
# ---------------------------
def send_normal_chat(user_text: str):
    """백엔드 /chat/completion 호출"""
    st.session_state.messages.append({"role": "user", "content": user_text})

    payload = {
        "messages": [{"role": "user", "content": user_text}],
        "insurer": st.session_state.insurer,
        "top_k": int(st.session_state.top_k),
        "temperature": float(st.session_state.temperature),
        "max_tokens": int(st.session_state.max_tokens),
    }
    r, err = post_json(f"{API_BASE}/chat/completion", payload)
    if err:
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"❌ 요청 실패: {err}"
        })
        return

    data = r.json()
    reply = data.get("reply") or "⚠️ 빈 응답입니다."
    st.session_state.messages.append({"role": "assistant", "content": reply})

def send_answer_pdf(user_text: str):
    """
    백엔드 /qa/answer_pdf 호출
    - 서버가 application/pdf로 주면: 다운로드 버튼
    - JSON으로 {pdf_url, answer, sources} 주면: 링크 + 요약 + 소스
    """
    st.session_state.messages.append({"role": "user", "content": f"(PDF 요청) {user_text}"})

    payload = {
        "question": user_text,
        "policy_type": st.session_state.insurer,
        "top_k": int(st.session_state.top_k),
        "max_tokens": int(st.session_state.max_tokens),
    }
    try:
        r = requests.post(f"{API_BASE}/qa/answer_pdf", json=payload, timeout=(20, 180))
        r.raise_for_status()
    except requests.RequestException as e:
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"❌ PDF 생성 실패: {e}"
        })
        return

    ctype = r.headers.get("content-type", "").lower()
    if ctype.startswith("application/pdf"):
        # 바이트 직접 반환
        st.session_state.messages.append({
            "role": "assistant",
            "content": "PDF가 생성되었습니다. 아래 버튼으로 내려받으세요.",
            "meta": {"pdf": {"bytes": r.content}}
        })
    else:
        # JSON(pdf_url) + answer + sources
        data = r.json()
        answer = data.get("answer") or "요약이 제공되지 않았습니다."
        sources = data.get("sources") or []
        pdf_url = data.get("pdf_url")
        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "meta": {
                "sources": sources,
                "pdf": {"url": pdf_url} if pdf_url else None
            }
        })

# ---------------------------
# 입력창 (고정)
# ---------------------------
user_input = st.chat_input("질문을 입력하고 Enter를 누르세요…")
if user_input:
    # 기본은 일반 채팅으로 보냄
    send_normal_chat(user_input)

# 하단 툴바(버튼): 같은 입력으로 PDF 생성도 가능하게
cols = st.columns([1, 1, 6])
with cols[0]:
    if st.button("근거 기반 PDF 생성", use_container_width=True):
        st.session_state.messages.append({"role": "assistant", "content": "🛠️ PDF 생성 중…"})
        # 직전에 입력한 user 메시지 사용. 없으면 입력창 안내
        last_user = None
        for m in reversed(st.session_state.messages):
            if m["role"] == "user" and not m["content"].startswith("(PDF 요청)"):
                last_user = m["content"]
                break
        if not last_user:
            st.warning("먼저 질문을 입력해주세요.")
        else:
            send_answer_pdf(last_user)

with cols[1]:
    if st.button("대화 지우기", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
