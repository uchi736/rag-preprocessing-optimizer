"""
実用的な前処理最適化システム
- 選択的な画像化
- 段階的な判定
- コスト効率を重視
"""

import fitz
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import numpy as np
from enum import Enum
import json
import os
from datetime import datetime
from PIL import Image
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

class PageType(Enum):
    """ページタイプの定義"""
    PURE_TEXT = "pure_text"          # 純粋なテキスト
    SIMPLE_TABLE = "simple_table"    # 単純な表
    COMPLEX_TABLE = "complex_table"  # 複雑な表
    FLOWCHART = "flowchart"          # フロー図
    DIAGRAM = "diagram"              # その他の図
    MIXED = "mixed"                  # 混在型

class ProcessingMethod(Enum):
    """処理方法の定義"""
    TEXT_ONLY = "text_only"              # テキスト抽出のみ
    STRUCTURED_EXTRACTION = "structured"  # 構造化データ抽出
    IMAGE_WITH_GEMINI = "image_gemini"  # 画像化+Gemini解析
    IMAGE_WITH_ANALYSIS = "image_ml"     # 画像化+ML解析
    HYBRID = "hybrid"                    # ハイブリッド

@dataclass
class PracticalConfig:
    """実用的な設定"""
    # 段階1: 高速スクリーニング
    quick_text_density_threshold: float = 0.8   # テキスト密度が高い→テキストページ
    quick_image_size_threshold: int = 50000     # 大きな画像がある→図表ページ
    
    # 段階2: 詳細分析
    min_table_cells: int = 6                    # 表と判定する最小セル数
    min_flow_nodes: int = 3                     # フロー図の最小ノード数
    complex_table_cell_threshold: int = 20      # 複雑な表のセル数閾値
    
    # 段階3: 信頼度閾値
    high_confidence_threshold: float = 0.8      # 高信頼度
    medium_confidence_threshold: float = 0.6    # 中信頼度
    
    # コスト設定
    text_processing_cost: float = 0.1           # テキスト処理コスト
    image_processing_cost: float = 1.0          # 画像処理コスト
    structured_extraction_cost: float = 0.3     # 構造化抽出コスト
    
    # 実用設定
    force_image_keywords: List[str] = None      # これらのキーワードがあれば画像化
    skip_page_patterns: List[str] = None        # スキップするページパターン
    figure_number_patterns: List[str] = None    # 図番号パターン
    image_dpi_multiplier: float = 2.0           # 画像化時のDPI倍率（デフォルト2倍）

    def __post_init__(self):
        if self.force_image_keywords is None:
            self.force_image_keywords = ['フロー図', 'ブロック図', '配線図', '回路図']
        if self.skip_page_patterns is None:
            self.skip_page_patterns = []  # スキップ機能を無効化
        if self.figure_number_patterns is None:
            # 日本語の図番号パターン
            self.figure_number_patterns = [
                r'図\s*\d+[-\.]\d+',     # 図1-1, 図2.3
                r'図\s*\d+',             # 図1
                r'図表\s*\d+[-\.]\d+',   # 図表1-1
                r'表\s*\d+[-\.]\d+',     # 表1-1
                r'Fig\.\s*\d+[-\.]\d+',  # Fig.1-1
                r'Figure\s*\d+[-\.]\d+', # Figure 1-1
            ]

class PracticalPageAnalyzer:
    """実用的なページ分析器"""
    
    def __init__(self, config: PracticalConfig = None):
        self.config = config or PracticalConfig()
        self.stats = {
            'analyzed_pages': 0,
            'text_pages': 0,
            'figure_pages': 0,
            'skipped_pages': 0
        }
    
    def analyze_page(self, page: fitz.Page, page_num: int) -> Dict:
        """段階的なページ分析"""
        self.stats['analyzed_pages'] += 1
        
        # 段階1: 高速スクリーニング
        quick_result = self._quick_screening(page, page_num)
        if quick_result['skip']:
            self.stats['skipped_pages'] += 1
            return {
                'page_type': PageType.PURE_TEXT,
                'processing_method': ProcessingMethod.TEXT_ONLY,
                'confidence': 1.0,
                'skip': True,
                'reason': quick_result['reason']
            }
        
        if quick_result['is_pure_text']:
            self.stats['text_pages'] += 1
            return {
                'page_type': PageType.PURE_TEXT,
                'processing_method': ProcessingMethod.TEXT_ONLY,
                'confidence': quick_result['confidence'],
                'features': quick_result['features']
            }
        
        # 段階2: 詳細分析
        detailed_result = self._detailed_analysis(page)
        
        # 段階3: 最適な処理方法の決定
        page_type, processing_method, confidence = self._determine_processing(
            quick_result, detailed_result
        )
        
        if page_type != PageType.PURE_TEXT:
            self.stats['figure_pages'] += 1
        else:
            self.stats['text_pages'] += 1
        
        return {
            'page_type': page_type,
            'processing_method': processing_method,
            'confidence': confidence,
            'features': {**quick_result['features'], **detailed_result},
            'cost_estimate': self._estimate_cost(processing_method)
        }
    
    def _quick_screening(self, page: fitz.Page, page_num: int) -> Dict:
        """高速スクリーニング"""
        text = page.get_text()
        page_area = page.rect.width * page.rect.height
        
        # スキップパターンのチェック
        for pattern in self.config.skip_page_patterns:
            if pattern in text[:200]:  # 最初の200文字をチェック
                return {
                    'skip': True,
                    'reason': f'スキップパターン: {pattern}'
                }
        
        # テキスト密度の計算
        text_dict = page.get_text("dict")
        text_blocks = [b for b in text_dict.get('blocks', []) if b.get('type') == 0]
        text_area = sum(
            abs((b['bbox'][2] - b['bbox'][0]) * (b['bbox'][3] - b['bbox'][1]))
            for b in text_blocks
        )
        text_density = text_area / page_area if page_area > 0 else 0
        
        # 画像の確認
        images = page.get_images()
        large_images = []
        for img in images:
            xref = img[0]
            pix = None
            try:
                pix = fitz.Pixmap(page.parent, xref)
                if pix.width * pix.height > self.config.quick_image_size_threshold:
                    large_images.append((pix.width, pix.height))
            except:
                pass
            finally:
                # Pixmapのメモリを解放
                if pix:
                    pix = None
        
        # 強制画像化キーワードのチェック
        has_force_keywords = any(kw in text for kw in self.config.force_image_keywords)
        
        # 図番号パターンのチェック
        import re
        has_figure_number = False
        has_figure_reference = False
        
        # 図番号参照パターン（実際の図ではない）
        reference_patterns = [
            r'図\s*\d+[-\.]\d+\s*の通り',
            r'図\s*\d+[-\.]\d+\s*を参照',
            r'図\s*\d+[-\.]\d+\s*に示す',
            r'図\s*\d+[-\.]\d+\s*参照',
            r'図\s*\d+\s*の通り',
            r'図\s*\d+\s*を参照',
            r'参考.*図\s*\d+',
            r'前述の図\s*\d+',
            r'次の図\s*\d+',
            r'上記の図\s*\d+',
            r'下記の図\s*\d+',
            r'図\s*\d+[-\.]\d+\s*より',
            r'図\s*\d+[-\.]\d+\s*から',
            r'図\s*\d+[-\.]\d+\s*で示',
            r'については図\s*\d+',
        ]
        
        # まず参照パターンをチェック
        for pattern in reference_patterns:
            if re.search(pattern, text):
                has_figure_reference = True
                break
        
        # 図番号パターンをチェック
        for pattern in self.config.figure_number_patterns:
            if re.search(pattern, text):
                has_figure_number = True
                break
        
        # 実際の図のキャプションかどうかを判定
        actual_figure = False
        if has_figure_number and not has_figure_reference:
            # 図番号が行頭にあるか、独立した行にあるかチェック
            for pattern in self.config.figure_number_patterns:
                # パターン1: 行頭に図番号がある（図番号の後にキャプションが続く）
                if re.search(r'(?:^|\n)\s*' + pattern + r'[\s　:]', text, re.MULTILINE):
                    actual_figure = True
                    break
                # パターン2: 図番号が独立した行にある
                if re.search(r'(?:^|\n)\s*' + pattern + r'\s*(?:\n|$)', text, re.MULTILINE):
                    actual_figure = True
                    break
                # パターン3: 中央揃えや特殊なフォーマットの図番号
                if re.search(r'(?:^|\n)\s{3,}' + pattern + r'(?:\s|$)', text, re.MULTILINE):
                    actual_figure = True
                    break
        
        # 判定
        is_pure_text = (
            text_density > self.config.quick_text_density_threshold and
            len(large_images) == 0 and
            not has_force_keywords and
            not actual_figure  # 実際の図がある場合のみ画像化
        )
        
        return {
            'skip': False,
            'is_pure_text': is_pure_text,
            'confidence': 0.9 if is_pure_text else 0.5,
            'features': {
                'text_density': text_density,
                'large_images_count': len(large_images),
                'has_force_keywords': has_force_keywords,
                'has_figure_number': has_figure_number,
                'has_figure_reference': has_figure_reference,
                'actual_figure': actual_figure
            }
        }
    
    def _detailed_analysis(self, page: fitz.Page) -> Dict:
        """詳細分析（SmartPageAnalyzerの優れた機能を統合）"""
        # PyMuPDFの表検出
        try:
            tables = list(page.find_tables())
            table_info = []
            for table in tables:
                try:
                    # セル数の計算
                    cells = table.cells
                    cell_count = len(cells) if cells else 0
                    table_info.append({
                        'cell_count': cell_count,
                        'bbox': table.bbox
                    })
                except:
                    pass
        except:
            tables = []
            table_info = []
        
        # 図形要素の分析（改良版）
        drawings = list(page.get_drawings())
        rect_count = 0
        line_count = 0
        curve_count = 0
        arrow_patterns = 0
        
        for d in drawings:
            d_type = d.get('type')
            if d_type == 'r':  # rectangle
                rect_count += 1
            elif d_type == 'l':  # line
                line_count += 1
            elif d_type == 'c':  # curve
                curve_count += 1
            
            # 矢印パターンの簡易検出
            items = d.get('items', [])
            if len(items) > 2:  # 複数の線が接続
                arrow_patterns += 1
        
        # 視覚要素の存在確認（SmartPageAnalyzerから統合）
        has_visual_element = (
            rect_count > 0 or 
            line_count > 0 or 
            len(tables) > 0
        )
        
        # 埋め込み画像の確認
        significant_images = 0
        try:
            image_list = page.get_images(full=True)
            for img in image_list:
                xref = img[0]
                try:
                    base_image = page.parent.extract_image(xref)
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    if width > 100 and height > 100:  # 100px以上を有意な画像とする
                        significant_images += 1
                        has_visual_element = True
                except:
                    pass
        except:
            pass
        
        # テキストパターンの分析（拡張版）
        text = page.get_text()
        import re
        has_step_pattern = bool(re.search(r'(STEP|ステップ|手順|Phase|フェーズ|工程)\s*[0-9０-９①-⑩]', text))
        has_number_list = bool(re.search(r'[①-⑩]|[1-9]\.\s', text))
        has_arrow_text = len(re.findall(r'[→←↑↓⇒⇐⇑⇓➡⬅⬆⬇]', text)) >= 3
        
        return {
            'tables': table_info,
            'table_count': len(tables),
            'total_cells': sum(t['cell_count'] for t in table_info),
            'rect_count': rect_count,
            'line_count': line_count,
            'curve_count': curve_count,
            'arrow_patterns': arrow_patterns,
            'has_step_pattern': has_step_pattern,
            'has_number_list': has_number_list,
            'has_arrow_text': has_arrow_text,
            'has_visual_element': has_visual_element,
            'significant_images': significant_images
        }
    
    def _determine_processing(self, quick_result: Dict, detailed_result: Dict) -> Tuple[PageType, ProcessingMethod, float]:
        """最適な処理方法の決定（視覚要素チェック統合）"""
        features = quick_result['features']
        
        # 視覚要素がない場合は図表なしと判定（誤検知防止）
        if not detailed_result.get('has_visual_element', False):
            # キーワードのみの場合は参照文として扱う
            if features.get('has_figure_number', False):
                # 参照文はテキストとして処理
                return PageType.PURE_TEXT, ProcessingMethod.TEXT_ONLY, 0.9
        
        # 実際の図がある場合は優先的に画像化
        if features.get('actual_figure', False) and detailed_result.get('has_visual_element', False):
            # 表の可能性をチェック
            if detailed_result['table_count'] > 0:
                return PageType.COMPLEX_TABLE, ProcessingMethod.IMAGE_WITH_GEMINI, 0.85
            # フロー図または図の可能性
            elif detailed_result['rect_count'] > 0 or features['large_images_count'] > 0:
                return PageType.FLOWCHART, ProcessingMethod.IMAGE_WITH_ANALYSIS, 0.8
            else:
                return PageType.DIAGRAM, ProcessingMethod.IMAGE_WITH_ANALYSIS, 0.75
        
        # 純粋なテキスト（再確認）
        if (features['text_density'] > 0.7 and 
            detailed_result['table_count'] == 0 and
            detailed_result['rect_count'] < 2):
            return PageType.PURE_TEXT, ProcessingMethod.TEXT_ONLY, 0.9
        
        # 表の判定
        if detailed_result['table_count'] > 0:
            total_cells = detailed_result['total_cells']
            if total_cells > self.config.complex_table_cell_threshold:
                return PageType.COMPLEX_TABLE, ProcessingMethod.IMAGE_WITH_GEMINI, 0.85
            else:
                return PageType.SIMPLE_TABLE, ProcessingMethod.STRUCTURED_EXTRACTION, 0.8
        
        # フロー図の判定
        if (detailed_result['rect_count'] >= self.config.min_flow_nodes and
            (detailed_result['has_step_pattern'] or detailed_result['line_count'] > 5)):
            return PageType.FLOWCHART, ProcessingMethod.IMAGE_WITH_ANALYSIS, 0.75
        
        # 図の判定
        if features['large_images_count'] > 0:
            return PageType.DIAGRAM, ProcessingMethod.IMAGE_WITH_ANALYSIS, 0.8
        
        # 混在型
        if detailed_result['rect_count'] > 0 or detailed_result['line_count'] > 10:
            return PageType.MIXED, ProcessingMethod.HYBRID, 0.6
        
        # デフォルト
        return PageType.PURE_TEXT, ProcessingMethod.TEXT_ONLY, 0.5
    
    def _estimate_cost(self, method: ProcessingMethod) -> float:
        """処理コストの見積もり"""
        cost_map = {
            ProcessingMethod.TEXT_ONLY: self.config.text_processing_cost,
            ProcessingMethod.STRUCTURED_EXTRACTION: self.config.structured_extraction_cost,
            ProcessingMethod.IMAGE_WITH_GEMINI: self.config.image_processing_cost,
            ProcessingMethod.IMAGE_WITH_ANALYSIS: self.config.image_processing_cost * 1.5,
            ProcessingMethod.HYBRID: (self.config.text_processing_cost + 
                                    self.config.image_processing_cost) * 0.7
        }
        return cost_map.get(method, 1.0)

class PracticalDocumentProcessor:
    """実用的なドキュメント処理器"""
    
    def __init__(self, config: PracticalConfig = None):
        self.analyzer = PracticalPageAnalyzer(config)
        self.config = config or PracticalConfig()
        self.max_workers = min(multiprocessing.cpu_count(), 8)  # 最大8スレッドに制限
    
    def process_pdf(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict:
        """PDFの実用的な処理"""
        start_time = datetime.now()
        doc = fitz.open(pdf_path)
        
        results = {
            'pdf_path': pdf_path,
            'total_pages': doc.page_count,
            'processed_pages': [],
            'summary': {
                'text_pages': 0,
                'image_pages': 0,
                'hybrid_pages': 0,
                'skipped_pages': 0,
                'total_cost': 0
            }
        }
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            # ページ分析
            analysis = self.analyzer.analyze_page(page, page_num)
            
            # スキップページ
            if analysis.get('skip', False):
                results['summary']['skipped_pages'] += 1
                print(f"ページ {page_num + 1}: スキップ - {analysis['reason']}")
                continue
            
            # 処理方法に応じた処理
            page_result = self._process_page(page, page_num, analysis, output_dir)
            results['processed_pages'].append(page_result)
            
            # サマリー更新
            if analysis['processing_method'] == ProcessingMethod.TEXT_ONLY:
                results['summary']['text_pages'] += 1
            elif analysis['processing_method'] in [ProcessingMethod.IMAGE_WITH_GEMINI, 
                                                  ProcessingMethod.IMAGE_WITH_ANALYSIS]:
                results['summary']['image_pages'] += 1
            else:
                results['summary']['hybrid_pages'] += 1
            
            results['summary']['total_cost'] += analysis['cost_estimate']
            
            # 進捗表示
            method = analysis['processing_method'].value
            confidence = analysis['confidence']
            print(f"ページ {page_num + 1}: {method} (信頼度: {confidence:.2f})")
        
        doc.close()
        
        # 処理時間
        results['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        # 統計情報
        results['analyzer_stats'] = self.analyzer.stats
        
        # 結果を保存
        if output_dir:
            summary_path = os.path.join(output_dir, 'processing_summary.json')
            with open(summary_path, 'w', encoding='utf-8') as f:
                # PIL Imageオブジェクトを除外してJSON保存
                json_safe = self._make_json_safe(results)
                json.dump(json_safe, f, ensure_ascii=False, indent=2)
        
        return results
    
    def process_pdf_parallel(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict:
        """PDFの並列処理による高速化"""
        start_time = datetime.now()
        doc = fitz.open(pdf_path)
        
        results = {
            'pdf_path': pdf_path,
            'total_pages': doc.page_count,
            'processed_pages': [],
            'summary': {
                'text_pages': 0,
                'image_pages': 0,
                'hybrid_pages': 0,
                'skipped_pages': 0,
                'total_cost': 0
            }
        }
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # ページ処理タスクを準備
        page_tasks = []
        for page_num in range(doc.page_count):
            page_tasks.append((page_num, doc))
        
        # 並列処理
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 各ページの処理をサブミット
            future_to_page = {}
            for page_num, _ in page_tasks:
                future = executor.submit(self._process_page_parallel, pdf_path, page_num, output_dir)
                future_to_page[future] = page_num
            
            # 結果を収集
            for future in as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    page_result = future.result()
                    if page_result:
                        results['processed_pages'].append(page_result)
                        
                        # サマリー更新
                        if 'skip' in page_result and page_result['skip']:
                            results['summary']['skipped_pages'] += 1
                        elif page_result['processing_method'] == ProcessingMethod.TEXT_ONLY.value:
                            results['summary']['text_pages'] += 1
                        elif page_result['processing_method'] in [ProcessingMethod.IMAGE_WITH_GEMINI.value, 
                                                                  ProcessingMethod.IMAGE_WITH_ANALYSIS.value]:
                            results['summary']['image_pages'] += 1
                        else:
                            results['summary']['hybrid_pages'] += 1
                        
                        if 'cost_estimate' in page_result:
                            results['summary']['total_cost'] += page_result['cost_estimate']
                except Exception as e:
                    print(f"ページ {page_num + 1} の処理中にエラー: {str(e)}")
        
        doc.close()
        
        # ページ番号順にソート
        results['processed_pages'].sort(key=lambda x: x.get('page_number', 0))
        
        # 処理時間
        results['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        # 統計情報
        results['analyzer_stats'] = self.analyzer.stats
        
        # 結果を保存
        if output_dir:
            summary_path = os.path.join(output_dir, 'processing_summary.json')
            with open(summary_path, 'w', encoding='utf-8') as f:
                json_safe = self._make_json_safe(results)
                json.dump(json_safe, f, ensure_ascii=False, indent=2)
        
        return results
    
    def _process_page_parallel(self, pdf_path: str, page_num: int, output_dir: Optional[str]) -> Optional[Dict]:
        """並列処理用のページ処理メソッド"""
        try:
            # 各スレッドで独立してドキュメントを開く
            doc = fitz.open(pdf_path)
            page = doc[page_num]
            
            # ページ分析
            analysis = self.analyzer.analyze_page(page, page_num)
            
            # スキップページ
            if analysis.get('skip', False):
                print(f"ページ {page_num + 1}: スキップ - {analysis['reason']}")
                doc.close()
                return {
                    'page_number': page_num + 1,
                    'skip': True,
                    'reason': analysis['reason']
                }
            
            # 処理方法に応じた処理
            page_result = self._process_page(page, page_num, analysis, output_dir)
            
            # 進捗表示
            method = analysis['processing_method'].value
            confidence = analysis['confidence']
            print(f"ページ {page_num + 1}: {method} (信頼度: {confidence:.2f})")
            
            doc.close()
            return page_result
            
        except Exception as e:
            print(f"ページ {page_num + 1} の処理エラー: {str(e)}")
            return None
    
    def _process_page(self, page: fitz.Page, page_num: int, 
                     analysis: Dict, output_dir: Optional[str]) -> Dict:
        """ページの処理"""
        result = {
            'page_number': page_num + 1,
            'page_type': analysis['page_type'].value,
            'processing_method': analysis['processing_method'].value,
            'confidence': analysis['confidence'],
            'features': analysis.get('features', {})
        }
        
        method = analysis['processing_method']
        
        # テキスト処理
        if method in [ProcessingMethod.TEXT_ONLY, ProcessingMethod.STRUCTURED_EXTRACTION]:
            result['text'] = page.get_text()
            
            # 構造化抽出
            if method == ProcessingMethod.STRUCTURED_EXTRACTION:
                tables = list(page.find_tables())
                result['structured_data'] = []
                for table in tables:
                    try:
                        df = table.to_pandas()
                        result['structured_data'].append({
                            'type': 'table',
                            'data': df.to_dict('records')
                        })
                    except:
                        pass
        
        # 画像処理
        if method in [ProcessingMethod.IMAGE_WITH_GEMINI, ProcessingMethod.IMAGE_WITH_ANALYSIS, 
                     ProcessingMethod.HYBRID]:
            # 画像化
            dpi_mult = getattr(self.config, 'image_dpi_multiplier', 2.0)
            mat = fitz.Matrix(dpi_mult, dpi_mult)  # 設定可能な解像度
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            try:
                with Image.open(io.BytesIO(img_data)) as img:
                    result['image_size'] = img.size
                    
                    # 保存
                    if output_dir:
                        img_filename = f"page_{page_num+1:03d}_{analysis['page_type'].value}.png"
                        img_path = os.path.join(output_dir, img_filename)
                        img.save(img_path)
                        result['image_path'] = img_path
            finally:
                # Pixmapのメモリを解放
                pix = None
            
            # ハイブリッドの場合はテキストも抽出
            if method == ProcessingMethod.HYBRID:
                result['text'] = page.get_text()
        
        return result
    
    def _make_json_safe(self, obj):
        """JSONシリアライズ可能な形式に変換"""
        if isinstance(obj, dict):
            return {k: self._make_json_safe(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_safe(v) for v in obj]
        elif isinstance(obj, Image.Image):
            return f"<PIL Image {obj.size}>"
        elif hasattr(obj, '__dict__'):
            return str(obj)
        else:
            return obj

def calculate_roi(results: Dict) -> Dict:
    """投資対効果（ROI）の計算"""
    summary = results['summary']
    
    # 仮定：画像処理により抽出精度が向上
    text_accuracy = 0.8
    image_accuracy = 0.95
    
    text_value = summary['text_pages'] * text_accuracy
    image_value = summary['image_pages'] * image_accuracy
    hybrid_value = summary['hybrid_pages'] * 0.9
    
    total_value = text_value + image_value + hybrid_value
    total_cost = summary['total_cost']
    
    roi = (total_value - total_cost) / total_cost if total_cost > 0 else 0
    
    return {
        'total_value': total_value,
        'total_cost': total_cost,
        'roi': roi,
        'cost_per_page': total_cost / results['total_pages'] if results['total_pages'] > 0 else 0
    }