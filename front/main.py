# front/main.py
# -----------------------------------------------------------------------------
# 기능: Streamlit 프론트엔드
#  - 백엔드 FastAPI 라우트(/qa/ask, /qa/search)에 맞춰 호출
#  - Q&A 탭: 질문 → /qa/ask → 답변/출처 표시
#  - 문서 검색 탭: 키워드 → /qa/search → 스니펫/점수 표시
#  - API_BASE는 secrets.toml 또는 환경변수에서 읽음
# -----------------------------------------------------------------------------

import os
import requests
import streamlit as st

# 백엔드 주소: secrets.toml > 환경변수 > 기본값
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="보험 RAG 플랫폼", layout="wide")
st.title("보험 문서 RAG 플랫폼")

tab1, tab2 = st.tabs(["Q&A", "문서 검색"])

# -----------------------------
# Q&A 탭: /qa/ask 호출
# -----------------------------
with tab1:
    left, right = st.columns([3, 1])

    with left:
        q = st.text_input("질문을 입력하세요", placeholder="예) 실손 청구에 필요한 서류는?")

    with right:
        insurers = ["", "DB손해", "현대해상", "삼성화재"]
        policy = st.selectbox("보험사(선택)", insurers, index=0)
        top_k = st.slider("Top-K", 1, 10, 5)

    if st.button("질문하기", use_container_width=True, disabled=not q):
        try:
            # /qa/ask는 'question' 키를 받도록 맞춤 (백엔드 AskRequest)
            payload = {
                "question": q,
                "policy_type": policy or None,
                "top_k": int(top_k),
                "max_tokens": 600,
            }
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
                        st.write((s.get("content") or "")[:2000])

        except Exception as e:
            st.error(f"요청 실패: {e}")

# -----------------------------
# 문서 검색 탭: /qa/search 호출
# -----------------------------
with tab2:
    left, right = st.columns([3, 1])

    with left:
        q_search = st.text_input("검색어", key="search", placeholder="예) 입원비 지급 한도")

    with right:
        insurers2 = ["", "DB손해", "현대해상", "삼성화재"]
        policy2 = st.selectbox("보험사(선택)", insurers2, index=0, key="policy2")
        top_k2 = st.slider("Top-K(검색)", 1, 20, 5, key="topk2")

    if st.button("검색하기", use_container_width=True, disabled=not q_search):
        try:
            # /qa/search는 'q' 키를 받도록 맞춤 (백엔드 SearchReq)
            payload = {
                "q": q_search,
                "policy_type": policy2 or None,
                "top_k": int(top_k2),
            }
            resp = requests.post(f"{API_BASE}/qa/search", json=payload, timeout=30)
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

        except Exception as e:
            st.error(f"검색 실패: {e}")

# 하단 디버그용 표시(선택)
st.caption(f"API_BASE = {API_BASE}")
