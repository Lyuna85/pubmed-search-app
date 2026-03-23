import streamlit as st
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def search_pubmed(query, max_results, email, year_start=None, year_end=None):
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
        "email": email,
        "tool": "pubmed-streamlit-app",
    }
    if year_start and year_end:
        params["mindate"] = f"{year_start}/01/01"
        params["maxdate"] = f"{year_end}/12/31"
        params["datetype"] = "pdat"

    response = requests.get(ESEARCH_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["esearchresult"]["idlist"]


def fetch_details(pmids, email):
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
        "email": email,
        "tool": "pubmed-streamlit-app",
    }
    response = requests.get(EFETCH_URL, params=params, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    articles = []

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        title_el = article.find(".//ArticleTitle")
        title = "".join(title_el.itertext()) if title_el is not None else "제목 없음"

        # 저자 목록
        authors = []
        for author in article.findall(".//Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {fore}".strip())
        author_str = ", ".join(authors[:5])
        if len(authors) > 5:
            author_str += " et al."

        # 저널
        journal_el = article.find(".//Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # 출판일
        pub_year = article.findtext(".//PubDate/Year", "")
        pub_month = article.findtext(".//PubDate/Month", "")
        pub_date = f"{pub_year} {pub_month}".strip()

        # 초록
        abstract_texts = article.findall(".//AbstractText")
        abstract_parts = []
        for ab in abstract_texts:
            label = ab.get("Label")
            text = "".join(ab.itertext())
            if label:
                abstract_parts.append(f"**{label}:** {text}")
            else:
                abstract_parts.append(text)
        abstract = "\n\n".join(abstract_parts) if abstract_parts else "초록 없음"

        # DOI 및 PMC ID
        doi = ""
        pmc_id = ""
        for article_id in article.findall(".//ArticleIdList/ArticleId"):
            id_type = article_id.get("IdType", "")
            if id_type == "doi":
                doi = article_id.text or ""
            elif id_type == "pmc":
                pmc_id = article_id.text or ""

        articles.append({
            "PMID": pmid,
            "제목": title,
            "저자": author_str,
            "저널": journal,
            "출판일": pub_date,
            "초록": abstract,
            "DOI": doi,
            "PMC_ID": pmc_id,
            "링크": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })

    return articles


# ── UI ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="PubMed 논문 검색", page_icon="🔬", layout="wide")
st.title("🔬 PubMed 논문 검색")
st.caption("NCBI PubMed API를 이용한 논문 검색 도구")

# 사이드바 — 이메일 설정
with st.sidebar:
    st.header("설정")
    user_email = st.text_input(
        "이메일 주소",
        placeholder="your@email.com",
        help="NCBI 이용약관에 따라 API 요청 시 이메일을 포함하는 것을 권장합니다."
    )
    if not user_email:
        st.warning("이메일을 입력하면 NCBI 서버에 요청자 정보가 기록됩니다.")

# 검색 폼
with st.form("search_form"):
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input("검색어", placeholder="예: COVID-19 vaccine efficacy")
    with col2:
        max_results = st.selectbox("결과 수", [10, 20, 50], index=1)

    col3, col4, col5 = st.columns([1, 1, 2])
    with col3:
        use_date = st.checkbox("날짜 필터 사용")
    with col4:
        year_start = st.number_input("시작 연도", min_value=1900, max_value=datetime.now().year,
                                     value=2020, disabled=not use_date)
    with col5:
        year_end = st.number_input("종료 연도", min_value=1900, max_value=datetime.now().year,
                                   value=datetime.now().year, disabled=not use_date)

    submitted = st.form_submit_button("검색", use_container_width=True, type="primary")

# 검색 실행
if submitted and query.strip():
    with st.spinner("PubMed에서 논문을 검색 중입니다..."):
        try:
            y_start = int(year_start) if use_date else None
            y_end = int(year_end) if use_date else None

            pmids = search_pubmed(query.strip(), max_results, user_email, y_start, y_end)

            if not pmids:
                st.warning("검색 결과가 없습니다. 다른 검색어를 시도해보세요.")
            else:
                articles = fetch_details(pmids, user_email)
                st.success(f"**{len(articles)}개** 논문을 찾았습니다.")

                # CSV 다운로드
                df = pd.DataFrame(articles)
                csv = df.drop(columns=["초록", "PMC_ID"]).to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="📥 CSV 다운로드",
                    data=csv,
                    file_name=f"pubmed_{query[:30].replace(' ', '_')}.csv",
                    mime="text/csv",
                )

                st.divider()

                # 결과 목록
                for i, art in enumerate(articles, 1):
                    with st.container():
                        st.markdown(f"#### {i}. [{art['제목']}]({art['링크']})")
                        meta_col1, meta_col2, meta_col3 = st.columns(3)
                        with meta_col1:
                            first_author = art['저자'].split(',')[0] if art['저자'] else '저자 정보 없음'
                            st.caption(f"👤 {first_author}")
                        with meta_col2:
                            st.caption(f"📰 {art['저널'] or '저널 정보 없음'}")
                        with meta_col3:
                            st.caption(f"📅 {art['출판일'] or '날짜 정보 없음'}")

                        if art["DOI"]:
                            st.caption(f"🔗 DOI: https://doi.org/{art['DOI']}")

                        btn_col1, btn_col2 = st.columns([1, 5])
                        with btn_col1:
                            if art["PMC_ID"]:
                                pmc_num = art["PMC_ID"].replace("PMC", "")
                                pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{art['PMC_ID']}/pdf/"
                                try:
                                    pdf_resp = requests.get(pdf_url, timeout=15, allow_redirects=True)
                                    if pdf_resp.status_code == 200 and "application/pdf" in pdf_resp.headers.get("Content-Type", ""):
                                        st.download_button(
                                            label="📄 PDF 다운로드",
                                            data=pdf_resp.content,
                                            file_name=f"{art['PMC_ID']}.pdf",
                                            mime="application/pdf",
                                            key=f"pdf_{art['PMID']}",
                                        )
                                    else:
                                        st.link_button("📄 PDF 보기 (PMC)", f"https://www.ncbi.nlm.nih.gov/pmc/articles/{art['PMC_ID']}/pdf/")
                                except Exception:
                                    st.link_button("📄 PDF 보기 (PMC)", f"https://www.ncbi.nlm.nih.gov/pmc/articles/{art['PMC_ID']}/pdf/")

                        with st.expander("초록 보기"):
                            st.markdown(art["초록"])

                        st.divider()

        except requests.exceptions.Timeout:
            st.error("요청 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.")
        except requests.exceptions.RequestException as e:
            st.error(f"네트워크 오류가 발생했습니다: {e}")

elif submitted and not query.strip():
    st.warning("검색어를 입력해주세요.")
