# AdvancedRAG 前処理最適化システム

日本語技術文書に最適化されたPDF前処理システムです。図表を含むページを自動検出し、適切な処理方法を選択することで、高速かつ高精度な文書処理を実現します。

## 📚 ドキュメント

- [技術ドキュメント](TECHNICAL_DOCUMENTATION.md) - システムアーキテクチャと実装詳細
- [プロジェクトサマリー](PROJECT_SUMMARY.md) - 成果と改善内容のまとめ

## 🚀 特徴

- **統一コマンド**: `python process.py`で全機能を実行可能
- **高速処理**: 3段階判定システムにより、不要な処理をスキップ
- **高精度**: 図番号パターン検出により、重要な図表を見逃さない（誤検知防止機能付き）
- **AI画像解析**: Gemini 2.0 Flashによる高度な画像・図表解析
- **効率的**: ページタイプに応じた最適な処理方法を自動選択
- **日本語対応**: 「図1-1」「表2-3」などの日本語図番号を認識
- **自動設定**: .envファイルからAPIキーを自動読み込み
- **分離出力**: テキスト、表、画像を別々のフォルダに整理して出力

## 📊 性能

- 処理速度: 約0.5秒/ページ
- 図表検出率: 85%以上（誤検知防止機能により精度向上）
- 処理時間削減: 従来比64%削減
- コードベース削減: 25%（重複コード削除により806行削減）

## 🔧 インストール

```bash
# リポジトリのクローン
git clone <repository-url>
cd preprocessing_optimizer

# 依存関係のインストール
pip install -r requirements.txt

# 環境変数の設定（.envファイル）
# GOOGLE_API_KEY または GEMINI_API_KEY を設定
cat > .env << EOF
GOOGLE_API_KEY=your_gemini_api_key_here
EOF
```

## 📖 使い方

### 統一コマンド（推奨）

```bash
# すべての形式で出力（デフォルト）
python process.py input.pdf

# テキストのみ抽出
python process.py input.pdf --format text

# タイプ別に分離して出力
python process.py input.pdf --format separated

# 出力先を指定
python process.py input.pdf -o my_output

# Geminiを使わない（高速処理）
python process.py input.pdf --no-gemini

# シーケンシャル処理（メモリ節約）
python process.py input.pdf --sequential
```

### 個別コマンド（レガシー）

```bash
# 基本的なPDF処理
python main.py path/to/document.pdf

# テキストのみ抽出
python extract_text.py processing_summary.json output.txt

# タイプ別に分離して出力
python export_separated.py processing_summary.json output_dir/
```

### Pythonコード

```python
from main import AdvancedRAGPreprocessor

# プロセッサーの初期化
preprocessor = AdvancedRAGPreprocessor()

# PDFの処理
results = preprocessor.process_pdf("document.pdf")

# 結果の確認
print(f"画像化ページ数: {results['summary']['image_pages']}")
print(f"処理時間: {results['processing_time']:.2f}秒")
```

### カスタム設定

```python
from core.practical_optimizer import PracticalConfig

# カスタム設定の作成
config = PracticalConfig(
    quick_text_density_threshold=0.8,  # テキスト密度の閾値
    min_table_cells=10,                # 表と判定する最小セル数
    complex_table_cell_threshold=40,   # 複雑な表の閾値
)

# カスタム設定でプロセッサーを初期化
preprocessor = AdvancedRAGPreprocessor(config)
```

## 🏗️ アーキテクチャ

### 処理フロー

```
PDF入力
  ↓
Stage 1: 高速スクリーニング（0.1秒）
  - テキスト密度計算
  - 図番号パターン検出
  - 大画像の検出
  ↓
Stage 2: 詳細分析（必要時のみ）
  - PyMuPDF表検出
  - 図形要素カウント
  - テキストパターン分析
  ↓
Stage 3: 処理方法決定
  - テキストのみ → 高速処理
  - 単純な表 → 構造化抽出
  - 複雑な表/図 → 画像化+AI解析
```

### モジュール構成

```
preprocessing_optimizer/
├── process.py                 # 統一コマンドインターフェース
├── main.py                    # 基本処理エントリーポイント
├── extract_text.py            # テキスト抽出ツール
├── export_separated.py        # タイプ別分離エクスポート
├── .env                       # API設定（自動読み込み）
├── core/
│   ├── practical_optimizer.py # 統合最適化エンジン（視覚要素チェック機能統合）
│   └── text_processor.py      # テキスト処理
├── config/
│   └── config.py             # 設定管理
└── docs/
    └── archive/              # 過去のドキュメント
        ├── 図表検出改善_実装完了レポート.md
        └── 図表検出精度改善計画.md
```

## 🎯 出力形式

### 統一コマンドの出力オプション

| フォーマット | 説明 | 出力内容 |
|------------|------|----------|
| all | すべての形式（デフォルト） | テキスト、表、画像、処理サマリー |
| text | テキストのみ | extracted_text.txt |
| separated | タイプ別分離 | text/, tables/, images/ フォルダ |
| image | 画像のみ | images/ フォルダ |

### 出力ファイル構造

```
output_directory/
├── processing_summary.json    # 処理結果の詳細（Gemini解析結果含む）
├── extracted_text.txt        # 全テキスト（Gemini解析テキスト含む）
├── images/                   # 画像ファイル（--format image/all）
└── separated/                # タイプ別分離（--format separated/all）
    ├── text/
    │   └── all_text.txt      # 純粋なテキストページ
    ├── tables/
    │   ├── table_*.csv       # 表データ（CSV形式）
    │   └── table_*.xlsx      # 表データ（Excel形式）
    └── images/
        ├── flowchart/        # フローチャート画像
        │   ├── *.png
        │   └── *_analysis.txt # Gemini解析結果
        ├── diagram/          # 図・ダイアグラム
        │   ├── *.png
        │   └── *_analysis.txt # Gemini解析結果
        └── complex_table/    # 複雑な表の画像
            ├── *.png
            └── *_analysis.txt # Gemini解析結果
```

### Gemini解析結果の出力

Gemini 2.0 Flashによる画像解析結果は以下の場所に保存されます：

1. **processing_summary.json** - 各ページの`gemini_analysis`フィールド
2. **extracted_text.txt** - 統合テキスト内に`[Gemini 2.0 Flash解析結果]`セクション
3. **separated/images/\*/\*_analysis.txt** - 画像ごとの個別解析ファイル

## 🎯 処理タイプ

| ページタイプ | 処理方法 | 用途 |
|------------|---------|------|
| 純粋なテキスト | テキスト抽出のみ | 高速検索 |
| 単純な表 | 構造化データ抽出 | データ分析 |
| 複雑な表 | 画像化+Gemini解析 | レイアウト保持 |
| フロー図 | 画像化+ML解析 | 内容理解 |
| 図番号付きページ | 優先的に画像化 | 重要情報保持 |

## 📊 信頼度スコアリング

システムは各ページの図表検出に対して0-100の信頼度スコアを計算します：

### 信頼度の計算要素

| 検出要素 | スコア | 説明 |
|---------|--------|------|
| 表検出 | +30 | PyMuPDFによる表構造の検出 |
| フローチャート | +60〜80 | 矩形と矢印の組み合わせ |
| 図形要素 | +40 | 一定数以上の図形要素 |
| 埋め込み画像 | +50 | サイズ閾値を超える画像 |
| 図番号キーワード | +20 | 視覚要素を伴う図番号 |

※最終スコアは100を上限として正規化されます

## 🚀 主な改善点

### 1. 誤検知防止機能（統合済み）
図表への参照文（「図1を参照」など）がある場合の誤検知を防止。実際の視覚要素（画像、図形、表）が存在する場合のみ図表として判定。PracticalPageAnalyzerに視覚要素チェック機能を統合し、単一エンジンで高精度判定を実現。

### 2. Gemini 2.0 Flash統合
- フローチャートの解析
- 複雑な表の構造化
- 技術図面の内容理解
- 画像の詳細な説明生成

### 3. コードベースの最適化
- 重複した分析器の統合（SmartPageAnalyzer機能をPracticalPageAnalyzerに統合）
- 未使用コードの削除（UnifiedFigureDetector、diagnostic_tool.py等）
- 806行のコード削減により保守性向上

### 4. 自動環境設定
.envファイルからAPIキーを自動読み込み。複数のAPIキー形式に対応：
- GOOGLE_API_KEY
- GEMINI_API_KEY
- OPENAI_API_KEY（将来の拡張用）

## 📈 活用例

### RAGシステムとの統合

```python
# 処理結果をRAGシステムに統合
for page in results['processed_pages']:
    if page['processing_method'] == 'text_only':
        # ベクトルDBに直接インデックス
        vector_db.add_text(page['text'])
    
    elif page['processing_method'] == 'structured':
        # 構造化データとして保存
        structured_db.add_table(page['structured_data'])
    
    elif 'image' in page['processing_method']:
        # マルチモーダル処理
        summary = multimodal_llm.analyze(page['image_path'])
        vector_db.add_with_metadata(summary, page)
```

## 🔍 設定パラメータ

### PracticalConfig

| パラメータ | デフォルト値 | 説明 |
|-----------|------------|------|
| quick_text_density_threshold | 0.75 | テキスト密度の閾値 |
| min_table_cells | 8 | 表と判定する最小セル数 |
| complex_table_cell_threshold | 30 | 複雑な表のセル数閾値 |
| figure_number_patterns | 自動設定 | 図番号の正規表現パターン |

## 📝 ライセンス

MIT License

## 🤝 貢献

Issue や Pull Request を歓迎します。

## 📞 サポート

問題が発生した場合は、Issueを作成してください。