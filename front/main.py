import os, requests, streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")  # 백엔드 주소
USER_ID = "demo_user"

st.set_page_config(page_title="보험 RAG 플랫폼", layout="wide")
st.title("보험 문서 RAG 플랫폼")

tab1, tab2 = st.tabs(["Q&A", "문서 검색"])

with tab1:
    q = st.text_input("질문을 입력하세요")
    if st.button("질문하기"):
        try:
            resp = requests.post(f"{API_BASE}/ask", json={"user_id": USER_ID, "question": q}, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            st.write(data["answer"])
            if data.get("sources"):
                st.json(data["sources"])
        except Exception as e:
            st.error(f"요청 실패: {e}")

with tab2:
    q = st.text_input("검색어", key="search")
    if st.button("검색하기"):
        try:
            resp = requests.post(f"{API_BASE}/search", json={"q": q, "top_k": 5}, timeout=30)
            resp.raise_for_status()
            for item in resp.json():
                st.write(f"- {item['title']} : {item['snippet']}")
        except Exception as e:
            st.error(f"검색 실패: {e}")
