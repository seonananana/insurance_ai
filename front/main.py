import requests
import streamlit as st
import time

# ===== 페이지 & 테마 =====
st.set_page_config(page_title="RAG Chat", page_icon="✨", layout="wide")

# 기본 테마와 어울리는 CSS
CSS = """
/* 메뉴/푸터 정리 */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* 전체 여백 */
.block-container {padding-top: 1.5rem; padding-bottom: 2rem;}

/* 히어로 섹션 */
.hero {
  background: linear-gradient(135deg, #f6f5ff 0%, #ffffff 60%);
  border: 1px solid #efeaff;
  padding: 20px 22px;
  border-radius: 20px;
  margin-bottom: 18px;
}

/* 카드 */
.card {
  padding: 1rem 1.1rem;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #f1efff;
  box-shadow: 0 6px 18px rgba(124,58,237,0.08);
  margin-bottom: 10px;
}

/* 채팅 말풍선 */
.chat-bubble {
  padding: .8rem 1rem;
  border-radius: 14px;
  margin: .25rem 0 .5rem 0;
  border: 1px solid #ede9fe;
}
.user {
  background: #eef2ff;
}
.assistant {
  background: #ffffff;
}

/* 작은 보조 텍스트 */
.subtle {
  color:#6b7280; font-size:.9rem;
}

/* Evidence 배지/링크 */
.badge {
  display:inline-block; padding:.1rem .5rem; border-radius:999px;
  border:1px solid #e9e5ff; font-size:.78rem; margin-left:.4rem;
  color:#6b21a8; background:#faf5ff;
}
a.evi {
  text-decoration:none;
  border-bottom:1px dashed #c4b5fd;
}
"""

st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

# ===== 기본 상수/상태 =====
DEFAULT_API_BASE = "http://localhost:8000"
DEFAULT_SESSION_ID = "demo-session"

if "history" not in st.session_state:
    st.session_state.history = []  # [(role, text)]
if "last_evidence" not in st.session_state:
    st.session_state.last_evidence = []
if "busy" not in st.session_state:
    st.session_state.busy = False

# ===== 사이드바 =====
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    API_BASE = st.text_input("API Base", DEFAULT_API_BASE, help="FastAPI Base URL")
    SESSION_ID = st.text_input("Session ID", DEFAULT_SESSION_ID)
    top_k = st.slider("근거 문서 개수 (top_k)", 1, 8, 5)
    max_ctx = st.slider("최근 대화 맥락", 1, 20, 8)
    show_score = st.toggle("근거 점수 표시", value=True)
    st.markdown("---")
    colA, colB = st.columns(2)
    with colA:
        if st.button("🧹 대화 초기화", use_container_width=True):
            st.session_state.history = []
            st.session_state.last_evidence = []
            st.toast("대화를 초기화했어요.", icon="🧽")
    with colB:
        if st.button("🌱 시드(seed_demo)", use_container_width=True):
            try:
                r = requests.post(f"{API_BASE}/seed_demo", timeout=60)
                st.success(r.json())
            except Exception as e:
                st.error(f"시드 실패: {e}")

# ===== 헤더 / 히어로 =====
st.markdown("""
<div class="hero">
  <h2 style="margin:0 0 .4rem 0">✨ RAG Chat</h2>
  <div class="subtle">검색 증거 기반 답변 · 문서 스니펫과 점수 확인 · 간단한 설정 튜닝</div>
</div>
""", unsafe_allow_html=True)

# ===== 입력 영역 (Form으로 엔터 제출 지원) =====
with st.form("chat-form"):
    user_input = st.text_area("질문을 입력하세요", "", key="user_input", height=80, placeholder="예) 보험 청구 단계 알려줘 / 특정 정책 PDF의 요약 보여줘")
    col1, col2, col3 = st.columns([1,1,4])
    send = col1.form_submit_button("🚀 전송", use_container_width=True, disabled=st.session_state.busy)
    stop = col2.form_submit_button("⏹️ 중단", use_container_width=True, disabled=not st.session_state.busy, help="(시연용) 요청 중단 느낌만 제공")
    if stop and st.session_state.busy:
        # 실제 스트림 중단 로직이 없다면 플래그만 변경
        st.session_state.busy = False
        st.warning("요청 중단 신호를 보냈어요(데모).")

# ===== 전송 처리 =====
if send and user_input.strip():
    st.session_state.history.append(("user", user_input.strip()))
    st.session_state.busy = True
    placeholder = st.empty()
    with placeholder.container():
        with st.status("모델이 답변을 생성하는 중...", expanded=True) as status:
            st.write("컨텍스트 정리 및 검색…")
            time.sleep(0.2)

            try:
                resp = requests.post(
                    f"{API_BASE}/chat",
                    json={
                        "session_id": SESSION_ID,
                        "message": user_input.strip(),
                        "top_k": top_k,
                        "max_context": max_ctx,
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.history.append(("assistant", data.get("answer", "")))
                    st.session_state.last_evidence = data.get("evidence", [])
                    status.update(label="완료!", state="complete")
                else:
                    st.session_state.history.append(("assistant", f"❌ 오류: {resp.status_code}"))
                    status.update(label="오류", state="error")
            except Exception as e:
                st.session_state.history.append(("assistant", f"❌ 예외: {e}"))
                status.update(label="예외", state="error")
            finally:
                st.session_state.busy = False
                placeholder.empty()

# ===== 채팅 표시 (말풍선 스타일) =====
for role, text in st.session_state.history:
    if role == "user":
        st.markdown(f"""
        <div class="card">
          <div class="chat-bubble user"><b>👤 User</b><br>{st.markdown(text, help=None)._repr_markdown_()}</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="card">
          <div class="chat-bubble assistant"><b>🤖 Assistant</b><br>{st.markdown(text, help=None)._repr_markdown_()}</div>
        </div>""", unsafe_allow_html=True)

# ===== 근거(증거) 섹션 =====
evidence = st.session_state.last_evidence or []
if evidence:
    st.markdown("### 🔍 근거")
    with st.expander("모델이 참고한 문서 보기", expanded=True):
        for i, ev in enumerate(evidence, 1):
            score = ev.get("score", None)
            title = ev.get("title") or f"문서 {ev.get('id') or i}"
            url = ev.get("url") or ""
            snippet = ev.get("snippet") or ""

            meta = ""
            if show_score and score is not None:
                try:
                    meta = f'<span class="badge">score {float(score):.3f}</span>'
                except Exception:
                    meta = f'<span class="badge">score {score}</span>'

            link = f' · <a class="evi" href="{url}" target="_blank">원문</a>' if url else ""
            st.markdown(
                f"""
                <div class="card">
                  <div style="display:flex;align-items:center;justify-content:space-between;">
                    <div><b>[{i}] {title}</b>{meta}{link}</div>
                  </div>
                  <div class="subtle" style="margin-top:.5rem">{snippet}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
