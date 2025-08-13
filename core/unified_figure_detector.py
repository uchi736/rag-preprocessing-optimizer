"""
統合図表検出エンジン - 1回のパスですべての判定を実行
"""

import fitz
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod
import re
import time
from collections import defaultdict


class FigureType(Enum):
    """図表タイプの定義"""
    FLOWCHART = "flowchart"
    TABLE = "table"
    DIAGRAM = "diagram"
    EMBEDDED_IMAGE = "embedded_image"
    COMPLEX_LAYOUT = "complex_layout"
    TEXT_ONLY = "text_only"


@dataclass
class DetectionResult:
    """検出結果を保持するデータクラス"""
    type: FigureType
    confidence: float
    details: Dict[str, Any]
    reasons: List[str]
    complexity: str  # simple/medium/complex


@dataclass
class FigureDetectionResult:
    """統合された図表検出結果"""
    has_figure: bool
    has_table: bool
    has_flowchart: bool
    has_embedded_image: bool
    has_diagram: bool
    primary_type: FigureType
    confidence: float
    complexity: str
    details: Dict[str, Any]
    reasons: List[str]
    processing_time: float


class DetectorPlugin(ABC):
    """検出器プラグインの基底クラス"""
    
    @abstractmethod
    def detect(self, page_data: Dict) -> Optional[DetectionResult]:
        """検出を実行"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """検出器の名前を返す"""
        pass


class FlowchartDetector(DetectorPlugin):
    """フローチャート専用検出器"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.min_arrows = self.config.get('min_arrows_for_flowchart', 2)
        self.min_rects = 3
        
    def detect(self, page_data: Dict) -> Optional[DetectionResult]:
        """フローチャートの検出"""
        drawings = page_data.get('drawings', [])
        text = page_data.get('text', '')
        
        # 図形要素のカウント
        rect_count = sum(1 for d in drawings if d.get('type') == 'r')
        arrow_count = self._detect_arrows(drawings)
        
        # テキストパターンの検出
        flowchart_keywords = ['フローチャート', 'フロー図', 'START', 'END', '判定', '分岐']
        keyword_matches = sum(1 for kw in flowchart_keywords if kw in text)
        
        # フローチャート判定
        if rect_count >= self.min_rects and arrow_count >= self.min_arrows:
            confidence = min(0.6 + (arrow_count * 0.1) + (keyword_matches * 0.05), 1.0)
            return DetectionResult(
                type=FigureType.FLOWCHART,
                confidence=confidence,
                details={
                    'rectangles': rect_count,
                    'arrows': arrow_count,
                    'keywords': keyword_matches
                },
                reasons=[f"フローチャート検出: 矩形{rect_count}個, 矢印{arrow_count}個"],
                complexity='complex' if arrow_count > 5 else 'medium'
            )
        
        return None
    
    def _detect_arrows(self, drawings: List[Dict]) -> int:
        """矢印パターンの検出"""
        lines = [d for d in drawings if d.get('type') == 'l']
        # 簡易版: 線の数から推定
        return len(lines) // 3 if lines else 0
    
    def get_name(self) -> str:
        return "FlowchartDetector"


class TableDetector(DetectorPlugin):
    """テーブル検出器"""
    
    def detect(self, page_data: Dict) -> Optional[DetectionResult]:
        """テーブルの検出"""
        tables = page_data.get('tables', [])
        
        if tables and len(tables) > 0:
            table_count = len(tables)
            return DetectionResult(
                type=FigureType.TABLE,
                confidence=0.9,
                details={'table_count': table_count},
                reasons=[f"テーブルを{table_count}個検出"],
                complexity='simple' if table_count == 1 else 'medium'
            )
        
        return None
    
    def get_name(self) -> str:
        return "TableDetector"


class EmbeddedImageDetector(DetectorPlugin):
    """埋め込み画像検出器"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.min_size = self.config.get('embedded_image_min_size', 100)
    
    def detect(self, page_data: Dict) -> Optional[DetectionResult]:
        """埋め込み画像の検出"""
        images = page_data.get('images', [])
        
        significant_images = []
        for img in images:
            width = img.get('width', 0)
            height = img.get('height', 0)
            if width > self.min_size and height > self.min_size:
                significant_images.append((width, height))
        
        if significant_images:
            return DetectionResult(
                type=FigureType.EMBEDDED_IMAGE,
                confidence=0.95,
                details={
                    'image_count': len(significant_images),
                    'sizes': significant_images
                },
                reasons=[f"埋め込み画像を{len(significant_images)}個検出"],
                complexity='medium'
            )
        
        return None
    
    def get_name(self) -> str:
        return "EmbeddedImageDetector"


class DiagramDetector(DetectorPlugin):
    """一般的なダイアグラム検出器"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.min_shapes = self.config.get('min_combined_shapes', 8)
    
    def detect(self, page_data: Dict) -> Optional[DetectionResult]:
        """ダイアグラムの検出"""
        drawings = page_data.get('drawings', [])
        
        rect_count = sum(1 for d in drawings if d.get('type') == 'r')
        line_count = sum(1 for d in drawings if d.get('type') == 'l')
        curve_count = sum(1 for d in drawings if d.get('type') == 'c')
        total_shapes = rect_count + line_count + curve_count
        
        if total_shapes >= self.min_shapes:
            confidence = min(0.4 + (total_shapes * 0.02), 0.8)
            return DetectionResult(
                type=FigureType.DIAGRAM,
                confidence=confidence,
                details={
                    'total_shapes': total_shapes,
                    'rectangles': rect_count,
                    'lines': line_count,
                    'curves': curve_count
                },
                reasons=[f"ダイアグラム検出: 総要素数{total_shapes}"],
                complexity='complex' if total_shapes > 20 else 'medium'
            )
        
        return None
    
    def get_name(self) -> str:
        return "DiagramDetector"


class UnifiedFigureDetector:
    """統合された図表検出エンジン"""
    
    def __init__(self, config=None):
        self.config = config
        
        # プラグインの登録
        self.detectors = {
            'flowchart': FlowchartDetector(config),
            'table': TableDetector(),
            'embedded_image': EmbeddedImageDetector(config),
            'diagram': DiagramDetector(config)
        }
        
        # キャッシュ
        self._page_cache = {}
    
    def detect_once(self, page: fitz.Page) -> FigureDetectionResult:
        """1回のパスですべての判定を実行"""
        start_time = time.time()
        
        # ページデータのキャッシュを構築
        page_cache = self._build_page_cache(page)
        
        # 並列で各種検出を実行
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for name, detector in self.detectors.items():
                futures[name] = executor.submit(detector.detect, page_cache)
            
            # 結果を収集
            results = {}
            for name, future in futures.items():
                try:
                    result = future.result(timeout=1.0)
                    if result:
                        results[name] = result
                except Exception as e:
                    print(f"検出器 {name} でエラー: {e}")
        
        # 結果を統合
        integrated_result = self._integrate_results(results)
        
        # 処理時間を記録
        integrated_result.processing_time = time.time() - start_time
        
        return integrated_result
    
    def _build_page_cache(self, page: fitz.Page) -> Dict:
        """ページデータのキャッシュを構築"""
        cache = {
            'text': page.get_text(),
            'drawings': [],
            'tables': [],
            'images': []
        }
        
        # 図形要素
        try:
            cache['drawings'] = list(page.get_drawings())
        except:
            pass
        
        # テーブル
        try:
            tables = page.find_tables()
            cache['tables'] = list(tables) if tables else []
        except:
            pass
        
        # 画像
        try:
            image_list = page.get_images(full=True)
            for img in image_list:
                xref = img[0]
                try:
                    base_image = page.parent.extract_image(xref)
                    cache['images'].append({
                        'width': base_image.get('width', 0),
                        'height': base_image.get('height', 0)
                    })
                except:
                    pass
        except:
            pass
        
        return cache
    
    def _integrate_results(self, results: Dict[str, DetectionResult]) -> FigureDetectionResult:
        """検出結果を統合"""
        # 初期化
        integrated = FigureDetectionResult(
            has_figure=False,
            has_table=False,
            has_flowchart=False,
            has_embedded_image=False,
            has_diagram=False,
            primary_type=FigureType.TEXT_ONLY,
            confidence=0.0,
            complexity='simple',
            details={},
            reasons=[],
            processing_time=0.0
        )
        
        # 各検出結果を統合
        max_confidence = 0.0
        primary_result = None
        
        for name, result in results.items():
            # フラグを設定
            if result.type == FigureType.TABLE:
                integrated.has_table = True
            elif result.type == FigureType.FLOWCHART:
                integrated.has_flowchart = True
                integrated.has_figure = True
            elif result.type == FigureType.EMBEDDED_IMAGE:
                integrated.has_embedded_image = True
                integrated.has_figure = True
            elif result.type == FigureType.DIAGRAM:
                integrated.has_diagram = True
                integrated.has_figure = True
            
            # 最も信頼度の高い結果を記録
            if result.confidence > max_confidence:
                max_confidence = result.confidence
                primary_result = result
            
            # 理由を追加
            integrated.reasons.extend(result.reasons)
        
        # プライマリタイプと信頼度を設定
        if primary_result:
            integrated.primary_type = primary_result.type
            integrated.confidence = primary_result.confidence
            integrated.complexity = primary_result.complexity
            integrated.details = primary_result.details
        
        return integrated
    
    def get_metrics(self) -> Dict:
        """メトリクスを取得"""
        metrics = {
            'cache_size': len(self._page_cache),
            'detectors': list(self.detectors.keys()),
            'detector_count': len(self.detectors)
        }
        return metrics