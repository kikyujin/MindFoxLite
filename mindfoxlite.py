#!/usr/bin/env python3
"""
MindFoxLite - Simple Multi-Agent Story Generator
================================================
マルチエージェントによる物語自動生成ツール。
各キャラクターがLLMで独立に行動し、ターンごとにmdファイルを出力する。

Usage:
    python mindfoxlite.py [world.md] [agents.json] [max_turns] [ollama_url]

Examples:
    python mindfoxlite.py                              # デフォルト設定で実行
    python mindfoxlite.py world.md agents.json 6       # 6ターン実行
    python mindfoxlite.py world.md agents.json 4 http://m4max.local:11434  # リモートOllama
"""

import json
import random
import sys
import time
import requests
from pathlib import Path
from datetime import datetime


# ─── Configuration ───────────────────────────────────────────

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:26b"
DEFAULT_MAX_TURNS = 6
OUTPUT_DIR = Path("output")


# ─── File I/O ────────────────────────────────────────────────

def load_world(path: str) -> str:
    """世界設定mdを読み込む"""
    p = Path(path)
    if not p.exists():
        print(f"❌ 世界設定ファイルが見つかりません: {path}")
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def load_agents(path: str) -> list[dict]:
    """エージェントJSONを読み込む"""
    p = Path(path)
    if not p.exists():
        print(f"❌ エージェントファイルが見つかりません: {path}")
        sys.exit(1)
    data = json.loads(p.read_text(encoding="utf-8"))
    return data["agents"]


# ─── Ollama API ──────────────────────────────────────────────

def call_ollama(
    base_url: str,
    model: str,
    system: str,
    user: str,
    timeout: int = 180,
) -> str:
    """Ollama /api/generate を呼び出す。think: false 必須（gemma4）"""
    payload = {
        "model": model,
        "system": system,
        "prompt": user,
        "think": False,
        "stream": False,
    }
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("response", "")
        # 万が一 thinking ブロックが混入した場合のフィルタ
        if "<think>" in result:
            idx = result.find("</think>")
            if idx != -1:
                result = result[idx + len("</think>"):].strip()
        return result
    except requests.exceptions.ConnectionError:
        print(f"❌ Ollama に接続できません: {base_url}")
        print("   ollama serve が起動しているか確認してください。")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"⏰ タイムアウト（{timeout}秒）。モデルが重すぎるかも。")
        return "（応答なし）"
    except Exception as e:
        print(f"❌ Ollama エラー: {e}")
        return "（エラー）"


# ─── Prompt Construction ─────────────────────────────────────

def build_system_prompt(world: str, agent: dict) -> str:
    """キャラクター用のシステムプロンプトを組み立てる"""
    rels = "\n".join(
        f"  - {aid}: {desc}"
        for aid, desc in agent.get("relationships", {}).items()
    )

    return f"""あなたは韓国ドラマの脚本家として、指定されたキャラクターの視点でシーンを執筆します。

## 世界設定
{world}

## あなたが演じるキャラクター
- 名前: {agent['name']}
- 役職: {agent['role']}
- 性格タイプ: {agent['archetype']}
- 背景: {agent.get('background', '')}
- 動機: {agent['motivation']}
- 人間関係:
{rels}

## 執筆ルール
- {agent['name']}の視点で、このターンの行動・心理・台詞を書く
- 三人称（「{agent['name']}は〜」）で記述
- 台詞は「」で囲む。心の声は（）で囲む
- 他キャラとの直接的なやりとりがあれば対話を含める
- 300〜500字程度
- 感情描写を丁寧に。視線、仕草、表情で内面を表現する
- 韓国ドラマらしいドラマチックさを意識する
"""


def build_user_prompt(
    agent: dict,
    turn_num: int,
    history_summaries: list[str],
    earlier_this_turn: str,
) -> str:
    """キャラクターへのターン指示プロンプトを組み立てる"""
    parts = [f"# ターン {turn_num}\n"]

    if history_summaries:
        parts.append("## これまでの流れ\n")
        for i, s in enumerate(history_summaries, 1):
            parts.append(f"### ターン{i}のまとめ\n{s}\n")

    if earlier_this_turn:
        parts.append(
            f"## このターンで先に起きたこと\n{earlier_this_turn}\n"
        )

    parts.append(
        f"\n{agent['name']}として、このターンの行動と台詞を書いてください。"
    )
    return "\n".join(parts)


# ─── Turn Execution ──────────────────────────────────────────

def generate_summary(
    base_url: str, model: str, world: str, turn_num: int, sections: str
) -> str:
    """ターンの状況まとめを生成する"""
    system = f"""あなたは物語の語り手です。
このターンの出来事を250字以内で要約してください。
- 権力関係の変化
- 恋愛模様の進展
- 次ターンへの伏線
に注目して簡潔にまとめてください。

{world}"""

    user = f"## ターン{turn_num}の出来事\n\n{sections}"
    return call_ollama(base_url, model, system, user)


def run_turn(
    base_url: str,
    model: str,
    world: str,
    agents: list[dict],
    turn_num: int,
    history_summaries: list[str],
) -> tuple[str, str]:
    """
    1ターンを実行する。
    Returns: (turn_md, summary)
    """
    order = list(range(len(agents)))
    random.shuffle(order)

    sections = []
    earlier = ""

    for idx in order:
        agent = agents[idx]
        print(f"  🎭 {agent['name']}（{agent['archetype']}）…", end="", flush=True)
        t0 = time.time()

        system = build_system_prompt(world, agent)
        user = build_user_prompt(agent, turn_num, history_summaries, earlier)
        response = call_ollama(base_url, model, system, user)

        elapsed = time.time() - t0
        print(f" {elapsed:.1f}s ✅")

        section = f"## {agent['name']}（{agent['role']}）\n\n{response}"
        sections.append(section)
        earlier += f"\n### {agent['name']}\n{response}\n"

    # 状況まとめ
    print("  📝 状況まとめ…", end="", flush=True)
    t0 = time.time()
    all_sections = "\n\n".join(sections)
    summary = generate_summary(base_url, model, world, turn_num, all_sections)
    elapsed = time.time() - t0
    print(f" {elapsed:.1f}s ✅")

    # Markdown 組み立て
    md = f"# ターン {turn_num}\n\n"
    md += all_sections
    md += f"\n\n---\n\n### 状況まとめ\n\n{summary}\n"

    return md, summary


# ─── Main ────────────────────────────────────────────────────

def main():
    # 引数パース
    args = sys.argv[1:]
    world_path = args[0] if len(args) > 0 else "world.md"
    agents_path = args[1] if len(args) > 1 else "agents.json"
    max_turns = int(args[2]) if len(args) > 2 else DEFAULT_MAX_TURNS
    ollama_url = args[3] if len(args) > 3 else DEFAULT_OLLAMA_URL
    model = DEFAULT_MODEL

    # ヘッダー表示
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   🦊 MindFoxLite                            ║")
    print("║   Multi-Agent Story Generator                ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(f"  📖 World:   {world_path}")
    print(f"  🎭 Agents:  {agents_path}")
    print(f"  🔄 Turns:   {max_turns}")
    print(f"  🤖 Model:   {model}")
    print(f"  🌐 Ollama:  {ollama_url}")
    print()

    # ファイル読み込み
    world = load_world(world_path)
    agents = load_agents(agents_path)

    print(f"  登場人物 ({len(agents)}名):")
    for a in agents:
        print(f"    - {a['name']}（{a['role']}）[{a['archetype']}]")
    print()

    # Ollamaの接続確認
    print("  🔌 Ollama 接続確認…", end="", flush=True)
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        model_base = model.split(":")[0]
        if not any(m == model or m.split(":")[0] == model_base for m in models):
            print(f"\n  ⚠️  モデル '{model}' が見つかりません。")
            print(f"     利用可能: {', '.join(models[:5])}")
            print(f"     ollama pull {model} を実行してください。")
            sys.exit(1)
        print(" OK ✅")
    except Exception as e:
        print(f"\n  ❌ Ollama に接続できません: {e}")
        sys.exit(1)

    # 出力ディレクトリ作成
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ターンループ
    history_summaries: list[str] = []
    history_mds: list[str] = []

    for turn in range(1, max_turns + 1):
        print()
        print(f"{'─' * 50}")
        print(f"  🎬 ターン {turn} / {max_turns}")
        print(f"{'─' * 50}")

        md, summary = run_turn(
            ollama_url, model, world, agents, turn, history_summaries
        )

        # ファイル出力
        turn_file = OUTPUT_DIR / f"turn_{turn:02d}.md"
        turn_file.write_text(md, encoding="utf-8")
        print(f"\n  📄 出力: {turn_file}")

        # ユーザー確認
        if turn < max_turns:
            print()
            print(f"  📝 {turn_file} を確認・修正してください。")
            print(f"     修正すると次ターンに反映されます。")
            print(f"     （'q' で中断、Enter で続行）")
            user_input = input("  > ").strip()
            if user_input.lower() == "q":
                print("\n  🛑 中断しました。")
                break
            # 修正済みファイルを再読み込み
            md = turn_file.read_text(encoding="utf-8")
            # サマリーも再抽出（修正されてるかもしれない）
            if "### 状況まとめ" in md:
                summary = md.split("### 状況まとめ")[-1].strip()
        else:
            print("\n  🎬 最終ターン完了！")

        history_summaries.append(summary)
        history_mds.append(md)

    # 全ターン結合
    if history_mds:
        story_file = OUTPUT_DIR / "story.md"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# ミレ・ディフェンスの愛と野望\n\n"
        header += f"*Generated by MindFoxLite on {ts}*\n\n"
        header += f"*Model: {model} | Turns: {len(history_mds)}*\n\n---\n\n"
        body = "\n\n---\n\n".join(history_mds)
        story_file.write_text(header + body, encoding="utf-8")

        print()
        print("╔══════════════════════════════════════════════╗")
        print(f"║  📚 完成！ {story_file}              ║")
        print(f"║  🎭 {len(agents)}キャラ × {len(history_mds)}ターン              ║")
        print("╚══════════════════════════════════════════════╝")
        print()


if __name__ == "__main__":
    main()
