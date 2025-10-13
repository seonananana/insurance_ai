# front/main.py
import os
import time
import requests
import streamlit as st

st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

# ---------------------------
# 환경
# ---------------------------
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["DB손해", "현대해상", "삼성화재"]
DEFAULT_TEMP = 0.3
DEFAULT_MAXTOK = 512

# ---------------------------
# 상태
# ---------------------------
def ensure_state():
    ss = st.session_state
    ss.setdefault("messages", [])           # [{"role":..., "content":..., "meta":{...}}]
    ss.setdefault("insurer", None)          # 처음엔 None -> 선택 유도
    ss.setdefault("top_k", 3)
    ss.setdefault("temperature", DEFAULT_TEMP)
    ss.setdefault("max_tokens", DEFAULT_MAXTOK)
    ss.setdefault("insurer_selected", False)
    # 오버레이 타이머: 보험사 선택을 아직 안 눌렀다면 10초 노출
    if not ss["insurer_selected"]:
        ss.setdefault("overlay_until", time.time() + 10)
    else:
        ss["overlay_until"] = 0
ensure_state()

# ---------------------------
# 공통 HTTP
# ---------------------------
def post_json(url: str, payload: dict, timeout=(20, 180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r, None
    except requests.RequestException as e:
        return None, str(e)

# ---------------------------
# 사이드바 (설정 + 액션)
# ---------------------------
def on_change_insurer():
    st.session_state.insurer_selected = True
    st.session_state.overlay_until = 0

with st.sidebar:
    st.subheader("⚙️ 설정")

    # 1) 보험사 (사용자가 클릭해야 선택됨)
    st.session_state.insurer = st.selectbox(
        "보험사",
        ["선택하세요…"] + INSURERS if st.session_state.insurer is None else INSURERS,
        index=0 if st.session_state.insurer is None else INSURERS.index(st.session_state.insurer),
        on_change=on_change_insurer,
        help="검색에 사용할 문서를 어느 보험사 것으로 제한할지 선택합니다.",
    )

    # 2) 검색/생성 파라미터
    st.session_state.top_k = st.slider(
        "Top-K (근거 개수)",
        1, 10, st.session_state.top_k,
        help="질문과 가장 유사한 문서 조각을 몇 개까지 불러올지입니다. 높을수록 더 많은 근거를 보지만 느려질 수 있습니다."
    )
    st.session_state.temperature = st.slider(
        "온도(창의성)",
        0.0, 1.0, st.session_state.temperature, 0.05,
        help="답변의 무작위성을 조절합니다. 0에 가까울수록 사실 위주의 안정적인 답변, 1에 가까울수록 표현이 다양해집니다."
    )
    st.session_state.max_tokens = st.slider(
        "최대 토큰",
        128, 2048, st.session_state.max_tokens, 64,
        help="한 번에 생성할 수 있는 최대 길이입니다. 너무 크면 비용·지연이 늘 수 있습니다."
    )

    # 3) 액션 버튼 (사이드바로 이동)
    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        make_pdf_clicked = st.button("📄 근거 기반 PDF 생성", use_container_width=True)
    with col_b:
        clear_clicked = st.button("🗑️ 대화 지우기", use_container_width=True)

    # 4) 도움말
    with st.expander("ℹ️ 이 옵션은 뭐죠?"):
        st.markdown(
            "- **보험사**: 해당 보험사의 약관/안내문만 우선 검색합니다.\n"
            "- **Top-K**: 검색 근거(문서 조각) 개수입니다. 3~5 권장.\n"
            "- **온도(창의성)**: 0.2~0.4는 문서 QA에 적당합니다.\n"
            "- **최대 토큰**: 답변 길이 상한입니다. 길수록 느릴 수 있어요."
        )

    # 5) API_BASE 표시는 가장 아래로
    st.markdown("---")
    st.caption(f"API_BASE: {API_BASE}")

# ---------------------------
# 헤더
# ---------------------------
st.title("보험 문서 RAG 플랫폼")
st.divider()

# ---------------------------
# 오버레이: 보험사 선택 유도 (투명 배경 + 중앙 안내, 10초 후 자동 사라짐)
# ---------------------------
def render_overlay():
    st.markdown(
        """
        <style>
        .overlay {
            position: fixed; inset: 0; background: rgba(0,0,0,0.25);
            display: flex; align-items: center; justify-content: center; z-index: 9999;
        }
        .overlay-card {
            background: white; padding: 24px 28px; border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2); font-size: 18px; text-align: center;
        }
        </style>
        <div class="overlay">
            <div class="overlay-card">
                <b>보험사를 선택해 주세요.</b><br/>
                왼쪽 사이드바에서 보험사를 고르면 시작할 수 있어요.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

if (not st.session_state.insurer_selected) and (time.time() < st.session_state.get("overlay_until", 0)):
    render_overlay()

# ---------------------------
# 채팅 메시지 렌더
# ---------------------------
for msg in st.session_state.messages:
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(msg["content"])
        meta = msg.get("meta") or {}
        # 근거
        sources = meta.get("sources") or []
        if sources:
            with st.expander("🔎 근거 문서/소스", expanded=False):
                for i, h in enumerate(sources, 1):
                    title = h.get("clause_title") or h.get("doc_id") or f"source {i}"
                    score = h.get("score")
                    snippet = (h.get("content") or "").strip()
                    if len(snippet) > 320: snippet = snippet[:320] + "…"
                    st.markdown(f"**{i}. {title}** (score: {score})\n\n> {snippet}")
        # PDF
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
# 호출 함수
# ---------------------------
def send_normal_chat(user_text: str):
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
        st.session_state.messages.append({"role": "assistant", "content": f"❌ 요청 실패: {err}"})
        return
    reply = r.json().get("reply") or "⚠️ 빈 응답입니다."
    st.session_state.messages.append({"role": "assistant", "content": reply})

def send_answer_pdf(user_text: str):
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
        st.session_state.messages.append({"role": "assistant", "content": f"❌ PDF 생성 실패: {e}"})
        return

    ctype = r.headers.get("content-type", "").lower()
    if ctype.startswith("application/pdf"):
        st.session_state.messages.append({
            "role": "assistant",
            "content": "PDF가 생성되었습니다. 아래 버튼으로 내려받으세요.",
            "meta": {"pdf": {"bytes": r.content}}
        })
    else:
        data = r.json()
        answer = data.get("answer") or "요약이 제공되지 않았습니다."
        sources = data.get("sources") or []
        pdf_url = data.get("pdf_url")
        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "meta": {"sources": sources, "pdf": {"url": pdf_url} if pdf_url else None}
        })

# ---------------------------
# 입력창 & 사이드바 액션 처리
# ---------------------------
user_input = st.chat_input("질문을 입력하고 Enter를 누르세요…", disabled=not st.session_state.insurer_selected)
if user_input:
    if not st.session_state.insurer_selected:
        st.warning("먼저 보험사를 선택해 주세요.")
    else:
        send_normal_chat(user_input)

# 사이드바 버튼 처리
if 'make_pdf_clicked' in locals() and make_pdf_clicked:
    # 최근 사용자 질문 찾기
    last_user = None
    for m in reversed(st.session_state.messages):
        if m["role"] == "user" and not m["content"].startswith("(PDF 요청)"):
            last_user = m["content"]
            break
    if not last_user:
        st.warning("먼저 질문을 입력해 주세요.")
    else:
        send_answer_pdf(last_user)

if 'clear_clicked' in locals() and clear_clicked:
    st.session_state.messages = []
    st.rerun()
