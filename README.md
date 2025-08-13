# AdvancedRAG 前処理最適化システム

日本語技術文書に最適化されたPDF前処理システムです。図表を含むページを自動検出し、適切な処理方法を選択することで、高速かつ高精度な文書処理を実現します。

## 📚 ドキュメント

- [技術ドキュメント](TECHNICAL_DOCUMENTATION.md) - システムアーキテクチャと実装詳細
- [プロジェクトサマリー](PROJECT_SUMMARY.md) - 成果と改善内容のまとめ

## 🚀 特徴

- **高速処理**: 3段階判定システムにより、不要な処理をスキップ
- **高精度**: 図番号パターン検出により、重要な図表を見逃さない
- **効率的**: ページタイプに応じた最適な処理方法を自動選択
- **日本語対応**: 「図1-1」「表2-3」などの日本語図番号を認識

## 📊 性能

- 処理速度: 約0.5秒/ページ
- 図表検出率: 85%以上
- 処理時間削減: 従来比64%削減

## 🔧 インストール

```bash
# リポジトリのクローン
git clone <repository-url>
cd preprocessing_optimizer

# 依存関係のインストール
pip install -r requirements.txt

# 環境変数の設定（Gemini API使用時）
echo "GEMINI_API_KEY=your_api_key_here" > .env
```

## 📖 使い方

### コマンドライン

```bash
# 単一PDFファイルの処理
python main.py path/to/document.pdf

# ディレクトリ内の全PDFを処理
python main.py path/to/pdf_directory/

# 出力先を指定
python main.py document.pdf -o output_directory/

# カスタム設定を使用
python main.py document.pdf --config custom_config.json
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
├── main.py                    # メインエントリーポイント
├── core/
│   ├── practical_optimizer.py # 最適化エンジン
│   ├── document_parser_gemini.py # Gemini統合
│   ├── smart_page_analyzer.py # ページ分析
│   └── text_processor.py      # テキスト処理
└── config/
    └── config.py             # 設定管理
```

## 🎯 処理タイプ

| ページタイプ | 処理方法 | 用途 |
|------------|---------|------|
| 純粋なテキスト | テキスト抽出のみ | 高速検索 |
| 単純な表 | 構造化データ抽出 | データ分析 |
| 複雑な表 | 画像化+OCR | レイアウト保持 |
| フロー図 | 画像化+ML解析 | 内容理解 |
| 図番号付きページ | 優先的に画像化 | 重要情報保持 |

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