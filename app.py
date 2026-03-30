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
        author_str = authors[0] if authors else ""

        # 저널
        journal_el = article.find(".//Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # 출판일
        pub_year = article.findtext(".//PubDate/Year", "")

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
            "Year": pub_year,
            "Journal": journal,
            "First_Author": author_str,
            "Title": title,
            "Link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "Abstract": abstract,
            "PMID": pmid,
            "DOI": doi,
            "PMC_ID": pmc_id,
        })

    return articles


# ── UI ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="PubMed 논문 검색", page_icon="🔬", layout="wide")

# 인증 블록
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.subheader("🔐 접근 제한")
    pw = st.text_input("비밀번호를 입력하세요", type="password")
    if st.button("확인"):
        if pw == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

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
        query = st.text_input(
            "검색어 (쉼표로 구분 시 AND 검색)",
            placeholder="예: EGFR, lung cancer, mutation",
            help="저자 검색: 검색어에 [au] 태그 사용 가능 — 예: Kim J[au], EGFR"
        )
    with col2:
        max_results = st.selectbox("결과 수", [10, 20, 50, 100], index=1)

    author_query = st.text_input("저자명 (쉼표로 구분 시 OR 검색)", placeholder="예: Kim J, Park S")

    year_start, year_end = st.slider(
        "출판 연도 범위",
        min_value=1900,
        max_value=datetime.now().year,
        value=(2020, datetime.now().year),
    )

    submitted = st.form_submit_button("검색", use_container_width=True, type="primary")

# 검색 실행
if submitted and (query.strip() or author_query.strip()):
    with st.spinner("PubMed에서 논문을 검색 중입니다..."):
        try:
            y_start = int(year_start)
            y_end = int(year_end)

            terms = [t.strip() for t in query.strip().split(",") if t.strip()]
            pubmed_query = " AND ".join(terms)

            if author_query.strip():
                authors = [a.strip() for a in author_query.strip().split(",") if a.strip()]
                author_part = " OR ".join(f'"{a}"[au]' for a in authors)
                if len(authors) > 1:
                    author_part = f"({author_part})"
                pubmed_query = f"{pubmed_query} AND {author_part}" if pubmed_query else author_part

            pmids = search_pubmed(pubmed_query, max_results, user_email, y_start, y_end)

            if not pmids:
                st.warning("검색 결과가 없습니다. 다른 검색어를 시도해보세요.")
            else:
                articles = fetch_details(pmids, user_email)
                articles.sort(key=lambda x: x["Year"] or "0", reverse=True)
                st.session_state.articles = articles
                st.session_state.last_query = pubmed_query

        except requests.exceptions.Timeout:
            st.error("요청 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.")
        except requests.exceptions.RequestException as e:
            st.error(f"네트워크 오류가 발생했습니다: {e}")

elif submitted and not query.strip() and not author_query.strip():
    st.warning("검색어 또는 저자명을 입력해주세요.")

# 결과 표시
if "articles" in st.session_state and st.session_state.articles:
    articles = st.session_state.articles
    last_query = st.session_state.get("last_query", "")

    st.success(f"**{len(articles)}개** 논문을 찾았습니다.")

    # 결과 내 재검색
    filter_term = st.text_input("결과 내 재검색 (쉼표로 구분 시 AND 검색)", placeholder="예: EGFR, lung cancer", key="filter")
    if filter_term.strip():
        keywords = [k.strip() for k in filter_term.strip().lower().split(",") if k.strip()]
        articles = [
            a for a in articles
            if all(
                kw in a["Title"].lower()
                or kw in a["First_Author"].lower()
                or kw in a["Journal"].lower()
                or kw in a["Abstract"].lower()
                for kw in keywords
            )
        ]
        st.caption(f"재검색 결과: **{len(articles)}개** (키워드: {', '.join(keywords)})")

    # CSV 다운로드
    df = pd.DataFrame(articles)
    csv = df.drop(columns=["PMC_ID"]).to_csv(index=False, encoding="utf-8-sig")
    default_name = f"pubmed_{last_query[:30].replace(' ', '_')}"
    csv_filename = st.text_input("파일 이름", value=default_name)
    st.download_button(
        label="📥 CSV 다운로드",
        data=csv,
        file_name=f"{csv_filename}.csv",
        mime="text/csv",
    )

    st.divider()

    # 결과 목록
    for i, art in enumerate(articles, 1):
        with st.container():
            st.markdown(f"#### {i}. [{art['Title']}]({art['Link']})")
            meta_col1, meta_col2, meta_col3 = st.columns(3)
            with meta_col1:
                first_author = art['First_Author'].split(',')[0] if art['First_Author'] else '저자 정보 없음'
                st.caption(f"👤 {first_author}")
            with meta_col2:
                st.caption(f"📰 {art['Journal'] or '저널 정보 없음'}")
            with meta_col3:
                st.caption(f"📅 {art['Year'] or '날짜 정보 없음'}")

            if art["DOI"]:
                st.caption(f"🔗 DOI: https://doi.org/{art['DOI']}")

            btn_col1, btn_col2 = st.columns([1, 5])
            with btn_col1:
                if art["PMC_ID"]:
                    pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{art['PMC_ID']}/"
                    st.link_button("📄 PDF 보기 (PMC)", pmc_url)

            with st.expander("초록 보기"):
                st.markdown(art["Abstract"])

            st.divider()
