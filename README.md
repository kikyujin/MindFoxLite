# 🦊 MindFoxLite🎈

**マルチエージェント・ストーリージェネレーター**

各キャラクターが独立したLLMエージェントとして行動し、ターンごとに物語を紡ぐシンプルなツール。

## 特徴

- **ローカル完結** — Ollama + gemma4:26b で動作。APIキー不要
- **ターン制** — 1ターンごとにmdファイルを出力して停止。ユーザーが修正可能
- **キャラ独立** — 各キャラをランダム順で個別にLLM呼び出し
- **最小構成** — Python 1ファイル + world.md + agents.json だけ

## 必要環境

- Python 3.10+
- Ollama（gemma4:26b をpull済み）
- requests ライブラリ（`pip install requests`）

## ファイル構成

```
mindfoxlite/
├── mindfoxlite.py     メインスクリプト
├── world.md        世界設定
├── agents.json     キャラクター定義
├── README.md       このファイル
├── output_sample/  実行結果のサンプル
└── output/         （実行時に自動生成）
    ├── turn_01.md
    ├── turn_02.md
    ├── ...
    └── story.md    全ターン結合版
```

## 使い方

```bash
# セットアップ
pip install requests

# 基本
python mindfoxlite.py

# 引数指定
python mindfoxlite.py world.md agents.json 6

# リモートOllama
python mindfoxlite.py world.md agents.json 6 http://m4max.local:11434
```

## ターンの流れ

1. キャラクターの行動順をランダムシャッフル
2. 各キャラごとにgemma4を呼び出し → 行動・台詞を生成
3. 全キャラの行動をまとめて `turn_XX.md` に書き出し
4. 「状況まとめ」を自動生成（次ターンのコンテキストに使用）
5. ユーザーがmdを確認・修正 → Enter で次ターンへ

## カスタマイズ

### 世界設定（world.md）

Markdown形式で自由に記述。舞台、ルール、トーンを定義する。

### キャラクター（agents.json）

```jsonc
{
  "agents": [
    {
      "agent_id": "unique_id",
      "name": "表示名",
      "archetype": "性格タイプ",  // stubborn, leader, impulsive, observer, contrarian 等
      "role": "役職・立場",
      "background": "過去と人格形成の背景",
      "motivation": "このシミュレーションでの動機・目標",
      "relationships": {
        "other_agent_id": "関係の説明"
      }
    }
  ]
}
```

### モデル変更

`mindfoxlite.py` 冒頭の `DEFAULT_MODEL` を書き換えるか、コード内で変更：

```python
DEFAULT_MODEL = "gemma4:12b"  # 軽量版
```

## ライセンス

MIT

## クレジット

MindFoxLite は現在開発中の簡易版として設計。
MindFox は [MiroFish](https://github.com/666ghj/MiroFish) にインスパイアされたプロジェクト。

---

```
   🦊✨ Crafted with love by ✨🎈

   Kikyujin    — 物語の設計者
   エルマー     — AIの相棒

   2026.4.16 — Seoul, Tokyo, and beyond
```
