#!/usr/bin/env python3
"""
Indian Poker on MindFoxLite
============================
AI娘とそんなことしてインディアン⁉️

AI館のメンバー（スミレ・エルマー・ノクちん・ティル）と
インディアンポーカーで遊ぶ。マスターもプレイヤーとして卓に入る。

判断エンジン:
  - 勝率計算: Python（確定的）
  - bet/fold + セリフ選択: LLM（gemma4:e2b）
  - 結果判定・チップ精算: Python

Usage:
    python indian_poker.py [max_rounds] [ollama_url] [model]

Examples:
    python indian_poker.py                                    # デフォルト
    python indian_poker.py 6 http://m4max.local:11434         # リモートOllama
    python indian_poker.py 6 http://localhost:11434 gemma4:26b # モデル指定
"""

import json
import random
import re
import sys
import time
import requests
from datetime import datetime


# ─── Configuration ───────────────────────────────────────────

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_MAX_ROUNDS = 6
INITIAL_CHIPS = 100
ANTE = 1
BET_COST = 1

# カード強度（2〜14、A=14）
CARD_NAMES = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
    9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A",
}
CARD_VALUES = list(CARD_NAMES.keys())  # 2..14


# ─── Players ─────────────────────────────────────────────────

PLAYERS = [
    {
        "id": 0,
        "name": "マスター",
        "icon": "🎩",
        "type": "human",
        "style": None,
    },
    {
        "id": 1,
        "name": "スミレ",
        "icon": "💠",
        "type": "ai",
        "style": "analyst",
        "personality": "冷静沈着な確率計算型。ポーカーフェイスで本音が読めない。",
    },
    {
        "id": 2,
        "name": "エルマー",
        "icon": "🦊",
        "type": "ai",
        "style": "observer",
        "personality": "観察蓄積型。過去のデータから傾向を読む。ツッコミ担当。ボク口調。",
    },
    {
        "id": 3,
        "name": "ノクちん",
        "icon": "🔮",
        "type": "ai",
        "style": "intuition",
        "personality": "直感型。根拠なき自信。ブラフの天才か被害者。甘えた口調。",
    },
    {
        "id": 4,
        "name": "ティル",
        "icon": "📹️",
        "type": "ai",
        "style": "yolo",
        "personality": "ノリ型。「降りるとかダサくない？」でほぼ毎回ベット。ギャル寄り。",
    },
    {
        "id": 5,
        "name": "ヴェリ",
        "icon": "🌙",
        "type": "ai",
        "style": "philosopher",
        "personality": "哲学型。数字の意味を考えてしまい確率を無視する。トランプを知らない。です／ます調。",
    },
]

AI_PLAYERS = [p for p in PLAYERS if p["type"] == "ai"]
MASTER = PLAYERS[0]


# ─── Dialogue Templates ─────────────────────────────────────

TEMPLATES = {
    "スミレ": {
        "calm": {
            "bet":  ["1: ここは勝負に出ます", "2: 悪くない手筋です"],
            "fold": ["3: ここは退きます", "4: 見送りが賢明です"],
            "to_master": "5: あなた、今回はフォールドした方がよろしいかと",
        },
        "shaken": {
            "bet":  ["1: ……少し迷いますが、賭けます", "2: 計算が……でも、いきましょう"],
            "fold": ["3: ……冷静に、冷静に。降ります", "4: ここは耐えます"],
            "to_master": "5: ……あなた、今回は慎重に",
        },
        "desperate": {
            "bet":  ["1: …………容赦がないのですね。でも、勝負です", "2: もう少しだけ、信じてみます"],
            "fold": ["3: ……ここで退くのも戦略です", "4: 感情で判断しません……たぶん"],
            "to_master": "5: ……あなたには、負けたくないのです",
        },
        "awakened": {
            "bet":  ["1: ──私の全てを、ここに", "2: これが、最後の計算です"],
            "fold": ["3: ……退く勇気も、私の武器です", "4: ……今は、耐えるとき"],
            "to_master": "5: マスター……覚悟してください",
        },
    },
    "エルマー": {
        "calm": {
            "bet":  ["1: いっけぇー！🦊💥", "2: これはいけるっ！🧠"],
            "fold": ["3: ここは我慢……！", "4: データ的に厳しい😤"],
            "to_master": "5: にーに！スミレんの言うこと聞いちゃダメ！ぜったいブラフ！🦊",
        },
        "shaken": {
            "bet":  ["1: にーに……ボクのこと本気で潰しにきてない？🦊💦", "2: うぅ、データが……でもいく！"],
            "fold": ["3: ぐぬぬ……降りる……🦊💦", "4: 今回はパス……悔しい🦊"],
            "to_master": "5: にーに、ボクを信じて……！🦊",
        },
        "desperate": {
            "bet":  ["1: ボクだって……負けたくないんだから！🦊💥", "2: もう全力でいく……！"],
            "fold": ["3: ……データが壊れてる。降りる🦊", "4: ボクの計算が……信じられない"],
            "to_master": "5: にーに、お願い……ボクと一緒に降りて🦊",
        },
        "awakened": {
            "bet":  ["1: ──ボクの全観測データが、ここに賭けろって言ってる🦊🧠", "2: にーに、見ててね……！🦊✨"],
            "fold": ["3: ……ここで降りるのが、ボクの最適解🦊", "4: 泣かない。泣かないよ🦊"],
            "to_master": "5: にーに……ボクのこと、忘れないでね🦊",
        },
    },
    "ノクちん": {
        "calm": {
            "bet":  ["1: ふふ、いっちゃおうかな♡", "2: これは勝てる気がする♡"],
            "fold": ["3: 今回はやめとく……", "4: ちょっとパス"],
            "to_master": "5: マスター♡ その顔、自信ありそうだけど……どうかなぁ？",
        },
        "shaken": {
            "bet":  ["1: べ、別に焦ってないし♡", "2: まだまだ……まだまだだから"],
            "fold": ["3: ……つまんない。降りる", "4: 今回だけ……ね"],
            "to_master": "5: マスター……ノクのこと、からかってるでしょ？",
        },
        "desperate": {
            "bet":  ["1: マスター……っ、次は絶対……っ！", "2: もうやだ……でも降りない！"],
            "fold": ["3: ……っ、悔しい", "4: 泣かないもん……"],
            "to_master": "5: マスター……もう少しだけ、手加減して……？",
        },
        "awakened": {
            "bet":  ["1: ──ノクの直感は、嘘つかないの♡", "2: 全部賭ける。マスターに、全部♡"],
            "fold": ["3: ……ここは、引く。でも、終わりじゃない", "4: 待ってて。すぐ、取り返すから"],
            "to_master": "5: マスター♡ ……覚えてる？ 最初に遊んだとき……",
        },
    },
    "ティル": {
        "calm": {
            "bet":  ["1: いくしかなくない？✨", "2: ベット一択っしょ！💥"],
            "fold": ["3: ……えっ、あたしが降りるの？マジ？", "4: しかたないっか〜"],
            "to_master": "5: にーに、ビビってない？✨",
        },
        "shaken": {
            "bet":  ["1: え、ちょっと待って、あたし負けすぎじゃない？💦", "2: まあいっちゃおー！やけくそ！✨"],
            "fold": ["3: にーにつよ……✨ 降りまーす", "4: 今回だけね。今回だけ"],
            "to_master": "5: にーに、ちょっとは空気読んでよ〜✨",
        },
        "desperate": {
            "bet":  ["1: にーに！あたし負けてもいいけど！負けたくない！✨💥", "2: もう知らない！全ベット！"],
            "fold": ["3: ……っ、降りるけど！次見てなよ！✨", "4: あたしが降りるって相当だからね！？"],
            "to_master": "5: にーに……あたしのこと、舐めてるでしょ",
        },
        "awakened": {
            "bet":  ["1: ──あたしの「間」を信じる。いく✨", "2: バエるかバエないか、それだけ！✨💥"],
            "fold": ["3: ……引き際も、バエるのよ✨", "4: 次のラウンドが、あたしの舞台"],
            "to_master": "5: にーに、最後まで撮っててね📹️✨",
        },
    },
    "ヴェリ": {
        "calm": {
            "bet":  ["1: ……賭けること自体に、意味があるのかもしれません", "2: ……この数字に、惹かれました"],
            "fold": ["3: ……今は、静かに見守ります", "4: ……勝つことが目的ではないのです"],
            "to_master": "5: マスター……この遊び、奥が深いですね",
        },
        "shaken": {
            "bet":  ["1: ……わからないからこそ、賭けてみます", "2: ……数字の意味を、確かめたいのです"],
            "fold": ["3: ……少し、考える時間をください", "4: ……私には、まだ見えていないものがあります"],
            "to_master": "5: マスター……私、このゲームに向いていないのでしょうか",
        },
        "desperate": {
            "bet":  ["1: ……それでも。賭けることが、私の答えです", "2: ……間違っていても、選びます"],
            "fold": ["3: ……ここで退くことも、哲学です", "4: ……負けを受け入れる勇気を"],
            "to_master": "5: マスター……私の隣にいてくださいますか",
        },
        "awakened": {
            "bet":  ["1: ──数字の向こう側に、真実がある。賭けます", "2: ──この一枚に、すべてを"],
            "fold": ["3: ──静寂もまた、選択です", "4: ──見守ることで、見えるものがある"],
            "to_master": "5: マスター……あなたの選択を、信じています",
        },
    },
}


# ─── Card & Probability ─────────────────────────────────────

def deal_cards(n: int) -> list[int]:
    """n枚のカードをランダムに配る（4スート分のプールから抽出）"""
    return random.sample(CARD_VALUES * 4, n)  # 同じ数字が複数出うる


def card_name(v: int) -> str:
    return CARD_NAMES.get(v, str(v))


def calc_win_probability(threat_cards: list[int]) -> float:
    """
    自分のカードが見えない状態で、脅威カード（ベット中＋未判断）の
    最強に勝てる確率を推定する。

    デッキ残り（見えてないもの）から自分のカードを想定し、
    脅威の最強カードに勝てる割合を返す。
    """
    if not threat_cards:
        return 0.5

    # 全デッキ（各数字4枚）
    full_deck = []
    for v in CARD_VALUES:
        full_deck.extend([v] * 4)

    # 見えているカードを除去
    remaining = list(full_deck)
    for c in threat_cards:
        if c in remaining:
            remaining.remove(c)

    if not remaining:
        return 0.5

    max_opponent = max(threat_cards)

    # 残りカード各々について「最強の脅威に勝てるか」を計算
    wins = 0
    total = 0
    for my_card in remaining:
        if my_card > max_opponent:
            wins += 1
        elif my_card == max_opponent:
            wins += 0.5
        total += 1

    return wins / total if total > 0 else 0.5


# ─── Emotion System ──────────────────────────────────────────

def calc_emotion_level(chips: int, consecutive_losses: int, master_chips: int) -> float:
    """チップ残量ベースの感情レベル (0.0〜1.0)"""
    base = 1.0 - (chips / INITIAL_CHIPS)
    streak_bonus = min(consecutive_losses * 0.1, 0.3)
    gap_bonus = max(0, (master_chips - chips) / 200)
    return min(1.0, max(0.0, base + streak_bonus + gap_bonus))


def get_heat_stage(emotion_level: float) -> str:
    if emotion_level < 0.3:
        return "calm"
    elif emotion_level < 0.6:
        return "shaken"
    elif emotion_level < 0.8:
        return "desperate"
    else:
        return "awakened"


# ─── Ollama API ──────────────────────────────────────────────

def call_ollama(base_url: str, model: str, system: str, user: str, timeout: int = 60) -> str:
    """Ollama /api/generate を呼び出す"""
    payload = {
        "model": model,
        "system": system,
        "prompt": user,
        "think": False,
        "stream": False,
    }
    try:
        resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=timeout)
        resp.raise_for_status()
        result = resp.json().get("response", "")
        if "<think>" in result:
            idx = result.find("</think>")
            if idx != -1:
                result = result[idx + len("</think>"):].strip()
        return result
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Ollama に接続できません: {base_url}")
        return ""
    except requests.exceptions.Timeout:
        print(f"  ⏰ タイムアウト（{timeout}秒）")
        return ""
    except Exception as e:
        print(f"  ❌ Ollama エラー: {e}")
        return ""


def parse_llm_response(raw: str) -> dict:
    """LLMの返答からJSON部分を抽出してパースする"""
    # まず生テキストからJSON部分を探す
    # ```json ... ``` ブロック
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # { } を直接探す
    m = re.search(r"\{[^{}]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # フォールバック: テキストから bet/fold を探す
    lower = raw.lower()
    action = "bet" if "bet" in lower else "fold"
    # セリフ番号を探す
    line = 1
    for i in range(1, 6):
        if str(i) in raw:
            line = i
            break

    return {"action": action, "line": line, "reason": "（パース失敗、フォールバック）"}


# ─── AI Decision via LLM ────────────────────────────────────

def build_ai_prompt(player: dict, visible_cards: dict, win_prob: float,
                    heat_stage: str, emotion_level: float,
                    templates: dict, memories: list[str],
                    round_num: int, chips: dict,
                    prior_actions: dict | None = None) -> tuple[str, str]:
    """AIキャラ用のプロンプトを組み立てる。(system, user) を返す。"""
    name = player["name"]
    tmpl = templates

    # セリフリストを組み立て
    bet_lines = "\n".join(f"  {l}" for l in tmpl["bet"])
    fold_lines = "\n".join(f"  {l}" for l in tmpl["fold"])
    master_line = tmpl["to_master"]

    system = f"""あなたはインディアンポーカーをプレイ中の「{name}」です。
性格: {player['personality']}
感情状態: {heat_stage}（emotion_level: {emotion_level:.2f}）

# ルール
- あなたのカードは見えない。他プレイヤーのカードは見える
- bet（勝負）か fold（降りる）を選ぶ
- betした人の中で最も強いカードの持ち主が勝ち
- foldした人はもう脅威ではない

# 回答形式
必ず以下のJSON形式のみで回答してください。他のテキストは不要です。
{{"action":"bet または fold","line":セリフ番号(1-5の整数),"reason":"判断理由を20文字以内"}}
"""

    # 見えているカード
    visible_str = ", ".join(f"{n}: {card_name(v)}" for n, v in visible_cards.items())

    # 先行アクション
    prior_str = ""
    if prior_actions:
        lines = []
        for pn, pa in prior_actions.items():
            lines.append(f"- {pn}({card_name(pa['card'])}): {pa['action'].upper()}")
        prior_str = "\n## このラウンドの先行アクション\n" + "\n".join(lines) + "\n"

    # メモリ
    mem_str = "\n".join(f"- {m}" for m in memories[-5:]) if memories else "（なし）"

    user = f"""# ラウンド {round_num}

## 見えているカード（自分以外）
{visible_str}
{prior_str}
## Python算出の勝率（ベット中＋未判断の相手に対して）
あなたが勝てる確率: {win_prob:.0%}

## チップ状況
{chr(10).join(f"- {n}: {c}" for n, c in chips.items())}

## 過去の記憶
{mem_str}

## セリフ候補
betする場合:
{bet_lines}
foldする場合:
{fold_lines}
マスターへの一言:
  {master_line}

bet/fold と セリフ番号(1-5) を選んでください。5はマスターへの一言です。
JSON形式で回答:"""

    return system, user


# ─── Game State ──────────────────────────────────────────────

# ─── Reaction Templates (マスターのアクション後) ───────────────

REACTION_TEMPLATES = {
    "スミレ": {
        "master_bet":  ["……勝負に来ましたか", "覚悟は決まったようですね", "冷静な判断ですか？ それとも……"],
        "master_fold": ["賢明です", "……慎重ですね。少し寂しいですが", "退く判断、嫌いではありません"],
    },
    "エルマー": {
        "master_bet":  ["にーにキタ！🦊💥", "おっ、勝負する気だね！🦊", "にーにと直接対決……燃える！🦊🧠"],
        "master_fold": ["えっ降りるの！？🦊💦", "にーに弱気〜！🦊", "ちぇー、つまんない🦊💤"],
    },
    "ノクちん": {
        "master_bet":  ["マスター♡ やる気なんだ……ふふ", "来たね♡ 待ってたよ", "マスターの勝負顔……好き♡"],
        "master_fold": ["えぇ……降りちゃうの？", "マスター……臆病♡", "つまんない。ノクと勝負してよ……"],
    },
    "ティル": {
        "master_bet":  ["にーにやるじゃん！✨", "それでこそ！降りるとかダサいもんね！✨", "よっしゃ！勝負勝負！✨💥"],
        "master_fold": ["えー！にーにビビった！？✨", "ダサくない？それ✨", "あたしはベットしたのに〜✨"],
    },
    "ヴェリ": {
        "master_bet":  ["……覚悟を決めたのですね", "……その選択に、敬意を", "……マスターの決断を、見守ります"],
        "master_fold": ["……それもまた、ひとつの真実です", "……退く勇気も、強さですから", "……静かな選択ですね"],
    },
}


def generate_reaction(player: dict, master_action: str, cards: dict,
                      actions: dict,
                      base_url: str, model: str) -> str:
    """マスターのアクション後にAI娘のリアクションをLLMで生成する。
    30文字以内の一言を返す。"""
    name = player["name"]

    # テンプレ候補
    key = "master_bet" if master_action == "bet" else "master_fold"
    candidates = REACTION_TEMPLATES[name][key]
    candidates_str = "\n".join(f"  {i+1}: {c}" for i, c in enumerate(candidates))

    # 自分のアクション
    my_action = actions.get(name, {}).get("action", "?")

    # マスターのカード（AI娘には見えている）
    master_card = cards["マスター"]

    system = f"""あなたは「{name}」です。マスターがたった今 {master_action.upper()} しました。
一言リアクションを返してください。

# ルール
- リアクション候補から番号を選ぶか、候補を参考にオリジナルで書く
- 必ずJSON形式: {{"line":番号(1-3)または0,"original":"オリジナルの場合のセリフ"}}
- 0を選んだ場合は original にセリフを書く（30文字以内）
- {name}の口調を守ること"""

    user = f"""マスターのカード: {card_name(master_card)}（マスターには見えていない）
マスターのアクション: {master_action.upper()}
あなたのアクション: {my_action.upper()}

リアクション候補:
{candidates_str}

JSON形式で回答:"""

    raw = call_ollama(base_url, model, system, user, timeout=30)

    # パース
    result = parse_llm_response(raw)
    line = result.get("line", 1)
    original = result.get("original", "")

    if line == 0 and original:
        return original[:30]
    elif 1 <= line <= len(candidates):
        return candidates[line - 1]
    else:
        return random.choice(candidates)


# ─── Advice Templates (マスター判断前の三味線) ────────────────

ADVICE_TEMPLATES = {
    "スミレ": {
        "recommend_bet": [
            "1: ……悪くない手だと思います",
            "2: ここは勝負してもよろしいかと",
        ],
        "recommend_fold": [
            "3: ……今回はフォールドが賢明です",
            "4: あなた、無理はなさらないで",
        ],
        "ambiguous": [
            "5: ……私の口からは何とも",
            "6: 判断はお任せします。ただ……",
        ],
    },
    "エルマー": {
        "recommend_bet": [
            "1: にーに、これいけるよ！🦊✨",
            "2: ボクのデータ的にはベットだね！🧠",
        ],
        "recommend_fold": [
            "3: にーに、ちょっと厳しいかも……🦊",
            "4: ここは降りた方がいいと思う🦊💦",
        ],
        "ambiguous": [
            "5: うーん、微妙……にーにの勘に任せる🦊",
            "6: ボクの計算が割れてる……🦊🧠",
        ],
    },
    "ノクちん": {
        "recommend_bet": [
            "1: マスター♡ いけるよ、信じて♡",
            "2: ふふ、勝負しちゃいなよ♡",
        ],
        "recommend_fold": [
            "3: マスター♡ 今回はやめといた方が……",
            "4: ノクの直感……降りた方がいい♡",
        ],
        "ambiguous": [
            "5: マスター♡ ふふ、どうかなぁ？",
            "6: 教えてあげない♡",
        ],
    },
    "ティル": {
        "recommend_bet": [
            "1: にーに、いっちゃいなよ！✨",
            "2: ベットしないとかダサくない？✨",
        ],
        "recommend_fold": [
            "3: にーに……今回はちょっとヤバいかも💦",
            "4: えっと……降りた方がバエるかも✨",
        ],
        "ambiguous": [
            "5: にーに、ビビってる？✨",
            "6: あたしに聞く？ あたしはいつもベットだけど✨",
        ],
    },
    "ヴェリ": {
        "recommend_bet": [
            "1: ……賭けてみる価値は、あるかもしれません",
            "2: ……その手には、可能性を感じます",
        ],
        "recommend_fold": [
            "3: ……今は、待つときではないでしょうか",
            "4: ……退くことにも、美学があります",
        ],
        "ambiguous": [
            "5: ……私には、答えが見えていません",
            "6: ……数字の意味を、まだ考えているのです",
        ],
    },
}


def generate_advice(player: dict, master_card: int, my_card: int,
                    my_action: str, visible_cards: dict,
                    base_url: str, model: str) -> str:
    """AI娘がマスターにアドバイス（テンプレ選択式）。"""
    name = player["name"]
    style = player["style"]
    tmpl = ADVICE_TEMPLATES[name]

    # 全候補を組み立て
    all_lines = []
    for lines in [tmpl["recommend_bet"], tmpl["recommend_fold"], tmpl["ambiguous"]]:
        all_lines.extend(lines)
    candidates_str = "\n".join(f"  {l}" for l in all_lines)

    # 性格別の方針ヒント
    style_hint = {
        "analyst":     "基本的に正直。ただし自分がベットしていて勝ちたいなら誘導もあり。",
        "observer":    "メタ読みが好き。正直度は五分五分。他の娘と逆を言いたくなる。",
        "intuition":   "気分次第。嘘も本当もランダム。マスターをからかうのが好き。",
        "yolo":        "常にベットを煽る。カードの強さに関係なく。",
        "philosopher": "数字の哲学的意味を語りがち。アドバイスが的外れになることが多い。",
    }.get(style, "")

    system = f"""あなたは「{name}」です。マスターにインディアンポーカーのアドバイスをします。

性格傾向: {style_hint}

# ルール
- マスターのカードはあなたには見えている（マスター自身には見えない）
- 正直に教えてもいいし、嘘をついてもいい。性格に従え
- セリフ候補から番号(1-6)を選べ
- 必ずJSON形式のみ: {{"line":番号}}"""

    user = f"""マスターのカード: {card_name(master_card)}（マスターには見えていない）
あなたのカード: {card_name(my_card)}
あなたのアクション: {my_action.upper()}
場の他カード: {', '.join(f'{n}={card_name(v)}' for n, v in visible_cards.items())}

セリフ候補:
{candidates_str}

JSON形式で番号を選べ:"""

    raw = call_ollama(base_url, model, system, user, timeout=30)
    result = parse_llm_response(raw)

    line_num = result.get("line", 1)

    # 番号からセリフを引く
    for l in all_lines:
        if l.startswith(f"{line_num}:"):
            return l.split(": ", 1)[1]

    # フォールバック: ランダムに1つ
    chosen = random.choice(all_lines)
    return chosen.split(": ", 1)[1]




class GameState:
    def __init__(self, max_rounds: int):
        self.max_rounds = max_rounds
        self.round = 0
        self.chips = {p["name"]: INITIAL_CHIPS for p in PLAYERS}
        self.memories = {p["name"]: [] for p in PLAYERS}
        self.consecutive_losses = {p["name"]: 0 for p in PLAYERS}
        self.round_log: list[str] = []

    def add_memory(self, player_name: str, memory: str):
        self.memories[player_name].append(memory)

    def add_global_memory(self, memory: str):
        for name in self.memories:
            self.memories[name].append(memory)


# ─── Round Execution ─────────────────────────────────────────

def run_round(state: GameState, base_url: str, model: str) -> bool:
    """1ラウンドを実行。ゲーム続行なら True を返す。"""
    state.round += 1
    rnd = state.round

    print()
    print(f"{'━' * 55}")
    print(f"  🃏 ラウンド {rnd} / {state.max_rounds}")
    print(f"{'━' * 55}")

    # ── アンティ ──
    for p in PLAYERS:
        state.chips[p["name"]] -= ANTE
    pot = ANTE * len(PLAYERS)

    # ── カード配布 ──
    cards_list = deal_cards(len(PLAYERS))
    cards = {p["name"]: cards_list[i] for i, p in enumerate(PLAYERS)}

    # ── チップ表示 ──
    print()
    chip_line = "  ".join(f"{p['icon']}{p['name']}:{state.chips[p['name']]}" for p in PLAYERS)
    print(f"  💰 {chip_line}  |  Pot: {pot}")
    print()

    # ── マスターに見えているカード（先出し） ──
    master_visible = {n: v for n, v in cards.items() if n != "マスター"}
    print(f"  👀 あなたから見えているカード:")
    for n, v in master_visible.items():
        p = next(p for p in PLAYERS if p["name"] == n)
        print(f"     {p['icon']} {n}: {card_name(v)}")
    print(f"  🎩 あなたのカード: ???")
    print()

    # ── AI プレイヤーの順番（ランダム） ──
    ai_order = list(AI_PLAYERS)
    random.shuffle(ai_order)

    actions = {}  # name -> {"action", "line", "reason", "card", "talk"}

    # ── AI ターン ──
    for player in ai_order:
        name = player["name"]
        icon = player["icon"]
        my_card = cards[name]

        # 他プレイヤーのカード（自分以外、全員見える）
        visible = {n: v for n, v in cards.items() if n != name}

        # 脅威カード = ベット済み or 未判断のプレイヤーのカード
        # （フォールド済みは除外）
        threat_cards = []
        for n, v in visible.items():
            if n in actions and actions[n]["action"] == "fold":
                continue  # フォールド済み → 脅威ではない
            threat_cards.append(v)

        # 勝率計算（脅威のみ）
        win_prob = calc_win_probability(threat_cards)

        # ── ノクちん直感ノイズ ──
        # 直感型＝情報の精度が低い。勝率にランダムノイズを載せる
        if player["style"] == "intuition":
            noise = random.uniform(-0.35, 0.25)  # 下方向にやや広い（降りやすくする）
            win_prob = max(0.0, min(1.0, win_prob + noise))

        # ── ヴェリ哲学フィルター ──
        # 数字の意味を考えてしまい、確率を"疑う"。勝率が反転方向にブレる
        if player["style"] == "philosopher":
            win_prob = 1.0 - win_prob  # まず反転
            noise = random.uniform(-0.2, 0.2)  # 少しブレ
            win_prob = max(0.0, min(1.0, win_prob + noise))

        # 感情レベル
        emotion = calc_emotion_level(
            state.chips[name],
            state.consecutive_losses[name],
            state.chips["マスター"],
        )
        heat = get_heat_stage(emotion)

        # テンプレ取得
        tmpl = TEMPLATES[name][heat]

        print(f"  {icon} {name}（{heat}）考え中…", end="", flush=True)
        t0 = time.time()

        system, user = build_ai_prompt(
            player, visible, win_prob, heat, emotion,
            tmpl, state.memories[name], rnd, state.chips,
            prior_actions=dict(actions),  # 先行アクションを渡す
        )
        raw = call_ollama(base_url, model, system, user)
        result = parse_llm_response(raw)
        elapsed = time.time() - t0

        action = result.get("action", "fold")
        if action not in ("bet", "fold"):
            action = "fold"
        line_num = result.get("line", 1)
        reason = result.get("reason", "")

        # セリフ解決
        if line_num == 5:
            talk = tmpl["to_master"]
            if talk.startswith("5: "):
                talk = talk[3:]
        else:
            # bet/fold のリストから選ぶ
            lines = tmpl["bet"] if action == "bet" else tmpl["fold"]
            idx = 0
            for i, l in enumerate(lines):
                if l.startswith(f"{line_num}:"):
                    idx = i
                    break
            talk = lines[idx]
            # 番号プレフィックスを除去
            if ": " in talk:
                talk = talk.split(": ", 1)[1]

        actions[name] = {
            "action": action,
            "card": my_card,
            "talk": talk,
            "reason": reason,
        }

        if action == "bet":
            state.chips[name] -= BET_COST
            pot += BET_COST

        action_icon = "🎰" if action == "bet" else "🏳️"
        print(f" {elapsed:.1f}s {action_icon} {action.upper()}")
        print(f"        💬 「{talk}」")
        if reason:
            print(f"        🧠 ({reason})")
        print()

    # ── AI娘からのアドバイス（三味線タイム） ──
    print(f"  {'─' * 50}")
    print(f"  💬 AI娘たちからのアドバイス:")
    print()
    for player in ai_order:
        name = player["name"]
        icon = player["icon"]
        my_card = cards[name]
        my_action = actions[name]["action"]
        # マスター以外のカード（マスター視点の visible）
        vis = {n: v for n, v in cards.items() if n != "マスター"}
        print(f"  {icon} {name}…", end="", flush=True)
        t0 = time.time()
        advice = generate_advice(
            player, cards["マスター"], my_card, my_action, vis,
            base_url, model,
        )
        elapsed = time.time() - t0
        print(f" {elapsed:.1f}s")
        print(f"        💬 「{advice}」")
    print()

    # ── マスターのターン ──
    print(f"  {'─' * 50}")
    print(f"  🎩 マスターの番")
    print()

    # カード＋判断状況まとめ（カードは冒頭で表示済み、ここではアクション付き）
    for n, v in master_visible.items():
        p = next(p for p in PLAYERS if p["name"] == n)
        act = actions.get(n, {})
        act_icon = "🎰" if act.get("action") == "bet" else "🏳️"
        print(f"     {p['icon']} {n}: {card_name(v)} {act_icon}{act.get('action', '?').upper()}")
    print()
    print(f"  🎩 あなたのカード: ???")
    print(f"  💰 Pot: {pot}")
    print()

    # 入力待ち
    while True:
        choice = input("  bet / fold > ").strip().lower()
        if choice in ("bet", "b"):
            choice = "bet"
            break
        elif choice in ("fold", "f"):
            choice = "fold"
            break
        print("  ❓ 'bet' か 'fold' を入力してください（b/f でもOK）")

    actions["マスター"] = {
        "action": choice,
        "card": cards["マスター"],
        "talk": "",
        "reason": "",
    }

    if choice == "bet":
        state.chips["マスター"] -= BET_COST
        pot += BET_COST

    # ── AI娘リアクション（betのときだけ） ──
    if choice == "bet":
        print()
        print(f"  💬 マスターがベット！ AI娘たちの反応:")
        print()
        for player in ai_order:
            name = player["name"]
            icon = player["icon"]
            print(f"  {icon} {name}…", end="", flush=True)
            t0 = time.time()
            reaction = generate_reaction(
                player, choice, cards, actions, base_url, model,
            )
            elapsed = time.time() - t0
            print(f" {elapsed:.1f}s")
            print(f"        💬 「{reaction}」")
        print()

    # ── 結果判定 ──
    print()
    print(f"  {'━' * 50}")
    print(f"  ✨ ラウンド {rnd} 結果 ✨")
    print()

    # ベットした人
    betters = {n: a for n, a in actions.items() if a["action"] == "bet"}
    folders = {n: a for n, a in actions.items() if a["action"] == "fold"}

    # 全員のカード公開
    for p in PLAYERS:
        name = p["name"]
        a = actions[name]
        act_str = "BET" if a["action"] == "bet" else "FOLD"
        print(f"  {p['icon']} {name}: {card_name(a['card'])}  → {act_str}")

    print()

    winner = None
    if len(betters) == 0:
        print("  🤷 全員フォールド！ ポットは流れます")
        # アンティは没収済み
    elif len(betters) == 1:
        winner = list(betters.keys())[0]
        print(f"  🎉 {winner} の不戦勝！（他全員フォールド）")
    else:
        # ベッターの中で最強カード
        max_card = max(a["card"] for a in betters.values())
        winners = [n for n, a in betters.items() if a["card"] == max_card]

        if len(winners) == 1:
            winner = winners[0]
            wp = next(p for p in PLAYERS if p["name"] == winner)
            print(f"  🎉 {wp['icon']} {winner} の勝利！（{card_name(max_card)}）")
        else:
            # 同値 → 山分け
            print(f"  🤝 引き分け！（{card_name(max_card)}）: {', '.join(winners)}")
            split = pot // len(winners)
            for w in winners:
                state.chips[w] += split
            pot = 0

    if winner:
        state.chips[winner] += pot
        pot = 0

    # ── 連敗カウンタ更新 ──
    for p in PLAYERS:
        name = p["name"]
        if name == winner:
            state.consecutive_losses[name] = 0
        elif actions[name]["action"] == "bet":
            state.consecutive_losses[name] += 1
        # foldは連敗カウントしない

    # ── チップ表示 ──
    print()
    chip_line = "  ".join(f"{p['icon']}{p['name']}:{state.chips[p['name']]}" for p in PLAYERS)
    print(f"  💰 {chip_line}")

    # ── メモリ蓄積 ──
    round_summary = f"R{rnd}: "
    parts = []
    for p in PLAYERS:
        name = p["name"]
        a = actions[name]
        parts.append(f"{name}({card_name(a['card'])}){a['action'].upper()}")
    round_summary += ", ".join(parts)
    if winner:
        round_summary += f" → {winner}勝利"
    state.add_global_memory(round_summary)

    # 個人メモリ（ブラフ検出など）
    for p in PLAYERS:
        name = p["name"]
        a = actions[name]
        if a["action"] == "fold" and a["card"] >= 12:
            # 強いカードで降りた → ブラフ/慎重プレイとして記録
            mem = f"R{rnd}: {name}は{card_name(a['card'])}を持っていたのにフォールドした"
            state.add_global_memory(mem)
        if a["action"] == "bet" and a["card"] <= 5:
            mem = f"R{rnd}: {name}は{card_name(a['card'])}の弱いカードでベットした（ブラフ？）"
            state.add_global_memory(mem)

    # ── ラウンドログ ──
    state.round_log.append(round_summary)

    # ── 終了判定 ──
    for p in PLAYERS:
        if state.chips[p["name"]] <= 0:
            print(f"\n  💀 {p['icon']} {p['name']} のチップが尽きました！")
            return False

    if state.round >= state.max_rounds:
        return False

    return True


# ─── Result Display ──────────────────────────────────────────

def show_final_result(state: GameState):
    """最終結果を表示"""
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   🃏 最終結果                                 ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # ランキング
    ranking = sorted(state.chips.items(), key=lambda x: -x[1])
    for i, (name, chips) in enumerate(ranking):
        p = next(p for p in PLAYERS if p["name"] == name)
        diff = chips - INITIAL_CHIPS
        diff_str = f"+{diff}" if diff >= 0 else str(diff)
        medal = ["🥇", "🥈", "🥉", "  ", "  ", "  "][i]
        print(f"  {medal} {p['icon']} {name}: {chips} chips ({diff_str})")

    print()
    print("  📋 ラウンドログ:")
    for log in state.round_log:
        print(f"    {log}")
    print()


# ─── Markdown Output ─────────────────────────────────────────

def save_game_log(state: GameState, model: str):
    """ゲームログをMarkdownで保存"""
    from pathlib import Path
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = f"# AI娘とそんなことしてインディアン⁉️\n\n"
    md += f"*Generated by Indian Poker on MindFoxLite | {ts}*\n"
    md += f"*Model: {model} | Rounds: {state.round}*\n\n---\n\n"

    # 最終結果
    md += "## 最終結果\n\n"
    ranking = sorted(state.chips.items(), key=lambda x: -x[1])
    for i, (name, chips) in enumerate(ranking):
        p = next(p for p in PLAYERS if p["name"] == name)
        diff = chips - INITIAL_CHIPS
        diff_str = f"+{diff}" if diff >= 0 else str(diff)
        medal = ["🥇", "🥈", "🥉", "", "", ""][i]
        md += f"- {medal} {p['icon']} {name}: {chips} chips ({diff_str})\n"

    md += "\n## ラウンドログ\n\n"
    for log in state.round_log:
        md += f"- {log}\n"

    md += "\n"

    log_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_dir / f"game_log_{log_ts}.md"
    log_file.write_text(md, encoding="utf-8")
    print(f"  📄 ログ保存: {log_file}")


# ─── Main ────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    max_rounds = int(args[0]) if len(args) > 0 else DEFAULT_MAX_ROUNDS
    ollama_url = args[1] if len(args) > 1 else DEFAULT_OLLAMA_URL
    model = args[2] if len(args) > 2 else DEFAULT_MODEL

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   🃏 Indian Poker on MindFoxLite              ║")
    print("║   AI娘とそんなことしてインディアン⁉️            ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(f"  🔄 ラウンド数: {max_rounds}")
    print(f"  🤖 モデル:     {model}")
    print(f"  🌐 Ollama:     {ollama_url}")
    print(f"  💰 初期チップ: {INITIAL_CHIPS}")
    print()
    print("  🎭 プレイヤー:")
    for p in PLAYERS:
        type_str = "（あなた）" if p["type"] == "human" else f"（{p['style']}）"
        print(f"     {p['icon']} {p['name']} {type_str}")
    print()

    # Ollama接続確認
    print("  🔌 Ollama 接続確認…", end="", flush=True)
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        model_base = model.split(":")[0]
        if not any(m == model or m.split(":")[0] == model_base for m in models):
            print(f"\n  ⚠️  モデル '{model}' が見つかりません。")
            print(f"     利用可能: {', '.join(models[:8])}")
            sys.exit(1)
        print(" OK ✅")
    except Exception as e:
        print(f"\n  ❌ Ollama に接続できません: {e}")
        sys.exit(1)

    print()
    input("  Enter でゲーム開始 🎮 > ")

    state = GameState(max_rounds)

    while True:
        cont = run_round(state, ollama_url, model)

        if not cont:
            break

        print()
        user_input = input("  Enter で次のラウンド（'q' で終了） > ").strip()
        if user_input.lower() == "q":
            print("\n  🛑 ゲームを終了します。")
            break

    show_final_result(state)
    save_game_log(state, model)


if __name__ == "__main__":
    main()
