# Slack 아카이브 조회 및 관리 앱

이 프로젝트는 Slack 워크스페이스에서 내보낸 데이터를 로컬에서 조회하고 관리하기 위한 Streamlit 기반의 웹 애플리케이션입니다. 채널 및 DM 대화를 쉽게 탐색하고, 사용자 ID를 실제 이름으로 매핑하며, 대화 내용을 TXT 파일로 내보낼 수 있습니다. 특히, 대화 스레드 메시지를 포함하여 전체 대화 흐름을 파악할 수 있도록 개선되었습니다.

## 기능 개요

-   **Slack 데이터 로드**: Slack 워크스페이스에서 내보낸 JSON 데이터를 로드하여 채널 및 DM 대화를 표시합니다.
-   **대화 탐색**: 채널 및 DM 목록을 통해 원하는 대화를 선택하여 내용을 조회합니다.
-   **스레드 메시지 표시**: 대화 내 스레드 메시지를 메인 메시지 아래에 확장 가능한 형태로 표시하여 대화의 맥락을 파악할 수 있습니다.
-   **사용자 ID 매핑**: Slack 사용자 ID(예: U12345)를 실제 사용자 이름으로 매핑하여 가독성을 높입니다. 매핑 정보는 `user_mapping.json` 파일에 저장됩니다.
-   **DM 이름 매핑**: 그룹 DM ID(예: C12345)를 식별하기 쉬운 이름으로 매핑할 수 있습니다.
-   **대화 내보내기**: 선택한 대화 내용을 TXT 파일로 내보낼 수 있습니다.
-   **메시지 검색**: 특정 키워드를 포함하는 메시지를 검색합니다. 이제 검색 결과에도 연도별, 월별, 분기별, 사용자 정의 기간 필터링이 적용됩니다.
-   **기간별 필터링**: 메시지를 연도별 또는 사용자 정의 기간별로 필터링하여 조회할 수 있습니다.
-   **Hydra 설정 관리**: `configs/` 디렉토리의 YAML 파일을 통해 데이터 경로 및 기타 설정을 유연하게 관리합니다.

## 프로젝트 구조

```
test_slack/
├── configs/                  # Hydra 설정 파일
│   └── config.yaml           # 메인 설정 파일
├── data/                     # Slack 내보내기 데이터 및 매핑 파일
│   ├── channels/             # 채널 대화 JSON 파일들이 있는 폴더
│   │   └── #channel_name/    # 각 채널 폴더
│   │       └── YYYY-MM-DD.json # 날짜별 메시지 JSON 파일
│   ├── dms/                  # DM 대화 JSON 파일들이 있는 폴더
│   │   └── DM_ID.json        # 각 DM 대화 JSON 파일
│   ├── dm_mapping.json       # DM ID와 표시 이름 매핑 정보
│   └── user_mapping.json     # 사용자 ID와 실제 이름 매핑 정보
├── exports/                  # 내보낸 대화 TXT 파일들이 저장될 폴더
├── main.py                   # Streamlit 앱의 메인 스크립트
├── data_models.py            # 데이터 모델 및 Slack 아카이브 관리 로직
├── .gitignore                # Git 버전 관리에서 제외할 파일/폴더 설정
└── environment.yml           # Conda 환경 설정 파일
```

**참고**: `data/` 및 `exports/` 폴더는 Slack 데이터와 내보낸 파일을 포함하므로, `.gitignore`에 추가하여 버전 관리에서 제외하는 것을 권장합니다. 민감한 정보가 포함될 수 있으며, 파일 크기가 클 수 있습니다.

## 설치 및 실행 방법

### 1. Conda 환경 설정

이 프로젝트는 Conda를 사용하여 환경을 관리합니다.

1.  **프로젝트 디렉토리로 이동**:
    ```bash
    cd /Users/joonpark/Documents/dev/test_slack
    ```

2.  **Conda 환경 생성**:
    ```bash
    conda env create -f environment.yml
    ```

3.  **환경 활성화**:
    ```bash
    conda activate test-slack-env
    ```

### 2. Slack 데이터 준비

Slack 워크스페이스에서 데이터를 내보내고 `data/` 디렉토리 구조에 맞게 배치해야 합니다.

1.  **Slack 데이터 내보내기**: Slack 워크스페이스 설정에서 "데이터 내보내기" 기능을 사용하여 워크스페이스 데이터를 다운로드합니다. (일반적으로 `zip` 파일 형태로 제공됩니다.)
2.  **데이터 압축 해제**: 다운로드한 `zip` 파일의 압축을 해제합니다.
3.  **데이터 배치**: 압축 해제된 폴더 내의 `channels/` 및 `dms/` 폴더를 이 프로젝트의 `data/` 디렉토리 아래로 복사합니다.
    *   예시: `test_slack/data/channels/` 및 `test_slack/data/dms/`

### 3. 설정 파일 (`configs/config.yaml`) 준비

`configs/` 디렉토리에 `config.yaml` 파일을 생성하고, Slack 데이터 경로를 지정합니다.

```yaml
# configs/config.yaml
paths:
  channel_root: "./data/channels"
  dm_root: "./data/dms"
  user_mapping_file: "./data/user_mapping.json"
```

### 4. 앱 실행

Conda 환경이 활성화된 상태에서 다음 명령어를 실행하여 Streamlit 앱을 시작합니다.

```bash
streamlit run main.py
```

앱이 웹 브라우저에서 열리며 Slack 아카이브를 탐색할 수 있습니다.

## 스레드 메시지 처리 상세

Slack 내보내기 데이터에서 스레드 메시지는 메인 메시지 객체 내의 `replies` 필드에 포함되어 있습니다. 본 앱은 이 `replies` 필드를 파싱하여 스레드 답글을 로드하고 표시합니다.

-   **`Message` 클래스**: `replies` 속성을 추가하여 스레드 답글 `Message` 객체 리스트를 저장합니다.
-   **`parse_channel_message`, `parse_dm_message`**: 원본 Slack JSON 메시지에서 `replies` 필드를 재귀적으로 파싱하여 `Message` 객체로 변환하고, 메인 메시지의 `replies` 속성에 할당합니다.
-   **`export_conversation_to_txt`**: 메인 메시지에 `replies`가 있을 경우, `st.expander`를 사용하여 스레드 답글을 숨기거나 보이게 할 수 있도록 UI를 구성합니다. 내보내기 시에는 스레드 답글도 계층적으로 포함됩니다.

**주의사항**:
만약 사용하시는 Slack 내보내기 데이터의 스레드 구조가 `replies` 필드에 직접 포함되지 않고 별도의 파일(예: `thread_ts`를 이름으로 하는 폴더 내의 `replies.json`)로 저장되는 경우, 현재 로딩 로직(`SlackArchiveManager.load_channels`, `load_dms`)은 해당 스레드 답글을 자동으로 로드하지 못할 수 있습니다. 이 경우, `SlackArchiveManager`의 로딩 로직을 수정하여 별도의 스레드 답글 파일을 추가로 로드하도록 구현해야 합니다.