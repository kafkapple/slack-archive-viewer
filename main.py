import streamlit as st
import os
import glob
import json
import datetime
from hydra import initialize, compose
from omegaconf import OmegaConf
from hydra.core.global_hydra import GlobalHydra
import pandas as pd
from typing import List, Optional
from data_models import Message, Conversation, UserMapping, DMChannelMapping, SlackArchiveManager

# ================================
# Hydra 설정 불러오기
# ================================

def load_config():
    # Hydra가 이미 초기화되어 있다면 초기화 해제
    if GlobalHydra.instance().is_initialized():
        GlobalHydra.instance().clear()
    
    # Hydra 초기화 및 설정 로드
    with initialize(config_path="configs", version_base=None):
        cfg = compose(config_name="config")
    return cfg

# 설정 로드
try:
    cfg = load_config()
    # Hydra 설정으로부터 경로 정보 읽기
    channel_root_path = cfg.paths.channel_root
    dm_root_path = cfg.paths.dm_root
    user_mapping_file = cfg.paths.user_mapping_file
except Exception as e:
    st.error(f"설정 파일 로드 중 오류 발생: {str(e)}")
    # 기본값 설정
    channel_root_path = "./data/channels"
    dm_root_path = "./data/dms"
    user_mapping_file = "./data/user_mapping.json"

# ================================
# 유틸리티 함수
# ================================

def convert_user_ids_to_names(messages_data, user_mapping):
    """JSON 데이터의 user ID를 매핑된 이름으로 변환"""
    converted_data = []
    for msg in messages_data:
        msg_copy = msg.copy()
        if 'user' in msg_copy:
            user_id = msg_copy['user']
            msg_copy['user'] = user_mapping.get_name(user_id)
            msg_copy['original_user_id'] = user_id  # 원본 ID 보존
        converted_data.append(msg_copy)
    return converted_data

def export_conversation_to_txt(conv, user_mapping, file_name):
    """대화 내용을 TXT 파일로 내보내기"""
    output = []
    
    # 메인 메시지 처리
    for msg in conv.messages:
        time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
        display_name = user_mapping.get_name(msg.user_id)
        output.append(f"[{time_str}] {display_name}: {msg.text}")
        
        # 스레드 메시지 처리 (msg.replies 사용)
        if msg.replies:
            output.append("┌── 스레드 ──")
            for t_msg in sorted(msg.replies, key=lambda x: x.ts):
                t_time = t_msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                t_display = user_mapping.get_name(t_msg.user_id)
                output.append(f"│ [{t_time}] {t_display}: {t_msg.text}")
            output.append("└──────────")
        output.append("")  # 빈 줄 추가
    
    # 파일 저장
    os.makedirs("exports", exist_ok=True)
    file_path = os.path.join("exports", f"{file_name}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    
    return file_path


def aggregate_user_ids(archive_manager):
    """채널과 DM 모든 대화에서 user id 집계"""
    user_ids = set()
    for conv in list(archive_manager.channels.values()) + list(archive_manager.dms.values()):
        for msg in conv.messages:
            user_ids.add(msg.user_id)
            if msg.replies: # 스레드 답글의 사용자도 집계
                for reply_msg in msg.replies:
                    user_ids.add(reply_msg.user_id)
    return sorted(list(user_ids))

@st.cache_data(ttl=300, show_spinner=False)  # 5분 캐시
def filter_messages_by_period(_messages, period_type, period_value, start_date=None, end_date=None):
    """
    period_type: "year", "month", "quarter", "custom" 또는 None(전체)
    period_value: 해당 period에 해당하는 값
    start_date, end_date: custom 기간 선택시 사용
    """
    if period_type is None:
        return messages
        
    filtered = []
    for msg in messages:
        dt = msg.get_datetime()
        
        if period_type == "custom":
            if start_date and end_date:
                if start_date <= dt.date() <= end_date:
                    filtered.append(msg)
            continue
            
        if period_type == "year" and dt.year != period_value:
            continue
        if period_type == "month" and (dt.year, dt.month) != period_value:
            continue
        if period_type == "quarter":
            msg_quarter = (dt.month - 1) // 3 + 1
            if (dt.year, msg_quarter) != period_value:
                continue
        filtered.append(msg)
    return filtered

# ================================
# 캐시: 아카이브 매니저 로드
# ================================

@st.cache_data(ttl=3600, show_spinner=False)  # 1시간 캐시
def load_archive_manager(channel_root, dm_root):
    user_mapping = UserMapping(mapping_file=user_mapping_file)
    manager = SlackArchiveManager(channel_root=channel_root, dm_root=dm_root, user_mapping=user_mapping)
    manager.load_channels()
    manager.load_dms()
    return manager

# ================================
# Streamlit UI 구현
# ================================

st.title("Slack 아카이브 조회 앱 (Streamlit)")

# Hydra 설정에서 불러온 경로 사용
archive_manager = load_archive_manager(channel_root_path, dm_root_path)

# 사이드바: 메뉴 선택
menu_option = st.sidebar.radio(
    "메뉴 선택", 
    options=["DM 보기", "채널 보기", "검색", "사용자 매핑 업데이트"]  # DM을 첫번째로
)

# 1. 속도 개선을 위한 캐시 최적화
@st.cache_data(ttl=3600*24, show_spinner=False)  # 24시간 캐시
def load_messages_for_conversation(_conv):  # 언더스코어 추가
    """개별 대화의 메시지를 캐싱"""
    return _conv.messages

@st.cache_data(ttl=3600*24, show_spinner=False)
def get_available_years(_messages):  # 언더스코어 추가
    """메시지에서 사용 가능한 연도 추출"""
    return sorted(set(msg.get_datetime().year for msg in _messages))

# 2. 기간 필터 단순화
def render_period_filter(messages):
    """기간 필터"""
    if not messages:
        return []
    
    # 전체 기간 표시
    dates = [msg.get_datetime().date() for msg in messages]
    min_date = min(dates)
    max_date = max(dates)
    st.sidebar.info(f"전체 기간: {min_date.year}-{min_date.month} ~ {max_date.year}-{max_date.month}")
    
    st.sidebar.write("### 기간 필터")
    period_type = st.sidebar.selectbox(
        "기간 선택",
        options=["전체", "연도별", "월별", "분기별", "사용자 정의"],
        key="period_type"
    )

    filtered_messages = messages
    period_value = None
    start_date = None
    end_date = None

    if period_type == "연도별":
        years = sorted(list(set(msg.get_datetime().year for msg in messages)), reverse=True)
        if years:
            selected_year = st.sidebar.selectbox("연도 선택", options=years, key="selected_year")
            period_value = selected_year
            filtered_messages = filter_messages_by_period(messages, "year", period_value)
    elif period_type == "월별":
        months = sorted(list(set((msg.get_datetime().year, msg.get_datetime().month) for msg in messages)), reverse=True)
        month_options = [f"{y}년 {m}월" for y, m in months]
        if month_options:
            selected_month_str = st.sidebar.selectbox("월 선택", options=month_options, key="selected_month")
            selected_year, selected_month = int(selected_month_str.split('년')[0]), int(selected_month_str.split('년')[1].replace('월', '').strip())
            period_value = (selected_year, selected_month)
            filtered_messages = filter_messages_by_period(messages, "month", period_value)
    elif period_type == "분기별":
        quarters = sorted(list(set((msg.get_datetime().year, (msg.get_datetime().month - 1) // 3 + 1) for msg in messages)), reverse=True)
        quarter_options = [f"{y}년 {q}분기" for y, q in quarters]
        if quarter_options:
            selected_quarter_str = st.sidebar.selectbox("분기 선택", options=quarter_options, key="selected_quarter")
            selected_year, selected_quarter = int(selected_quarter_str.split('년')[0]), int(selected_quarter_str.split('년')[1].replace('분기', '').strip())
            period_value = (selected_year, selected_quarter)
            filtered_messages = filter_messages_by_period(messages, "quarter", period_value)
    elif period_type == "사용자 정의":
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input("시작일", value=min_date, key="custom_start_date")
        with col2:
            end_date = st.date_input("종료일", value=max_date, key="custom_end_date")
        filtered_messages = filter_messages_by_period(messages, "custom", None, start_date, end_date)
    
    return filtered_messages

# --------------------
# 채널 보기 페이지
if menu_option == "채널 보기":
    st.header("채널 보기")
    channel_names = archive_manager.get_channel_names()
    if not channel_names:
        st.error("채널을 찾을 수 없습니다.")
    else:
        selected_channel = st.sidebar.selectbox("채널 선택", options=channel_names)
        conv = archive_manager.channels.get(selected_channel)
        
        # 제목과 내보내기 버튼을 나란히 배치
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(f"채널: {selected_channel}")
        with col2:
            if st.button("💾 대화 내보내기"):
                file_path = export_conversation_to_txt(
                    conv, 
                    archive_manager.user_mapping,
                    f"channel_{selected_channel}"
                )
                with open(file_path, "r", encoding="utf-8") as f:
                    st.download_button(
                        "📥 TXT 파일 다운로드",
                        f,
                        file_name=f"{selected_channel}_대화.txt",
                        mime="text/plain"
                    )
        
        # 메시지 표시
        filtered_messages = render_period_filter(conv.messages)
        for msg in filtered_messages:
            time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
            display_name = archive_manager.user_mapping.get_name(msg.user_id)
            st.write(f"[{time_str}] **{display_name}**: {msg.text}")
            # 스레드 메시지 표시 (msg.replies 사용)
            if msg.replies:
                with st.expander(f"스레드 보기 ({len(msg.replies)}개 답글)"):
                    for t_msg in sorted(msg.replies, key=lambda x: x.ts):
                        t_time = t_msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                        t_display = archive_manager.user_mapping.get_name(t_msg.user_id)
                        st.write(f"[{t_time}] **{t_display}**: {t_msg.text}")

# --------------------
# DM 보기 페이지
elif menu_option == "DM 보기":
    st.header("DM 보기")
    dm_names = archive_manager.get_dm_names()
    
    if not dm_names:
        st.error("DM 대화를 찾을 수 없습니다.")
    else:
        st.sidebar.write("### DM 목록")
        
        # 표시용 이름과 실제 키를 매핑
        display_to_key = {}
        for name in dm_names:
            if name.startswith('C'):  # 그룹 DM인 경우
                display_name = archive_manager.dm_mapping.get_name(name)
            else:  # 1:1 DM인 경우
                display_name = name.split('_')[0] if '_' in name else name
            display_to_key[display_name] = name
        
        # 정렬된 표시 이름 목록
        display_names = sorted(display_to_key.keys())
        
        # DM 선택 UI
        selected_display = st.sidebar.selectbox(
            "대화 선택",
            options=display_names,
            key="dm_select",
            format_func=lambda x: f"👥 {x}"  # 이모지 추가
        )
        
        # 선택된 표시 이름에 해당하는 실제 키로 변환
        selected_key = display_to_key[selected_display]
        
        # 제목과 내보내기 버튼을 상단에 배치
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(f"DM 대화: {selected_display}")
        with col2:
            if st.button("💾 대화 내보내기"):
                file_path = export_conversation_to_txt(
                    archive_manager.dms.get(selected_key),
                    archive_manager.user_mapping,
                    f"dm_{selected_key}"
                )
                with open(file_path, "r", encoding="utf-8") as f:
                    st.download_button(
                        "📥 TXT 파일 다운로드",
                        f,
                        file_name=f"{selected_display}_대화.txt",
                        mime="text/plain"
                    )
        
        # 보기 모드 선택
        view_mode = st.radio("보기 모드", ["파싱된 메시지"])
        
        try:
            if view_mode == "파싱된 메시지":
                if archive_manager.dms.get(selected_key) and archive_manager.dms.get(selected_key).messages:
                    # 기간 필터 UI 추가
                    filtered_messages = render_period_filter(archive_manager.dms.get(selected_key).messages)
                    
                    st.write(f"### 메시지 ({len(filtered_messages)}개)")
                    for msg in filtered_messages:
                        time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                        display_name = archive_manager.user_mapping.get_name(msg.user_id)
                        st.write(f"[{time_str}] **{display_name}**: {msg.text}")
                        # 스레드 메시지 표시 (msg.replies 사용)
                        if msg.replies:
                            with st.expander(f"스레드 보기 ({len(msg.replies)}개 답글)"):
                                for t_msg in sorted(msg.replies, key=lambda x: x.ts):
                                    t_time = t_msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                                    t_display = archive_manager.user_mapping.get_name(t_msg.user_id)
                                    st.write(f"[{t_time}] **{t_display}**: {t_msg.text}")
                else:
                    st.info("파싱된 메시지가 없습니다.")
                
        except Exception as e:
            st.error(f"파일 읽기 오류: {str(e)}")

# --------------------
# 검색 페이지 (채널/DM 선택 후 검색)
elif menu_option == "검색":
    st.header("메시지 검색")
    search_source = st.sidebar.radio("대상 선택", options=["채널", "DM"])
    keyword = st.text_input("검색어 입력")
    if search_source == "채널":
        conv_names = archive_manager.get_channel_names()
        conv_dict = archive_manager.channels
    else:
        conv_names = archive_manager.get_dm_names()
        conv_dict = archive_manager.dms
    if not conv_names:
        st.error(f"{search_source} 대화를 찾을 수 없습니다.")
    else:
        selected_conv = st.selectbox(f"{search_source} 선택", options=conv_names, key="search_conv")
        conv = conv_dict.get(selected_conv)
        if keyword:
            results = conv.search_messages(keyword)
            filtered_results = render_period_filter(results) # Changed from render_simplified_period_filter
            st.subheader(f"'{keyword}' 검색 결과 ({len(filtered_results)}건)")
            for msg in filtered_results:
                time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                display_name = archive_manager.user_mapping.get_name(msg.user_id)
                st.write(f"[{time_str}] **{display_name}**: {msg.text}")

# --------------------
# 사용자 매핑 업데이트 페이지
elif menu_option == "사용자 매핑 업데이트":
    tab1, tab2 = st.tabs(["사용자 ID 매핑", "DM 이름 매핑"])
    
    with tab1:
        st.header("사용자 ID 매핑")
        
        # 사용자 통계 수집
        archive_manager.user_mapping.collect_user_stats(
            archive_manager.channels,
            archive_manager.dms
        )
        
        # 전체 사용자 ID 목록 표시
        all_user_ids = archive_manager.user_mapping.user_stats.keys()
        
        # 사용자 통계를 포함한 데이터프레임 생성
        mapping_data = []
        for uid in all_user_ids:
            stats = archive_manager.user_mapping.get_user_stats(uid)
            current_name = archive_manager.user_mapping.get_name(uid)
            
            mapping_data.append({
                "User ID": uid,
                "현재 매핑된 이름": current_name if current_name != uid else "-",
                "총 메시지 수": stats['total_messages'],
                "활동 채널 수": stats['channel_count'],
                "DM 대화 수": stats['dm_count']
            })
        
        df = pd.DataFrame(mapping_data)
        st.dataframe(df)
        
        # 사용자 상세 정보와 매핑 업데이트
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # 사용자 상세 정보 표시
            selected_uid = st.selectbox(
                "사용자 선택",
                options=all_user_ids,
                format_func=lambda x: f"{x} ({archive_manager.user_mapping.get_name(x)})",
                key="user_select_tab1"
            )
            
            if selected_uid:
                stats = archive_manager.user_mapping.get_user_stats(selected_uid)
                st.write("### 사용자 상세 정보")
                st.write(f"- 총 메시지 수: {stats['total_messages']}")
                st.write(f"- 활동 채널: {', '.join(stats['channels'])}")
                st.write(f"- DM 대화: {', '.join(stats['dms'])}")
        
        with col2:
            # 매핑 업데이트 폼
            st.write("### 이름 매핑 업데이트")
            with st.form("update_mapping_form"):
                current_name = archive_manager.user_mapping.get_name(selected_uid)
                new_name = st.text_input("새로운 이름", 
                                       value=current_name if current_name != selected_uid else "")
                
                submitted = st.form_submit_button("매핑 업데이트")
                if submitted and new_name:
                    archive_manager.user_mapping.update_mapping(selected_uid, new_name)
                    st.success(f"매핑 업데이트 완료: {selected_uid} → {new_name}")
                    st.rerun()  # experimental_rerun 대신 rerun 사용

    with tab2:
        st.header("DM 이름 매핑")
        
        # DM ID 목록 (C로 시작하는 그룹 DM만)
        dm_ids = [name for name in archive_manager.get_dm_names() 
                 if name.startswith('C')]
        
        # DM 매핑 테이블 표시
        dm_mapping_data = []
        for dm_id in dm_ids:
            conv = archive_manager.dms.get(dm_id)
            message_count = len(conv.messages) if conv else 0
            current_name = archive_manager.dm_mapping.get_name(dm_id)
            
            # 참여자 목록 추출
            participants = set()
            if conv:
                for msg in conv.messages:
                    participants.add(archive_manager.user_mapping.get_name(msg.user_id))
            
            dm_mapping_data.append({
                "DM ID": dm_id,
                "현재 이름": current_name if current_name != dm_id else "-",
                "메시지 수": message_count,
                "참여자": ", ".join(sorted(participants))
            })
        
        df_dm = pd.DataFrame(dm_mapping_data)
        st.dataframe(df_dm)
        
        # DM 매핑 업데이트 폼
        with st.form("dm_mapping_form"):
            col1, col2 = st.columns(2)
            with col1:
                selected_dm = st.selectbox(
                    "업데이트할 DM",
                    options=dm_ids,
                    format_func=lambda x: f"{x} (현재: {archive_manager.dm_mapping.get_name(x)})",
                    key="dm_select_tab2"
                )
            with col2:
                new_dm_name = st.text_input("새로운 DM 이름")
            
            if st.form_submit_button("DM 이름 업데이트"):
                if new_dm_name:
                    archive_manager.dm_mapping.update_mapping(selected_dm, new_dm_name)
                    st.success(f"DM 이름 업데이트 완료: {selected_dm} → {new_dm_name}")
                    st.rerun()