import os
import glob
import json
import datetime
from flask import Flask, render_template_string, request, redirect, url_for

# --- Data Models ---

class Message:
    def __init__(self, ts, user_id, text, thread_ts=None):
        self.ts = float(ts)
        self.user_id = user_id
        self.text = text
        self.thread_ts = thread_ts  # Optional: for threaded messages

    def get_datetime(self):
        return datetime.datetime.fromtimestamp(self.ts)

class Channel:
    def __init__(self, name):
        self.name = name
        self.messages = []  # List of Message objects

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
    def __init__(self, archive_root, dm_root=None, user_mapping=None):
        self.archive_root = archive_root
        self.dm_root = dm_root
        self.channels = {}  # key: channel name, value: Channel object
        self.dms = {}      # key: dm name, value: Channel object
        self.user_mapping = user_mapping or UserMapping()

    def load_channels(self):
        for channel_folder in os.listdir(self.archive_root):
            channel_path = os.path.join(self.archive_root, channel_folder)
            if os.path.isdir(channel_path):
                channel = Channel(channel_folder)
                for file in glob.glob(os.path.join(channel_path, '*.json')):
                    with open(file, 'r', encoding='utf-8') as f:
                        try:
                            messages_data = json.load(f)
                        except json.JSONDecodeError as e:
                            print(f"Error parsing {file}: {e}")
                            continue
                        for m in messages_data:
                            ts = m.get('ts')
                            user_id = m.get('user')
                            text = m.get('text', '')
                            thread_ts = m.get('thread_ts')
                            if ts and user_id:
                                message = Message(ts, user_id, text, thread_ts)
                                channel.add_message(message)
                channel.sort_messages()
                self.channels[channel_folder] = channel

    def load_dms(self):
        """DM 메시지 로드"""
        if not self.dm_root or not os.path.isdir(self.dm_root):
            print(f"DM 폴더를 찾을 수 없습니다: {self.dm_root}")
            return
        
        for file_path in glob.glob(os.path.join(self.dm_root, '*.json')):
            file_name = os.path.basename(file_path)
            name_part, _ = os.path.splitext(file_name)
            
            # 1:1 DM인 경우 파일명에 "_"가 포함됨
            if "_" in name_part:
                conv_name = name_part.split("_")[0]
                conv_type = "dm_1to1"
            else:
                conv_name = name_part
                conv_type = "dm_group"
                
            channel = Channel(f"{conv_type}:{conv_name}")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    messages_data = json.load(f)
                except json.JSONDecodeError as e:
                    print(f"Error parsing {file_path}: {e}")
                    continue
                
                for m in messages_data:
                    ts = m.get('ts')
                    user_id = m.get('user')
                    text = m.get('text', '')
                    thread_ts = m.get('thread_ts')
                    if ts and user_id:
                        message = Message(ts, user_id, text, thread_ts)
                        channel.add_message(message)
            
            channel.sort_messages()
            self.dms[channel.name] = channel

    def get_dm_names(self):
        """DM 대화 목록 반환"""
        return sorted(self.dms.keys())

    def get_default_channel(self):
        """Return the alphabetically first channel name (if available)."""
        if self.channels:
            return sorted(self.channels.keys())[0]
        return None

# --- Flask Web App ---

app = Flask(__name__)

# Set paths to the folders where your Slack JSON files are stored
archive_root_path = './slack_exporter/channels'  # 채널 폴더 경로
dm_root_path = './slack_exporter/dms'           # DM 폴더 경로

archive_manager = SlackArchiveManager(
    archive_root=archive_root_path,
    dm_root=dm_root_path
)
archive_manager.load_channels()
archive_manager.load_dms()

# Home route: redirect to the default channel
@app.route('/')
def home():
    default_channel = archive_manager.get_default_channel()
    if default_channel:
        return redirect(url_for('display_channel', channel_name=default_channel))
    return "No channels found.", 404

# Route: Display a channel's messages
@app.route('/channel/<channel_name>')
def display_channel(channel_name):
    channel = archive_manager.channels.get(channel_name)
    if not channel:
        return f"Channel '{channel_name}' not found.", 404
    template = """
    <div style="display: flex;">
        <!-- 채널 목록 사이드바 -->
        <div style="width: 200px; padding: 10px; background-color: #f5f5f5;">
            <h2>채널 목록</h2>
            <ul style="list-style-type: none; padding: 0;">
                {% for ch_name in archive_manager.channels.keys()|sort %}
                    <li style="margin: 5px 0;">
                        <a href="{{ url_for('display_channel', channel_name=ch_name) }}"
                           style="{% if ch_name == channel.name %}font-weight: bold;{% endif %}">
                            #{{ ch_name }}
                        </a>
                    </li>
                {% endfor %}
            </ul>
        </div>
        <!-- 메인 컨텐츠 -->
        <div style="flex-grow: 1; padding: 20px;">
            <h1>Channel: {{ channel.name }}</h1>
            <form action="{{ url_for('search_channel', channel_name=channel.name) }}" method="get">
                <input type="text" name="q" placeholder="Search messages">
                <button type="submit">Search</button>
            </form>
            <ul>
                {% for msg in channel.messages %}
                    <li>
                        [{{ msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S') }}]
                        <strong>{{ user_mapping.get_name(msg.user_id) }}</strong>:
                        {{ msg.text }}
                        {% if msg.thread_ts %}
                            <a href="{{ url_for('view_thread', thread_ts=msg.thread_ts) }}">View Thread</a>
                        {% endif %}
                    </li>
                {% endfor %}
            </ul>
            <a href="{{ url_for('update_mapping') }}">Update User Mapping</a>
        </div>
    </div>
    """
    return render_template_string(template, 
                                channel=channel, 
                                user_mapping=archive_manager.user_mapping,
                                archive_manager=archive_manager)

# Route: Search messages within a channel
@app.route('/search/<channel_name>')
def search_channel(channel_name):
    keyword = request.args.get('q', '')
    channel = archive_manager.channels.get(channel_name)
    if not channel:
        return f"Channel '{channel_name}' not found.", 404
    results = channel.search_messages(keyword)
    template = """
    <div style="display: flex;">
        <!-- 채널 목록 사이드바 -->
        <div style="width: 200px; padding: 10px; background-color: #f5f5f5;">
            <h2>채널 목록</h2>
            <ul style="list-style-type: none; padding: 0;">
                {% for ch_name in archive_manager.channels.keys()|sort %}
                    <li style="margin: 5px 0;">
                        <a href="{{ url_for('display_channel', channel_name=ch_name) }}"
                           style="{% if ch_name == channel.name %}font-weight: bold;{% endif %}">
                            #{{ ch_name }}
                        </a>
                    </li>
                {% endfor %}
            </ul>
        </div>
        <!-- 메인 컨텐츠 -->
        <div style="flex-grow: 1; padding: 20px;">
            <h1>Search Results in {{ channel.name }} for '{{ keyword }}'</h1>
            <ul>
                {% for msg in results %}
                    <li>
                        [{{ msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S') }}]
                        <strong>{{ user_mapping.get_name(msg.user_id) }}</strong>:
                        {{ msg.text }}
                    </li>
                {% endfor %}
            </ul>
            <a href="{{ url_for('display_channel', channel_name=channel.name) }}">Back to Channel</a>
        </div>
    </div>
    """
    return render_template_string(template, 
                                channel=channel, 
                                results=results,
                                keyword=keyword, 
                                user_mapping=archive_manager.user_mapping,
                                archive_manager=archive_manager)

# Route: View threaded messages (basic implementation)
@app.route('/thread/<thread_ts>')
def view_thread(thread_ts):
    thread_messages = []
    # Look for messages with the given thread_ts or where the message ts equals thread_ts
    for channel in archive_manager.channels.values():
        for msg in channel.messages:
            if msg.thread_ts == thread_ts or msg.ts == float(thread_ts):
                thread_messages.append(msg)
    if not thread_messages:
        return f"No thread found for {thread_ts}", 404
    thread_messages.sort(key=lambda msg: msg.ts)
    default_channel = archive_manager.get_default_channel() or ""
    template = """
    <h1>Thread: {{ thread_ts }}</h1>
    <ul>
      {% for msg in thread_messages %}
        <li>
          [{{ msg.get_datetime().strftime('%Y-%m-%d %H:%M:%S') }}]
          <strong>{{ user_mapping.get_name(msg.user_id) }}</strong>:
          {{ msg.text }}
        </li>
      {% endfor %}
    </ul>
    <a href="{{ url_for('display_channel', channel_name=default_channel) }}">Back to Channel</a>
    """
    return render_template_string(template, thread_ts=thread_ts,
                                  thread_messages=thread_messages,
                                  user_mapping=archive_manager.user_mapping,
                                  default_channel=default_channel)

# Route: Update user mapping persistently
@app.route('/update_mapping', methods=['GET', 'POST'])
def update_mapping():
    message = ""
    if request.method == 'POST':
        user_id = request.form['user_id']
        real_name = request.form['real_name']
        archive_manager.user_mapping.update_mapping(user_id, real_name)
        message = f"Updated mapping for {user_id}."
    default_channel = archive_manager.get_default_channel() or ""
    template = """
    <h1>Update User Mapping</h1>
    <p>{{ message }}</p>
    <form method="post">
      <label>User ID: <input type="text" name="user_id"></label><br>
      <label>Real Name: <input type="text" name="real_name"></label><br>
      <button type="submit">Update</button>
    </form>
    <h2>Current Mapping</h2>
    <ul>
      {% for uid, name in mapping.items() %}
        <li>{{ uid }} : {{ name }}</li>
      {% endfor %}
    </ul>
    <a href="{{ url_for('display_channel', channel_name=default_channel) }}">Back to Channel</a>
    """
    return render_template_string(template, mapping=archive_manager.user_mapping.mapping,
                                  message=message, default_channel=default_channel)

# --- Run the Flask App ---
if __name__ == '__main__':
    app.run(debug=True)