import streamlit as st
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime
from openai import AzureOpenAI
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@st.cache_data(show_spinner=False)
def translate_abstract(abstract):
    try:
        client = AzureOpenAI(
            api_key=st.secrets["AZURE_OPENAI_KEY"],
            azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"],
            api_version="2024-02-01",
        )
        response = client.chat.completions.create(
            model=st.secrets["AZURE_OPENAI_DEPLOYMENT"],
            messages=[
                {"role": "system", "content": "논문 초록을 한국어로 번역해줘. 학술적 표현을 유지하고 번역문만 출력해."},
                {"role": "user", "content": abstract},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"번역 오류: {e}"


def search_pubmed(query, max_results, email, year_start=None, year_end=None):
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "email": email,
        "tool": "pubmed-streamlit-app",
        "api_key": st.secrets.get("NCBI_API_KEY", ""),
    }
    if year_start and year_end:
        params["mindate"] = f"{year_start}/01/01"
        params["maxdate"] = f"{year_end}/12/31"
        params["datetype"] = "pdat"

    response = requests.get(ESEARCH_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["esearchresult"]["idlist"]


def fetch_citations(pmids):
    try:
        response = requests.get(
            "https://icite.od.nih.gov/api/pubs",
            params={"pmids": ",".join(pmids)},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return {str(p["pmid"]): p.get("citation_count", 0) for p in data.get("data", [])}
    except Exception:
        return {}


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
        "api_key": st.secrets.get("NCBI_API_KEY", ""),
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
        author_str = ", ".join(authors) if authors else ""

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

    st.divider()
    st.subheader("결과 옵션")
    remove_duplicates = st.checkbox("중복 논문 제거", value=True)
    show_citations = st.checkbox("인용수 표시 및 정렬", value=False)
    if show_citations:
        sort_by = st.radio("정렬 기준", ["연도 내림차순", "인용수 내림차순"], index=0)
    else:
        sort_by = "연도 내림차순"

# 검색 폼
with st.form("search_form"):
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        query = st.text_input(
            "검색어 (쉼표로 구분 시 AND 검색)",
            placeholder="예: EGFR, lung cancer, mutation",
            help="저자 검색: 검색어에 [au] 태그 사용 가능 — 예: Kim J[au], EGFR"
        )
    with col2:
        max_results = st.selectbox("결과 수", [10, 20, 50, 100], index=1)
    with col3:
        search_field = st.selectbox("검색 범위", ["전체 필드", "제목/초록", "제목만"], index=1)

    author_query = st.text_input("저자명 (쉼표로 구분 시 OR 검색)", placeholder="예: Kim J, Park S")

    use_date = st.checkbox("출판 연도 범위 필터 사용")
    year_start, year_end = st.slider(
        "출판 연도 범위",
        min_value=1900,
        max_value=datetime.now().year,
        value=(2020, datetime.now().year),
        disabled=not use_date,
    )

    submitted = st.form_submit_button("검색", use_container_width=True, type="primary")

# 검색 실행
if submitted and (query.strip() or author_query.strip()):
    with st.spinner("PubMed에서 논문을 검색 중입니다..."):
        try:
            y_start = int(year_start) if use_date else None
            y_end = int(year_end) if use_date else None

            field_tag = {"전체 필드": "", "제목/초록": "[tiab]", "제목만": "[ti]"}[search_field]
            terms = [t.strip() for t in query.strip().split(",") if t.strip()]
            pubmed_query = " AND ".join(f'"{t}"{field_tag}' if field_tag else t for t in terms)

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

                if remove_duplicates:
                    seen = set()
                    articles = [a for a in articles if not (a["PMID"] in seen or seen.add(a["PMID"]))]

                if show_citations:
                    citations = fetch_citations([a["PMID"] for a in articles])
                    for a in articles:
                        a["Citations"] = citations.get(a["PMID"], 0)
                else:
                    for a in articles:
                        a["Citations"] = None

                if sort_by == "인용수 내림차순":
                    articles.sort(key=lambda x: x["Citations"] or 0, reverse=True)
                else:
                    articles.sort(key=lambda x: x["Year"] or "0", reverse=True)

                st.session_state.articles = articles
                st.session_state.show_citations = show_citations
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

    # 결과에서 제외
    excol1, excol2 = st.columns([3, 1])
    with excol1:
        exclude_term = st.text_input("결과에서 제외 (쉼표로 구분 시 OR 제외)", placeholder="예: review, meta-analysis", key="exclude")
    with excol2:
        exclude_field = st.selectbox("제외 범위", ["제목/초록", "제목만", "저자"], key="exclude_field")
    if exclude_term.strip():
        keywords = [k.strip() for k in exclude_term.strip().lower().split(",") if k.strip()]
        def match_exclude(a, kw):
            if exclude_field == "제목/초록":
                return kw in a["Title"].lower() or kw in a["Abstract"].lower()
            elif exclude_field == "제목만":
                return kw in a["Title"].lower()
            else:
                return kw in a["First_Author"].lower()
        articles = [a for a in articles if not any(match_exclude(a, kw) for kw in keywords)]
        st.caption(f"제외 후 결과: **{len(articles)}개** (제외 키워드: {', '.join(keywords)})")

    # CSV 다운로드
    df = pd.DataFrame(articles)
    df["First_Author"] = df["First_Author"].apply(lambda x: x.split(",")[0].strip() if x else "")
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
                first_author = art['First_Author'].split(',')[0].strip() if art['First_Author'] else '저자 정보 없음'
                st.caption(f"👤 {first_author}")
                if art['First_Author'] and ',' in art['First_Author']:
                    with st.expander("전체 저자 보기"):
                        st.caption(art['First_Author'])
            with meta_col2:
                st.caption(f"📰 {art['Journal'] or '저널 정보 없음'}")
            with meta_col3:
                st.caption(f"📅 {art['Year'] or '날짜 정보 없음'}")

            if st.session_state.get("show_citations") and art.get("Citations") is not None:
                st.caption(f"📊 인용수: {art['Citations']}")

            if art["DOI"]:
                st.caption(f"🔗 DOI: https://doi.org/{art['DOI']}")

            btn_col1, btn_col2 = st.columns([1, 5])
            with btn_col1:
                if art["PMC_ID"]:
                    pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{art['PMC_ID']}/"
                    st.link_button("📄 PDF 보기 (PMC)", pmc_url)

            with st.expander("초록 보기"):
                st.markdown(art["Abstract"])
                if st.button("🇰🇷 한국어 번역", key=f"translate_{art['PMID']}"):
                    with st.spinner("번역 중..."):
                        translated = translate_abstract(art["Abstract"])
                    st.markdown("---")
                    st.markdown(translated)

            st.divider()
