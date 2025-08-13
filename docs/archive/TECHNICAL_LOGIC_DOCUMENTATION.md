# Preprocessing Optimizer 技術ロジック詳細資料

## 1. システム概要

### 1.1 目的
日本語技術文書に特化したPDF前処理システム。図表を含むページを自動検出し、選択的に画像化することで、RAGシステムの精度向上とコスト最適化を実現。

### 1.2 主要コンポーネント
- **PracticalPageAnalyzer**: ページ分析エンジン
- **PracticalDocumentProcessor**: ドキュメント処理エンジン
- **PracticalConfig**: 設定管理

## 2. コア処理ロジック

### 2.1 段階的ページ分析アルゴリズム

#### 段階1: 高速スクリーニング（`_quick_screening`）
```
目的: 高速に純粋なテキストページを識別
```

**処理フロー:**
1. **スキップパターンチェック**
   - 目次、索引、はじめに、奥付などを検出
   - 最初の200文字をチェックして早期判定

2. **テキスト密度計算**
   ```python
   text_density = text_area / page_area
   ```
   - 閾値: 0.8以上 → 純粋なテキストページの可能性大

3. **大型画像検出**
   - 画像サイズ閾値: 50,000ピクセル以上
   - 各画像のPixmapを作成してサイズ確認
   - メモリ効率のため、確認後即座に解放

4. **図番号検出ロジック**
   ```
   図番号パターン:
   - 図\d+[-\.]\d+ (例: 図1-1, 図2.3)
   - 表\d+[-\.]\d+ (例: 表1-1)
   - Fig.\d+[-\.]\d+ (例: Fig.1-1)
   
   参照パターン（実際の図ではない）:
   - 図\d+を参照
   - 図\d+に示す
   - 前述の図\d+
   - については図\d+
   等、15種類のパターン
   ```

5. **実際の図判定アルゴリズム**
   ```python
   if has_figure_number and not has_figure_reference:
       # 3つのパターンで実際の図かチェック
       1. 行頭に図番号（^|\n)\s*図\d+[\s　:]
       2. 独立した行に図番号（^|\n)\s*図\d+\s*(\n|$)
       3. 中央揃えの図番号（^|\n)\s{3,}図\d+(\s|$)
   ```

#### 段階2: 詳細分析（`_detailed_analysis`）

**処理内容:**
1. **PyMuPDF表検出**
   ```python
   tables = page.find_tables()
   for table in tables:
       cell_count = len(table.cells)
   ```

2. **図形要素分析**
   ```python
   drawings = page.get_drawings()
   # 矩形(rect)、線(line)、曲線(curve)をカウント
   ```

3. **テキストパターン分析**
   - ステップパターン: `(STEP|ステップ|手順)\s*[0-9０-９①-⑩]`
   - 番号リスト: `[①-⑩]|[1-9]\.\s`

#### 段階3: 処理方法決定（`_determine_processing`）

**判定ロジックツリー:**
```
1. actual_figure == True?
   YES → 画像化優先
   - 表あり → COMPLEX_TABLE + IMAGE_WITH_OCR
   - 図形/画像あり → FLOWCHART/DIAGRAM + IMAGE_WITH_ANALYSIS
   NO → 次へ

2. text_density > 0.7 AND table_count == 0 AND rect_count < 2?
   YES → PURE_TEXT + TEXT_ONLY
   NO → 次へ

3. table_count > 0?
   YES → 
   - total_cells > 20 → COMPLEX_TABLE + IMAGE_WITH_OCR
   - total_cells <= 20 → SIMPLE_TABLE + STRUCTURED_EXTRACTION
   NO → 次へ

4. rect_count >= 3 AND (step_pattern OR line_count > 5)?
   YES → FLOWCHART + IMAGE_WITH_ANALYSIS
   NO → 次へ

5. large_images_count > 0?
   YES → DIAGRAM + IMAGE_WITH_ANALYSIS
   NO → 次へ

6. rect_count > 0 OR line_count > 10?
   YES → MIXED + HYBRID
   NO → PURE_TEXT + TEXT_ONLY (デフォルト)
```

### 2.2 並列処理アーキテクチャ

**実装方式:**
```python
ThreadPoolExecutor(max_workers=min(cpu_count(), 8))
```

**並列化戦略:**
1. 各ページを独立したタスクとして処理
2. スレッドごとに独立したPyMuPDFドキュメントオブジェクトを作成
3. 結果は非同期で収集し、最後にページ番号順でソート

**スレッドセーフティ:**
- 各スレッドが独自のドキュメントインスタンスを使用
- 共有リソースへのアクセスなし
- 結果の集約のみスレッド間で同期

### 2.3 メモリ管理戦略

1. **Pixmapオブジェクト管理**
   ```python
   pix = page.get_pixmap(matrix=mat)
   try:
       # 処理
   finally:
       pix = None  # 明示的な解放
   ```

2. **PIL Image管理**
   ```python
   with Image.open(io.BytesIO(img_data)) as img:
       # コンテキストマネージャで自動解放
   ```

3. **大規模PDF対策**
   - ページ単位で処理（全体をメモリに保持しない）
   - 処理済みページのリソースは即座に解放

## 3. コスト最適化ロジック

### 3.1 処理コストモデル
```python
コスト定義:
- TEXT_ONLY: 0.1
- STRUCTURED_EXTRACTION: 0.3
- IMAGE_WITH_OCR: 1.0
- IMAGE_WITH_ANALYSIS: 1.5
- HYBRID: 0.7
```

### 3.2 ROI計算
```python
def calculate_roi(results):
    text_accuracy = 0.8
    image_accuracy = 0.95
    
    text_value = text_pages * text_accuracy
    image_value = image_pages * image_accuracy
    
    roi = (total_value - total_cost) / total_cost
```

## 4. 設定パラメータの影響

### 4.1 重要な閾値
| パラメータ | デフォルト値 | 影響 |
|----------|------------|-----|
| quick_text_density_threshold | 0.8 | 高い値→より多くのページをテキストと判定 |
| min_table_cells | 6 | 低い値→より多くの構造を表と認識 |
| complex_table_cell_threshold | 20 | 高い値→複雑な表の判定基準が厳しくなる |
| high_confidence_threshold | 0.8 | 判定の信頼度基準 |

### 4.2 画像化設定
- **image_dpi_multiplier**: 画像品質とファイルサイズのトレードオフ
  - 1.0: 低品質・小サイズ
  - 2.0: 標準品質（デフォルト）
  - 3.0以上: 高品質・大サイズ

## 5. エラーハンドリング戦略

### 5.1 エラーレベル
1. **ページレベルエラー**: 個別ページの処理失敗
   - 該当ページをスキップし、処理を継続
   - エラー情報を記録

2. **ドキュメントレベルエラー**: PDF全体の処理失敗
   - 部分的な結果でも返却
   - エラー詳細を含む結果オブジェクト生成

3. **システムレベルエラー**: 致命的エラー
   - 適切なエラーメッセージ表示
   - --verboseオプションでスタックトレース表示

### 5.2 リカバリー機構
- 並列処理での個別スレッド失敗は他に影響しない
- メモリ不足時は自動的にリソース解放を試行
- 中断時（Ctrl+C）は適切にクリーンアップ

## 6. パフォーマンス特性

### 6.1 時間複雑度
- ページ分析: O(n) - nはページ数
- 並列処理時: O(n/p) - pは並列度

### 6.2 空間複雑度
- メモリ使用量: O(1) - ページ単位で処理
- 一時ファイル: O(m) - mは画像化されたページ数

### 6.3 最適化のトレードオフ
| 設定 | 処理速度 | メモリ使用 | 精度 |
|-----|---------|-----------|-----|
| 並列処理ON | 高速 | 高 | 同一 |
| 高DPI倍率 | 低速 | 高 | 高 |
| 厳密な図検出 | 中速 | 低 | 高 |