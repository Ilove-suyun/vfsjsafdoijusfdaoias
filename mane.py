import datetime
import requests
import pandas as pd
import pytz
import streamlit as st

# 페이지 기본 설정 (타이틀, 레이아웃)
st.set_page_config(page_title="일별 박스오피스 조회", layout="wide")


# 동일한 날짜 요청 시 API 중복 호출을 방지하기 위한 캐싱 함수 (1시간 = 3600초 유지)
@st.cache_data(ttl=3600)
def fetch_daily_box_office(api_key, target_date):
    """KOBIS API를 호출하여 해당 날짜의 박스오피스 데이터를 가져옵니다."""
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {"key": api_key, "targetDt": target_date}

    try:
        response = requests.get(url, params=params, timeout=10)
        # HTTP 응답 상태 코드가 200이 아닌 경우 예외 발생
        response.raise_for_status()
        return response.json(), None
    except Exception as e:
        return None, f"네트워크 요청 중 오류가 발생했습니다: {e}"


def get_korea_yesterday():
    """배포 서버의 시계와 상관없이 한국 표준시(KST) 기준 '어제' 날짜 객체를 구합니다."""
    kst = pytz.timezone("Asia/Seoul")
    now_kst = datetime.datetime.now(kst)
    yesterday_kst = now_kst - datetime.timedelta(days=1)
    return yesterday_kst.date()


def format_rank_change(val):
    """전날 대비 순위 증감(rankInten) 수치를 화살표 기호로 변환합니다."""
    if val > 0:
        return f"🔺 +{val}"  # 순위 상승 (빨간 위 화살표)
    elif val < 0:
        return f"🔹 {val}"  # 순위 하락 (파란 아래 화살표)
    else:
        return "-"  # 변동 없음


def main():
    st.title("🎬 일별 박스오피스 조회")

    # 1. Streamlit Secrets에서 API 키 불러오기
    if "KOBIS_KEY" not in st.secrets:
        st.error(
            "🔑 Secrets에 KOBIS_KEY가 설정되지 않았습니다. Streamlit Cloud 설정에서 Secret을 추가해 주세요."
        )
        st.info("설정 예시: KOBIS_KEY = '발급받은_API_키'")
        return

    api_key = st.secrets["KOBIS_KEY"]

    # 2. 한국 시간 기준 '어제' 날짜 계산 (선택 가능한 최대 날짜)
    max_date = get_korea_yesterday()

    # 사이드바에서 조회할 날짜를 달력으로 선택
    st.sidebar.header("🗓️ 날짜 선택")
    selected_date = st.sidebar.date_input(
        "조회할 날짜를 선택하세요",
        value=max_date,  # 기본값: 어제
        max_value=max_date,  # 선택 가능 최대 날짜: 어제
    )

    # API 변수에 맞게 YYYYMMDD 형태 문자열 변환
    target_dt_str = selected_date.strftime("%Y%m%d")
    display_date_str = selected_date.strftime("%Y년 %m월 %d일")

    st.subheader(f"📅 {display_date_str} 박스오피스")

    # 3. API 데이터 불러오기
    data, error_msg = fetch_daily_box_office(api_key, target_dt_str)

    # 네트워크 요청 자체 실패 시 안내
    if error_msg:
        st.error(error_msg)
        st.warning(
            "💡 확인해 보세요:\n- 인터넷 연결 상태를 확인해 주세요.\n- KOBIS API 서버가 정상 작동 중인지 확인해 주세요."
        )
        return

    # 4. KOBIS 응답 예외 처리 (인증키 오류 등 faultInfo가 포함된 경우)
    if "faultInfo" in data:
        st.error("❌ API 요청 중 오류가 발생했습니다.")
        fault = data["faultInfo"]
        st.write(
            f"**오류 메시지:** {fault.get('message', '알 수 없는 오류')}"
        )
        st.warning(
            "💡 확인해 보세요:\n- Streamlit Secrets에 입력한 KOBIS_KEY가 올바른지 확인해 주세요.\n- KOBIS 개발자센터에서 키 발급 상태를 확인해 주세요."
        )
        return

    # 5. 박스오피스 데이터 추출 및 목록 빈값 체크
    box_office_result = data.get("boxOfficeResult", {})
    daily_list = box_office_result.get("dailyBoxOfficeList", [])

    if not daily_list:
        st.warning("⚠️ 그날은 아직 집계 전입니다.")
        st.info(
            "💡 확인해 보세요:\n- 아직 해당 날짜의 데이터 집계가 완료되지 않았을 수 있습니다.\n- 다른 날짜를 선택해 보세요."
        )
        return

    # 6. 데이터프레임 변환 및 타입 정제 (문자열 -> 숫자)
    df = pd.DataFrame(daily_list)

    # 정렬, 조건 검사 및 그래프 처리를 위해 문자열 숫자를 정수형(int)으로 변환
    numeric_columns = [
        "rank",
        "rankInten",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
        "showCnt",
    ]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # 순위 기준 정렬
    df = df.sort_values("rank").reset_index(drop=True)

    # 7. 조건부 데이터 가공
    # (1) 누적관객 100만 명 이상 영화명 옆에 🏆 붙이기
    df["movieNm_display"] = df.apply(
        lambda row: f"{row['movieNm']} 🏆"
        if row["audiAcc"] >= 1_000_000
        else row["movieNm"],
        axis=1,
    )

    # (2) 순위 증감 화살표 기호 적용
    df["rankInten_display"] = df["rankInten"].apply(format_rank_change)

    # 8. 1위 영화 하이라이트 (카드 지표 3개)
    top_1 = df.iloc[0]
    st.markdown("### 🏆 1위 영화 하이라이트")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(label="1위 영화명", value=top_1["movieNm_display"])
    with col2:
        st.metric(label="관객수", value=f"{top_1['audiCnt']:,} 명")
    with col3:
        st.metric(label="누적 관객수", value=f"{top_1['audiAcc']:,} 명")

    st.divider()

    # 9. 관객수 상위 5편 막대그래프
    st.markdown("### 📊 관객수 상위 5편")
    top_5_df = df.head(5)
    # Streamlit 기본 차트 활용 (x축: 영화명, y축: 관객수)
    st.bar_chart(data=top_5_df, x="movieNm", y="audiCnt", color="#FF4B4B")

    st.divider()

    # 10. 전체 박스오피스 데이터 표 출력
    st.markdown("### 📋 박스오피스 순위표")

    # 표시할 컬럼 선택 및 이름 변경
    display_df = df[
        [
            "rank",
            "rankInten_display",
            "movieNm_display",
            "openDt",
            "audiCnt",
            "audiAcc",
            "scrnCnt",
        ]
    ].copy()
    display_df.columns = [
        "순위",
        "순위증감",
        "영화명",
        "개봉일",
        "관객수",
        "누적관객",
        "스크린수",
    ]

    # 숫자에 천 단위 쉼표(,) 서식 적용하여 표 표시
    st.dataframe(
        display_df.style.format(
            {"관객수": "{:,}", "누적관객": "{:,}", "스크린수": "{:,}"}
        ),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
