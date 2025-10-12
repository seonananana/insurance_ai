# front/main.py
# -----------------------------------------------------------------------------
# 기능: Streamlit 프론트엔드
#  - 백엔드 FastAPI 라우트(/qa/ask, /qa/search) 호출
#  - Q&A 탭: 질문 → /qa/ask → 답변/출처 표시
#  - 문서 검색 탭: 키워드 → /qa/search → 스니펫/점수 표시
#  - API_BASE: 환경변수 > secrets.toml > 기본값
# -----------------------------------------------------------------------------

import os
import requests
import streamlit as st

# 백엔드 주소: 환경변수 > secrets.toml > 기본값
API_BASE = os.getenv("API_BASE") or st.secrets.get("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="보험 RAG 플랫폼", layout="wide")
st.title("보험 문서 RAG 플랫폼")

tab1, tab2 = st.tabs(["Q&A", "문서 검색"])

# 공통: 보험사 선택 옵션 (ETL의 상위 폴더명과 일치해야 필터 적용)
INSURERS = ["", "DB손해", "현대해상", "삼성화재"]

# -----------------------------
# Q&A 탭: /qa/ask 호출
# -----------------------------
with tab1:
    left, right = st.columns([3, 1])
    with left:
        q = st.text_input("질문을 입력하세요", placeholder="예) 실손 청구에 필요한 서류는?")
    with right:
        policy = st.selectbox("보험사(선택)", INSURERS, index=0)
        top_k = st.slider("Top-K", 1, 10, 5)

    if st.button("질문하기", use_container_width=True, disabled=not q):
        try:
            payload = {
                "q": q,
                "top_k": int(top_k),
            }
            # 빈 문자열("")이면 보내지 않음 (검증 오류 방지)
            if policy:
                payload["policy_type"] = policy

            resp = requests.post(f"{API_BASE}/qa/ask", json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            st.markdown("### 답변")
            st.write(data.get("answer", ""))

            sources = data.get("sources") or []
            if sources:
                st.markdown("### 출처 (Top-K)")
                for s in sources:
                    title = s.get("clause_title") or "문서"
                    score = s.get("score")
                    score_txt = f" · score={score:.4f}" if isinstance(score, (int, float)) else ""
                    st.markdown(f"- **{title}**{score_txt}")
                    with st.expander("내용 보기", expanded=False):
                        st.write((s.get("content", "") or "")[:1200])

        except requests.RequestException as e:
            st.error(f"요청 실패: {e}")
        except Exception as e:
            st.error(f"알 수 없는 오류: {e}")

# -----------------------------
# 문서 검색 탭: /qa/search 호출
# -----------------------------
with tab2:
    left, right = st.columns([3, 1])
    with left:
        q_search = st.text_input("검색어", key="search", placeholder="예) 입원비 지급 한도")
    with right:
        policy2 = st.selectbox("보험사(선택)", INSURERS, index=0, key="policy2")
        top_k2 = st.slider("Top-K(검색)", 1, 20, 5, key="topk2")

    if st.button("검색하기", use_container_width=True, disabled=not q_search):
        try:
            payload = {"q": q_search, "top_k": int(top_k2)}
            if policy2:
                payload["policy_type"] = policy2

            resp = requests.post(f"{API_BASE}/qa/search)", json=payload, timeout=30)
            # ↑ 오타 방지: 위 줄의 끝에 '}' 가 들어가면 안 됩니다. 정확히는:
            # resp = requests.post(f"{API_BASE}/qa/search", json=payload, timeout=30)
        except Exception:
            # 오타 방지용으로 한 번 더 정확히 호출
            resp = requests.post(f"{API_BASE}/qa/search", json=payload, timeout=30)

        try:
            resp.raise_for_status()
            items = resp.json()

            if not items:
                st.info("검색 결과가 없습니다. (임베딩 데이터 확인)")
            else:
                st.markdown("### 검색 결과")
                for it in items:
                    title = it.get("clause_title") or "문서"
                    score = it.get("score")
                    snippet = it.get("content_snippet") or ""
                    score_txt = f" | score={score:.4f}" if isinstance(score, (int, float)) else ""
                    st.markdown(f"- **{title}**{score_txt}")
                    st.write(snippet)

        except requests.RequestException as e:
            st.error(f"검색 실패: {e}")
        except Exception as e:
            st.error(f"알 수 없는 오류: {e}")

# 하단 디버그용 표시(선택)
st.caption(f"API_BASE = {API_BASE}")

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE", "http://localhost:8000")

tab1, tab2, tab3 = st.tabs(["Q&A", "문서 검색", "Chat"])  # ← Chat 탭 추가

with tab3:
    st.subheader("OpenAI Chat")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    user_in = st.text_input("메시지 입력", key="chat_input", placeholder="무엇이든 질문하세요")
    colA, colB = st.columns([1,1])
    with colA:
        temp = st.slider("temperature", 0.0, 1.0, 0.3, 0.1)
    with colB:
        mtok = st.slider("max_tokens", 64, 2048, 512, 64)

    if st.button("보내기", use_container_width=True, disabled=not user_in):
        msgs = [{"role":"user","content":user_in}]
        # (원하면 대화 맥락 유지) st.session_state.chat_history 누적 사용
        payload = {"messages": st.session_state.chat_history + msgs, "temperature": float(temp), "max_tokens": int(mtok)}
        try:
            r = requests.post(f"{API_BASE}/chat/completion", json=payload, timeout=60)
            r.raise_for_status()
            reply = r.json().get("reply","")
            st.session_state.chat_history += msgs + [{"role":"assistant","content":reply}]
        except Exception as e:
            st.error(f"요청 실패: {e}")

    # 대화 표시
    for m in st.session_state.chat_history[-12:]:
        role = "🧑‍💻" if m["role"]=="user" else "🤖"
        st.markdown(f"**{role} {m['role']}**: {m['content']}")
