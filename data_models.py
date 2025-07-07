import datetime
import json
import os
import glob
from typing import List, Optional, Dict, Any

class Message:
    def __init__(self, ts, user_id, text, thread_ts=None, blocks=None, reactions=None, replies: Optional[List['Message']] = None):
        self.ts = float(ts)
        self.user_id = user_id
        self.text = text
        self.thread_ts = thread_ts
        self.blocks = blocks
        self.reactions = reactions
        self.replies = replies if replies is not None else []

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
        self.messages = []

    def add_message(self, message):
        self.messages.append(message)

    def sort_messages(self):
        self.messages.sort(key=lambda msg: msg.ts)

    def search_messages(self, keyword):
        return [msg for msg in self.messages if keyword.lower() in msg.text.lower()]

class UserMapping:
    def __init__(self, mapping_file):
        self.mapping_file = mapping_file
        self.mapping = self.load_mapping()
        self.user_stats = {} # 사용자 통계 저장

    def load_mapping(self):
        if os.path.exists(self.mapping_file):
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_mapping(self):
        with open(self.mapping_file, 'w', encoding='utf-8') as f:
            json.dump(self.mapping, f, ensure_ascii=False, indent=4)

    def get_name(self, user_id):
        return self.mapping.get(user_id, user_id)

    def update_mapping(self, user_id, new_name):
        self.mapping[user_id] = new_name
        self.save_mapping()

    def collect_user_stats(self, channels: Dict[str, 'Conversation'], dms: Dict[str, 'Conversation']):
        user_message_counts = {}
        user_channel_participation = {}
        user_dm_participation = {}

        # 채널 메시지 통계
        for channel_name, conv in channels.items():
            for msg in conv.messages:
                user_id = msg.user_id
                user_message_counts[user_id] = user_message_counts.get(user_id, 0) + 1
                user_channel_participation.setdefault(user_id, set()).add(channel_name)
                if msg.replies:
                    for reply_msg in msg.replies:
                        reply_user_id = reply_msg.user_id
                        user_message_counts[reply_user_id] = user_message_counts.get(reply_user_id, 0) + 1
                        user_channel_participation.setdefault(reply_user_id, set()).add(channel_name)

        # DM 메시지 통계
        for dm_name, conv in dms.items():
            for msg in conv.messages:
                user_id = msg.user_id
                user_message_counts[user_id] = user_message_counts.get(user_id, 0) + 1
                user_dm_participation.setdefault(user_id, set()).add(dm_name)
                if msg.replies:
                    for reply_msg in msg.replies:
                        reply_user_id = reply_msg.user_id
                        user_message_counts[reply_user_id] = user_message_counts.get(reply_user_id, 0) + 1
                        user_dm_participation.setdefault(reply_user_id, set()).add(dm_name)

        self.user_stats = {}
        all_user_ids = set(user_message_counts.keys()) | set(user_channel_participation.keys()) | set(user_dm_participation.keys())

        for user_id in all_user_ids:
            self.user_stats[user_id] = {
                'total_messages': user_message_counts.get(user_id, 0),
                'channels': sorted(list(user_channel_participation.get(user_id, set()))),
                'channel_count': len(user_channel_participation.get(user_id, set())),
                'dms': sorted(list(user_dm_participation.get(user_id, set()))),
                'dm_count': len(user_dm_participation.get(user_id, set()))
            }

    def get_user_stats(self, user_id):
        return self.user_stats.get(user_id, {
            'total_messages': 0,
            'channels': [],
            'channel_count': 0,
            'dms': [],
            'dm_count': 0
        })

class DMChannelMapping(UserMapping): # UserMapping을 상속받아 파일 로드/저장 기능 재활용
    def __init__(self, mapping_file):
        super().__init__(mapping_file)

class SlackArchiveManager:
    def __init__(self, channel_root, dm_root, user_mapping: UserMapping, dm_mapping: Optional['DMChannelMapping'] = None):
        self.channel_root = channel_root
        self.dm_root = dm_root
        self.user_mapping = user_mapping
        self.dm_mapping = dm_mapping if dm_mapping is not None else DMChannelMapping(os.path.join(os.path.dirname(user_mapping.mapping_file), "dm_mapping.json"))
        self.channels: Dict[str, Conversation] = {}
        self.dms: Dict[str, Conversation] = {}

    def _parse_message(self, msg_data: Dict[str, Any]) -> Optional[Message]:
        if 'ts' not in msg_data:
            return None

        replies = []
        if 'replies' in msg_data and isinstance(msg_data['replies'], list):
            for reply_data in msg_data['replies']:
                reply = self._parse_message(reply_data)
                if reply:
                    replies.append(reply)
        
        return Message(
            ts=msg_data['ts'],
            user_id=msg_data.get('user', 'UNKNOWN'),
            text=msg_data.get('text', ''),
            thread_ts=msg_data.get('thread_ts'),
            blocks=msg_data.get('blocks'),
            reactions=msg_data.get('reactions'),
            replies=replies
        )

    def load_channels(self):
        if not os.path.isdir(self.channel_root):
            print(f"경고: 채널 데이터 경로를 찾을 수 없습니다: {self.channel_root}")
            return

        for channel_dir in glob.glob(os.path.join(self.channel_root, '*')):
            if os.path.isdir(channel_dir):
                channel_name = os.path.basename(channel_dir)
                conv = Conversation(name=channel_name, conv_type="channel")
                for json_file in glob.glob(os.path.join(channel_dir, '*.json')):
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            messages_data = json.load(f)
                            for msg_data in messages_data:
                                message = self._parse_message(msg_data)
                                if message:
                                    conv.add_message(message)
                    except json.JSONDecodeError as e:
                        print(f"경고: {json_file} 파일 파싱 오류: {e}")
                    except Exception as e:
                        print(f"경고: {json_file} 파일 읽기 오류: {e}")
                conv.sort_messages()
                self.channels[channel_name] = conv

    def load_dms(self):
        if not os.path.isdir(self.dm_root):
            print(f"경고: DM 데이터 경로를 찾을 수 없습니다: {self.dm_root}")
            return

        for json_file in glob.glob(os.path.join(self.dm_root, '*.json')):
            dm_id = os.path.splitext(os.path.basename(json_file))[0]
            conv = Conversation(name=dm_id, conv_type="dm_group" if dm_id.startswith('C') else "dm_1to1")
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    messages_data = json.load(f)
                    for msg_data in messages_data:
                        message = self._parse_message(msg_data)
                        if message:
                            conv.add_message(message)
            except json.JSONDecodeError as e:
                print(f"경고: {json_file} 파일 파싱 오류: {e}")
            except Exception as e:
                print(f"경고: {json_file} 파일 읽기 오류: {e}")
            conv.sort_messages()
            self.dms[dm_id] = conv

    def get_channel_names(self):
        return sorted(list(self.channels.keys()))

    def get_dm_names(self):
        return sorted(list(self.dms.keys()))