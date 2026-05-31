# オントロジーデモ

Palantirなどのプラットフォームで起きている「データ統合 → 文脈理解 → アクション」の流れを再現したデモです。

## 概要

このデモは、サプライチェーン全体をオントロジーとして管理し、AIが関係性を理解して分析・推奨アクションを提示するシステムです。Palantir Foundryスタイルの「Human-in-the-loop: Search -> Select -> Execute」のワークフローを実装しています。

さらに本デモは、**同じ世界・同じ事故を「オントロジー」と「従来のDB(RDB+SQL)」の両方で扱える**ようにし、両者の設計思想の違いを体感できる構成にしています。

## 3つのモード（タブ）

サイドバーの Chaos 注入（サプライヤー停止 / 工場停止）は **3タブすべてに同時反映** されます。同じ状態を別々の「見方」で扱える点がこのデモの肝です。

| タブ | 何を見るか |
|---|---|
| 🌐 **Ontology Mode** | データを「オブジェクト+リンクのグラフ」として扱う。全体グラフ + 選択製品の Context Trace（辿ったリンク経路）+ AIの複合判断 + Write-back アクション |
| 📊 **Classic DB Mode** | 同じデータを正規化テーブルで保持。「停止中サプライヤーが脅かすVIP注文」を出すのに **4テーブルJOINのSQL** を書く様子と、AIに渡るのが「ID中心の平たい表」になる様子を体感 |
| ⚖️ **Compare** | 同じ事故への対応を左右に並べ、必要クエリ数・文脈の有無・分析→実行の統合度・スキーマの役割を総括 |

### オントロジーの構成要素（コード上の対応）

- **Object Type** = Pydanticクラス `Supplier / Material / Factory / Product / Order`
- **Property** = 各クラスの属性（`status`, `stock`, `priority` …）
- **Link** = オブジェクト間の参照（`supplier_id`, `factory_id`, `material_required_id`, `product_id`）
- **Action (Write-back)** = 分析結果を世界に書き戻す操作（代替発注 / VIP割当 / 緊急増産）

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. Graphvizのインストール（グラフ可視化に必要）

**Windows:**
- [Graphviz公式サイト](https://graphviz.org/download/)からインストーラーをダウンロード
- または Chocolatey を使用: `choco install graphviz`

**macOS:**
```bash
brew install graphviz
```

**Linux:**
```bash
sudo apt-get install graphviz
```

## 実行方法

Streamlitアプリを起動:
```bash
streamlit run app.py
```

ブラウザが自動的に開き、デモアプリが表示されます（通常は http://localhost:8501）。

## 主な機能

### 1. オントロジー管理
- **Supplier（サプライヤー）** → **Material（素材・部品）** → **Factory（工場）** → **Product（製品）** → **Order（注文）**
- サプライチェーン全体の関係性をグラフ構造で管理

### 2. セマンティックグラフ可視化
- Graphvizによる関係性マップの表示
- 各オブジェクトの状態（正常/異常）を色分けで表示
- 在庫不足やVIP注文を視覚的に識別

### 3. AIアシスタント
- オントロジー全体を分析してリスクを検出
- 状況に応じた推奨アクションを自動提示
- サプライヤートラブル、工場停止、在庫不足などを総合的に判断

### 4. アクション実行とフィードバック
- **VIP優先割り当て**: 重要顧客への在庫確保
- **緊急増産指示**: 工場への製造ライン稼働指示
- **代替サプライヤー検索**: トラブル時の候補企業検索と発注
- 実行結果をBefore/After形式でレポート表示

### 5. Chaos Engineering（障害注入）
- サイドバーからサプライヤーや工場の状態を意図的に変更
- AIの反応と推奨アクションをリアルタイムで確認

## 使い方

1. **製品選択**: サイドバーの「分析対象を選択」から製品を選ぶ
2. **状態変更**: 「Supply Chain Objects」セクションでサプライヤーや工場の状態を変更
3. **分析確認**: メイン画面でグラフとAI分析結果を確認
4. **アクション実行**: 推奨されたアクションボタンをクリック
5. **結果確認**: 実行後のレポートで変更内容（Before/After）を確認

## 技術スタック

- **Streamlit**: Webアプリケーションフレームワーク
- **Pydantic**: データモデル定義とバリデーション（= オントロジーの Object Type）
- **Graphviz**: セマンティックグラフ可視化
- **SQLite (標準ライブラリ) + pandas**: Classic DB Mode のテーブル/SQLシミュレーション

## ファイル構成

- `app.py`: メインアプリケーション
- `requirements.txt`: 依存関係リスト
- `README.md`: このファイル
