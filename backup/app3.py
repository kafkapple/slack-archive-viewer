import streamlit as st
import os
import glob
import json
import datetime

# ================================
# 데이터 모델 정의
# ================================

class Message:
    def __init__(self, ts, user_id, text, thread_ts=None):
        self.ts = float(ts)
        self.user_id = user_id
        self.text = text
        self.thread_ts = thread_ts  # 스레드 관련 값 (없으면 None)

    def get_datetime(self):
        return datetime.datetime.fromtimestamp(self.ts)

class Conversation:
    """
    채널과 DM 대화 모두를 표현하는 클래스.
    conv_type: "channel", "dm_1to1", "dm_group"
    """
    def __init__(self, name, conv_type="channel"):
        self.name = name
        self.conv_type = conv_type
        self.messages = []  # Message 객체 리스트

    def add_message(self, message):
        self.messages.append(message)

    def sort_messages(self):
        self.messages.sort(key=lambda msg: msg.ts)

    def search_messages(self, keyword):
        return [msg for msg in self.messages if keyword.lower() in msg.text.lower()]

class UserMapping:
    def __init__(self, mapping_file=os.path.join('db', 'user_mapping.json')):
        self.mapping_file = mapping_file
        self.mapping = {}
        os.makedirs(os.path.dirname(self.mapping_file), exist_ok=True)
        self.load_mapping()

    def update_mapping(self, user_id, actual_name):
        self.mapping[user_id] = actual_name
        self.save_mapping()

    def get_name(self, user_id):
        return self.mapping.get(user_id, user_id)

    def load_mapping(self):
        try:
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                self.mapping = json.load(f)
        except FileNotFoundError:
            self.mapping = {}

    def save_mapping(self):
        with open(self.mapping_file, 'w', encoding='utf-8') as f:
            json.dump(self.mapping, f, ensure_ascii=False, indent=2)

class SlackArchiveManager:
    """
    채널과 DM 대화 모두를 로드하는 관리자 클래스.
    - channels: 채널 폴더 (여러 하위 폴더)
    - dms: DM 폴더 내 각 대화 파일 (1:1, 그룹 DM 구분)
    """
    def __init__(self, channel_root, dm_root, user_mapping=None):
        self.channel_root = channel_root  # 채널 JSON 파일들이 있는 폴더 경로
        self.dm_root = dm_root            # DM JSON 파일들이 있는 폴더 경로
        self.channels = {}   # key: 채널 이름, value: Conversation 객체 (conv_type="channel")
        self.dms = {}        # key: 대화 제목, value: Conversation 객체 (conv_type="dm_1to1" 또는 "dm_group")
        self.user_mapping = user_mapping or UserMapping()

    def load_channels(self):
        if not os.path.isdir(self.channel_root):
            st.error(f"채널 폴더 경로를 찾을 수 없습니다: {self.channel_root}")
            return
        for channel_folder in os.listdir(self.channel_root):
            channel_path = os.path.join(self.channel_root, channel_folder)
            if os.path.isdir(channel_path):
                conv = Conversation(channel_folder, conv_type="channel")
                for file in glob.glob(os.path.join(channel_path, '*.json')):
                    with open(file, 'r', encoding='utf-8') as f:
                        try:
                            messages_data = json.load(f)
                        except json.JSONDecodeError as e:
                            st.error(f"파일 {file} 파싱 오류: {e}")
                            continue
                        for m in messages_data:
                            ts = m.get('ts')
                            user_id = m.get('user')
                            text = m.get('text', '')
                            thread_ts = m.get('thread_ts')
                            if ts and user_id:
                                msg = Message(ts, user_id, text, thread_ts)
                                conv.add_message(msg)
                conv.sort_messages()
                self.channels[channel_folder] = conv

    def load_dms(self):
        if not os.path.isdir(self.dm_root):
            st.error(f"DM 폴더 경로를 찾을 수 없습니다: {self.dm_root}")
            return
        for file_path in glob.glob(os.path.join(self.dm_root, '*.json')):
            file_name = os.path.basename(file_path)
            name_part, _ = os.path.splitext(file_name)
            # 1:1 DM의 경우 파일명에 "_"가 포함됨
            if "_" in name_part:
                conv_name = name_part.split("_")[0]
                conv_type = "dm_1to1"
            else:
                conv_name = name_part
                conv_type = "dm_group"
            conv = Conversation(conv_name, conv_type=conv_type)
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    messages_data = json.load(f)
                except json.JSONDecodeError as e:
                    st.error(f"파일 {file_path} 파싱 오류: {e}")
                    continue
                for m in messages_data:
                    ts = m.get('ts')
                    user_id = m.get('user')
                    text = m.get('text', '')
                    thread_ts = m.get('thread_ts')
                    if ts and user_id:
                        msg = Message(ts, user_id, text, thread_ts)
                        conv.add_message(msg)
            conv.sort_messages()
            key_name = f"{conv_type}:{conv_name}"
            self.dms[key_name] = conv

    def get_channel_names(self):
        return sorted(self.channels.keys())

    def get_dm_names(self):
        return sorted(self.dms.keys())

# ================================
# 유틸리티 함수
# ================================

def get_thread_messages(thread_ts, archive_manager, conv_source):
    """
    conv_source: "channel" 또는 "dm" 지정.
    해당 영역의 모든 대화에서 thread_ts에 해당하는 메시지 검색.
    """
    thread_messages = []
    if conv_source == "channel":
        conv_list = archive_manager.channels.values()
    else:
        conv_list = archive_manager.dms.values()
    for conv in conv_list:
        for msg in conv.messages:
            if msg.thread_ts == thread_ts or msg.ts == float(thread_ts):
                thread_messages.append(msg)
    thread_messages.sort(key=lambda msg: msg.ts)
    return thread_messages

def aggregate_user_ids(archive_manager):
    """채널과 DM 모든 대화에서 user id 집계"""
    user_ids = set()
    for conv in list(archive_manager.channels.values()) + list(archive_manager.dms.values()):
        for msg in conv.messages:
            user_ids.add(msg.user_id)
    return sorted(list(user_ids))

def filter_messages_by_period(_messages, period_type=None, period_value=None):
    """
    period_type: "year", "month", "quarter" 또는 None(전체)
    period_value: 해당 period에 해당하는 값 (예: 2022, 7, 2 등)
    """
    if period_type is None:
        return messages
    filtered = []
    for msg in messages:
        dt = msg.get_datetime()
        if period_type == "year" and dt.year != period_value:
            continue
        if period_type == "month" and dt.month != period_value:
            continue
        if period_type == "quarter":
            quarter = (dt.month - 1) // 3 + 1
            if quarter != period_value:
                continue
        filtered.append(msg)
    return filtered

# ================================
# 캐시: 아카이브 매니저 로드
# ================================

@st.cache_data(show_spinner=False)
def load_archive_manager(channel_root, dm_root):
    user_mapping = UserMapping()
    manager = SlackArchiveManager(channel_root=channel_root, dm_root=dm_root, user_mapping=user_mapping)
    manager.load_channels()
    manager.load_dms()
    return manager

# ================================
# Streamlit UI 구현
# ================================

st.title("Slack 아카이브 조회 앱 (Streamlit)")

# 경로 설정 (사용자 환경에 맞게 수정)
channel_root_path = "path/to/slack_archive"   # 채널 JSON 파일 폴더 경로
dm_root_path = "path/to/dm_archive"             # DM JSON 파일 폴더 경로

archive_manager = load_archive_manager(channel_root_path, dm_root_path)

# 사이드바: 메뉴 선택
menu_option = st.sidebar.radio("메뉴 선택", options=["채널 보기", "DM 보기", "검색", "사용자 매핑 업데이트"])

# --------------------
# 공통: 기간 필터 UI
def render_period_filter(messages):
    filter_type = st.sidebar.selectbox("기간 필터", options=["전체", "년도", "월", "분기"])
    if filter_type == "전체":
        return messages
    elif filter_type == "년도":
        years = sorted(set(msg.get_datetime().year for msg in messages))
        selected_year = st.sidebar.selectbox("년도 선택", years)
        return filter_messages_by_period(messages, period_type="year", period_value=selected_year)
    elif filter_type == "월":
        months = sorted(set(msg.get_datetime().month for msg in messages))
        selected_month = st.sidebar.selectbox("월 선택", months)
        return filter_messages_by_period(messages, period_type="month", period_value=selected_month)
    elif filter_type == "분기":
        quarters = sorted(set((msg.get_datetime().month - 1) // 3 + 1 for msg in messages))
        selected_quarter = st.sidebar.selectbox("분기 선택", quarters)
        return filter_messages_by_period(messages, period_type="quarter", period_value=selected_quarter)
    return messages

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
        st.subheader(f"채널: {selected_channel}")
        # 기간 필터 적용
        filtered_messages = render_period_filter(conv.messages)
        for msg in filtered_messages:
            time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
            display_name = archive_manager.user_mapping.get_name(msg.user_id)
            st.write(f"[{time_str}] **{display_name}**: {msg.text}")
            if msg.thread_ts:
                with st.expander("스레드 보기"):
                    thread_msgs = get_thread_messages(msg.thread_ts, archive_manager, conv_source="channel")
                    for t_msg in thread_msgs:
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
        selected_dm = st.sidebar.selectbox("DM 대화 선택", options=dm_names)
        conv = archive_manager.dms.get(selected_dm)
        st.subheader(f"DM 대화: {conv.name} ({conv.conv_type})")
        filtered_messages = render_period_filter(conv.messages)
        for msg in filtered_messages:
            time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
            display_name = archive_manager.user_mapping.get_name(msg.user_id)
            st.write(f"[{time_str}] **{display_name}**: {msg.text}")
            if msg.thread_ts:
                with st.expander("스레드 보기"):
                    thread_msgs = get_thread_messages(msg.thread_ts, archive_manager, conv_source="dm")
                    for t_msg in thread_msgs:
                        t_time = t_msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                        t_display = archive_manager.user_mapping.get_name(t_msg.user_id)
                        st.write(f"[{t_time}] **{t_display}**: {t_msg.text}")

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
        # 기간 필터는 검색보다는 전체에서 적용하는 것이 더 편할 수 있음.
        if keyword:
            results = conv.search_messages(keyword)
            # 선택한 대화 내의 결과에 대해서도 기간 필터를 적용할 수 있음
            filtered_results = render_period_filter(results)
            st.subheader(f"'{keyword}' 검색 결과 ({len(filtered_results)}건)")
            for msg in filtered_results:
                time_str = msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S')
                display_name = archive_manager.user_mapping.get_name(msg.user_id)
                st.write(f"[{time_str}] **{display_name}**: {msg.text}")

# --------------------
# 사용자 매핑 업데이트 페이지
elif menu_option == "사용자 매핑 업데이트":
    st.header("사용자 매핑 업데이트")
    st.write("전체 대화에서 나타난 user id 목록을 확인하고, 실제 이름을 할당하세요.")
    all_user_ids = aggregate_user_ids(archive_manager)
    st.write("### 전체 사용자 ID 목록")
    mapping_table = {uid: archive_manager.user_mapping.get_name(uid) for uid in all_user_ids}
    st.table(mapping_table)
    
    st.write("### 매핑 업데이트")
    with st.form("update_mapping_form"):
        user_id_input = st.selectbox("업데이트할 user id 선택", options=all_user_ids)
        real_name_input = st.text_input("실제 이름 입력")
        submitted = st.form_submit_button("업데이트")
        if submitted and real_name_input:
            archive_manager.user_mapping.update_mapping(user_id_input, real_name_input)
            st.success(f"{user_id_input}의 매핑이 '{real_name_input}'로 업데이트되었습니다.")
            st.experimental_rerun()