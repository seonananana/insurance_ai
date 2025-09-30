import requests
import streamlit as st

API_BASE = "http://localhost:8000"  # UTM 주소/포트에 맞게 수정
SESSION_ID = "demo-session"

st.set_page_config(page_title="RAG Chat", layout="centered")
st.title("RAG Chat")

with st.sidebar:
    st.markdown("### 설정")
    top_k = st.slider("근거 문서 개수 (top_k)", 1, 8, 5)
    max_ctx = st.slider("최근 대화 맥락", 1, 20, 8)

if "history" not in st.session_state:
    st.session_state["history"] = []

# 입력창
user_input = st.text_input("질문을 입력하세요", "", key="user_input")

col1, col2 = st.columns([1,1])
with col1:
    if st.button("전송") and user_input.strip():
        st.session_state["history"].append(("user", user_input))
        try:
            resp = requests.post(
                f"{API_BASE}/chat",
                json={"session_id": SESSION_ID, "message": user_input, "top_k": top_k, "max_context": max_ctx},
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state["history"].append(("assistant", data["answer"]))
                # evidence 표시를 위해 임시 저장
                st.session_state["last_evidence"] = data.get("evidence", [])
            else:
                st.session_state["history"].append(("assistant", f"❌ 오류: {resp.status_code}"))
        except Exception as e:
            st.session_state["history"].append(("assistant", f"❌ 예외: {e}"))

with col2:
    if st.button("샘플 문서 시드(seed_demo)"):
        r = requests.post(f"{API_BASE}/seed_demo")
        st.success(r.json())

# 대화 표시
for role, text in st.session_state["history"]:
    if role == "user":
        st.markdown(f"**👤 User:** {text}")
    else:
        st.markdown(f"**🤖 Assistant:** {text}")

# 근거(증거) 박스
evidence = st.session_state.get("last_evidence", [])
if evidence:
    st.markdown("---")
    st.markdown("### 근거")
    for i, ev in enumerate(evidence, 1):
        score = f"{ev.get('score', 0):.3f}" if "score" in ev else "-"
        title = ev.get("title") or f"문서 {ev.get('id')}"
        url = ev.get("url") or ""
        snippet = ev.get("snippet") or ""
        st.markdown(f"**[{i}] {title}**  (score: {score})")
        if url:
            st.markdown(f"- URL: {url}")
        st.caption(snippet)
