"""i18n: 言語設定とメッセージ定義"""

import os
import yaml

CONFIG_PATH = ".insighta.yaml"

MESSAGES = {
    "ja": {
        "broker": "SBI証券",
        "tz_offset": 9,
        "default_currency": "JPY",
        "onboarding_welcome": (
            "[bold]insighta portfolio importer[/bold]\n"
            "ステップに沿って進めていきます。"
        ),
        "steps": [
            ("1", "データ準備", "SBI証券からHTMLを保存して input/ に配置"),
            ("2", "パース＆検証", "HTML → CSV変換 → 保有数が合っているか照合"),
            ("3", "アップロード準備", "ポートフォリオ情報を入力 → upload用ファイル生成"),
            ("4", "アップロード", "Insighta APIへ送信"),
        ],
        "press_enter": "\nEnterキーで開始",
        "step1_title": "Step 1/4  データ準備",
        "step1_guide": (
            "SBI証券にログインし、以下の手順でHTMLを取得してください。\n"
            "\n"
            "  [bold]注文履歴[/bold] (必須)\n"
            "    1. 下記URLを開き、期間を指定して検索\n"
            "       https://member.c.sbisec.co.jp/foreign/refer/us/order-history\n"
            "    2. 表の行を右クリック → [bold]検証[/bold] (Inspect)\n"
            "    3. DevToolsで [cyan]<ul>[/cyan] 要素を探し、右クリック → [bold]Copy → Copy outerHTML[/bold]\n"
            "    4. テキストエディタに貼り付けて .html で保存\n"
            "    保存先: [cyan]input/history/[/cyan]  複数ファイル可\n"
            "\n"
            "  [bold]保有銘柄[/bold] (任意・検証用)\n"
            "    1. 下記URLを開く\n"
            "       https://member.c.sbisec.co.jp/foreign/account/summary\n"
            "    2. 画面右側の「保有銘柄一覧」を右クリック → [bold]検証[/bold] (Inspect)\n"
            "    3. DevToolsで [cyan]<div id=\"securities-holdings\">[/cyan] を探し、\n"
            "       右クリック → [bold]Copy → Copy outerHTML[/bold]\n"
            "    4. テキストエディタに貼り付けて .html で保存\n"
            "    保存先: [cyan]input/summary/[/cyan]\n"
            "\n"
            "  [bold]オプション[/bold]\n"
            "    ツール導入前に購入した銘柄がある場合、手動でCSVに登録できます。\n"
            "    → [cyan]templates/seed.csv[/cyan] を [cyan]input/seed/[/cyan] にコピーして編集\n"
            "\n"
            "    取引期間ごとに為替レートを指定したい場合、\n"
            "    → [cyan]templates/rate.csv[/cyan] を [cyan]input/rate.csv[/cyan] にコピーして編集\n"
        ),
        "step1_confirm": "ファイルの準備ができましたか？",
        "step2_title": "Step 2/4  パース＆検証",
        "file_detection": "ファイル検出",
        "history_found": "input/history/   [green]{n} files[/green]",
        "history_missing": "input/history/   [red]HTMLがありません[/red]",
        "summary_found": "input/summary/   [green]{n} files[/green]",
        "summary_missing": "input/summary/   [yellow]なし — 検証する場合は保有銘柄HTMLを配置してください[/yellow]",
        "seed_found": "input/seed/      [green]{n} files[/green]",
        "rate_found": "input/rate.csv   [green]あり[/green]",
        "history_required": "[red]input/history/ にHTMLを配置して、もう一度やり直してください。[/red]",
        "back_to_step1": "[dim]Step 1 に戻ります。[/dim]\n",
        "rate_prompt": "為替レート (固定値 / 空欄でスキップ)",
        "rate_file_auto": "[dim]為替レートは input/rate.csv を参照します。[/dim]",
        "rate_file_confirm": "input/rate.csv を使用しますか？",
        "verify_diff_warn": (
            "\n[yellow]保有数に差分があります。考えられる原因:[/yellow]\n"
            "  • 注文履歴HTMLの期間が足りない（古い取引が含まれていない）\n"
            "  • input/seed/ に初期保有分のCSVが不足している\n"
        ),
        "verify_choice": "どうしますか？",
        "back_to_step1_fix": "[dim]Step 1 に戻ります。ファイルを修正してください。[/dim]\n",
        "verify_confirm": "保有銘柄HTMLと照合しますか？",
        "summary_skip": "[dim]input/summary/ にHTMLがないため検証をスキップしました。[/dim]",
        "step3_confirm": "\nStep 3 (アップロード準備) へ進みますか？",
        "step3_title": "Step 3/4  アップロード準備",
        "step4_confirm": "\nStep 4 (アップロード) へ進みますか？",
        "step4_title": "Step 4/4  アップロード",
        "cred_prompt": "credentials.yaml のパス",
        "cred_confirm": "この設定でアップロードしますか？",
        "cred_missing": (
            "[red]{path} が見つかりません。[/red]\n"
            "\n"
            "  1. API Keyを発行:\n"
            "     https://insighta.cloud/ja/settings\n"
            "     → 開発者モードを ON → API Key発行\n"
            "\n"
            "  2. テンプレートをコピーしてAPI Keyを設定:\n"
            "     cp templates/credentials.yaml credentials.yaml\n"
        ),
        "all_done": "[bold green]🎉 全ステップ完了！[/bold green]",
        # prepare
        "prepare_name": "ポートフォリオ名",
        "prepare_desc": "説明",
        "prepare_currency": "通貨",
        "prepare_budget": "初期予算",
        "prepare_target_return": "目標リターン (%)",
        "prepare_target_date": "目標日 (YYYY-MM-DD)",
        "prepare_start_date": "開始日 (YYYY-MM-DD)",
        "prepare_history": "取引履歴CSVパス",
        "prepare_seed": "初期保有CSVパス (なければ空欄)",
        "prepare_rate": "為替レートCSVパス (なければ空欄)",
        "prepare_group": "同日の注文をまとめますか？",
        "prepare_items_header": "保有銘柄一覧",
        "prepare_items_prompt": "比率を入力 (例: SPY/0.2,QQQ/0.3 / 空欄でスキップ)",
        "prepare_group_note": "[dim]同じ日付+通貨の注文を1グループにまとめます。[/dim]",
        "prepare_result": "生成結果",
        "prepare_trades": "取引件数",
        "prepare_budget_count": "入出金",
        "prepare_dividend_count": "配当金",
        "prepare_groups": "注文グループ数",
        "prepare_grouping": "グルーピング",
        "prepare_grouping_date": "日付+通貨",
        "prepare_grouping_individual": "個別",
        "prepare_done": "{order} + {yaml} 生成完了",
        # resume
        "resume_history": "前回のパース結果 (output/history.csv) が見つかりました。再利用しますか？",
        "resume_prepare": "前回のアップロード準備ファイル (upload.yaml + order.csv) が見つかりました。再利用しますか？",
        "resume_reuse": "[dim]前回の結果を再利用します。[/dim]",
    },
    "ko": {
        "broker": "미래에셋증권",
        "tz_offset": 9,
        "default_currency": "KRW",
        "onboarding_welcome": (
            "[bold]insighta portfolio importer[/bold]\n"
            "단계별로 진행합니다."
        ),
        "steps": [
            ("1", "데이터 준비", "증권사에서 HTML을 저장하여 input/ 에 배치"),
            ("2", "파싱 & 검증", "HTML → CSV 변환 → 보유수량 대조"),
            ("3", "업로드 준비", "포트폴리오 정보 입력 → 업로드용 파일 생성"),
            ("4", "업로드", "Insighta API로 전송"),
        ],
        "press_enter": "\nEnter키로 시작",
        "step1_title": "Step 1/4  데이터 준비",
        "step1_guide": (
            "미래에셋증권에 로그인하여 아래 절차로 HTML을 가져오세요.\n"
            "\n"
            "  [bold]주문내역[/bold] (필수)\n"
            "    1. 해외주식 → 주문내역 페이지를 열고 기간을 지정하여 검색\n"
            "    2. 표의 행을 우클릭 → [bold]검사[/bold] (Inspect)\n"
            "    3. DevTools에서 해당 요소를 찾아 우클릭 → [bold]Copy → Copy outerHTML[/bold]\n"
            "    4. 텍스트 에디터에 붙여넣고 .html 로 저장\n"
            "    저장 위치: [cyan]input/history/[/cyan]  여러 파일 가능\n"
            "\n"
            "  [bold]보유종목[/bold] (선택 · 검증용)\n"
            "    1. 해외주식 → 잔고 페이지를 열기\n"
            "    2. 보유종목 영역을 우클릭 → [bold]검사[/bold] (Inspect)\n"
            "    3. DevTools에서 해당 요소를 찾아 우클릭 → [bold]Copy → Copy outerHTML[/bold]\n"
            "    4. 텍스트 에디터에 붙여넣고 .html 로 저장\n"
            "    저장 위치: [cyan]input/summary/[/cyan]\n"
            "\n"
            "  [bold]옵션[/bold]\n"
            "    이 툴 도입 전에 매수한 종목이 있다면 수동으로 CSV에 등록할 수 있습니다.\n"
            "    → [cyan]templates/seed.csv[/cyan] 를 [cyan]input/seed/[/cyan] 에 복사하여 편집\n"
            "\n"
            "    거래 기간별 환율을 지정하고 싶다면,\n"
            "    → [cyan]templates/rate.csv[/cyan] 를 [cyan]input/rate.csv[/cyan] 에 복사하여 편집\n"
        ),
        "step1_confirm": "파일 준비가 되었나요?",
        "step2_title": "Step 2/4  파싱 & 검증",
        "file_detection": "파일 검출",
        "history_found": "input/history/   [green]{n} files[/green]",
        "history_missing": "input/history/   [red]HTML이 없습니다[/red]",
        "summary_found": "input/summary/   [green]{n} files[/green]",
        "summary_missing": "input/summary/   [yellow]없음 — 검증하려면 보유종목 HTML을 배치해주세요[/yellow]",
        "seed_found": "input/seed/      [green]{n} files[/green]",
        "rate_found": "input/rate.csv   [green]있음[/green]",
        "history_required": "[red]input/history/ 에 HTML을 배치한 후 다시 시도해주세요.[/red]",
        "back_to_step1": "[dim]Step 1 로 돌아갑니다.[/dim]\n",
        "rate_prompt": "환율 (고정값 / 빈칸으로 스킵)",
        "rate_file_auto": "[dim]환율은 input/rate.csv 를 참조합니다.[/dim]",
        "rate_file_confirm": "input/rate.csv 를 사용하시겠습니까?",
        "verify_diff_warn": (
            "\n[yellow]보유수량에 차이가 있습니다. 가능한 원인:[/yellow]\n"
            "  • 주문내역 HTML의 기간이 부족 (오래된 거래가 포함되지 않음)\n"
            "  • input/seed/ 에 초기 보유분 CSV가 부족\n"
        ),
        "verify_choice": "어떻게 하시겠습니까?",
        "back_to_step1_fix": "[dim]Step 1 로 돌아갑니다. 파일을 수정해주세요.[/dim]\n",
        "verify_confirm": "보유종목 HTML과 대조하시겠습니까?",
        "summary_skip": "[dim]input/summary/ 에 HTML이 없어 검증을 스킵했습니다.[/dim]",
        "step3_confirm": "\nStep 3 (업로드 준비) 으로 진행하시겠습니까?",
        "step3_title": "Step 3/4  업로드 준비",
        "step4_confirm": "\nStep 4 (업로드) 로 진행하시겠습니까?",
        "step4_title": "Step 4/4  업로드",
        "cred_prompt": "credentials.yaml 경로",
        "cred_confirm": "이 설정으로 업로드하시겠습니까?",
        "cred_missing": (
            "[red]{path} 를 찾을 수 없습니다.[/red]\n"
            "\n"
            "  1. API Key 발급:\n"
            "     https://insighta.cloud/ko/settings\n"
            "     → 개발자 모드 ON → API Key 발급\n"
            "\n"
            "  2. 템플릿을 복사하고 API Key를 설정:\n"
            "     cp templates/credentials.yaml credentials.yaml\n"
        ),
        "all_done": "[bold green]🎉 모든 단계 완료![/bold green]",
        # prepare
        "prepare_name": "포트폴리오 이름",
        "prepare_desc": "설명",
        "prepare_currency": "통화",
        "prepare_budget": "초기 예산",
        "prepare_target_return": "목표 수익률 (%)",
        "prepare_target_date": "목표일 (YYYY-MM-DD)",
        "prepare_start_date": "시작일 (YYYY-MM-DD)",
        "prepare_history": "거래내역 CSV 경로",
        "prepare_seed": "초기보유 CSV 경로 (없으면 빈칸)",
        "prepare_rate": "환율 CSV 경로 (없으면 빈칸)",
        "prepare_group": "같은 날 주문을 묶으시겠습니까?",
        "prepare_items_header": "보유 종목 목록",
        "prepare_items_prompt": "비율 입력 (예: SPY/0.2,QQQ/0.3 / 빈칸으로 스킵)",
        "prepare_group_note": "[dim]같은 날짜+통화의 주문을 1그룹으로 묶습니다.[/dim]",
        "prepare_result": "생성 결과",
        "prepare_trades": "거래 건수",
        "prepare_budget_count": "입출금",
        "prepare_dividend_count": "배당금",
        "prepare_groups": "주문 그룹 수",
        "prepare_grouping": "그루핑",
        "prepare_grouping_date": "날짜+통화",
        "prepare_grouping_individual": "개별",
        "prepare_done": "{order} + {yaml} 생성 완료",
        # resume
        "resume_history": "이전 파싱 결과 (output/history.csv) 가 있습니다. 재사용하시겠습니까?",
        "resume_prepare": "이전 업로드 준비 파일 (upload.yaml + order.csv) 이 있습니다. 재사용하시겠습니까?",
        "resume_reuse": "[dim]이전 결과를 재사용합니다.[/dim]",
    },
}


def load_locale() -> str | None:
    """保存済みlocaleを読み込む。未設定ならNone。"""
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("locale")


def save_locale(locale: str):
    """localeを保存する。"""
    data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data["locale"] = locale
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)


def msg(locale: str) -> dict:
    """指定localeのメッセージ辞書を返す。"""
    return MESSAGES.get(locale, MESSAGES["ja"])
