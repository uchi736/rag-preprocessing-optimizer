"""
図表領域をピンポイントで切り出してGemini解析するプロセッサ
"""

import fitz
import os
import json
import base64
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

from core.practical_optimizer import (
    PracticalDocumentProcessor,
    PracticalConfig,
    ProcessingMethod,
    PageType
)


@dataclass
class FigureRegion:
    """図表領域の情報"""
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    type: str  # 'table', 'image', 'figure', 'chart'
    confidence: float  # 検出の信頼度
    page_num: int
    index: int  # ページ内でのインデックス
    caption: Optional[str] = None
    
    @property
    def area(self) -> float:
        """領域の面積"""
        return abs((self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1]))
    
    def expand(self, margin: int = 10) -> Tuple[float, float, float, float]:
        """マージンを追加したbboxを返す"""
        return (
            self.bbox[0] - margin,
            self.bbox[1] - margin,
            self.bbox[2] + margin,
            self.bbox[3] + margin
        )


class RegionBasedProcessor(PracticalDocumentProcessor):
    """
    図表領域をピンポイントで切り出して処理するプロセッサ
    """
    
    def __init__(self, config: Optional[PracticalConfig] = None):
        super().__init__(config)
        self.region_margin = 10  # 切り出し時のマージン（ピクセル）
        self.min_figure_area = 5000  # 最小図表面積（ピクセル^2）
        self.cluster_threshold = 50  # 図形クラスタリングの距離閾値
        
    def extract_region(self, page: fitz.Page, bbox: Tuple[float, float, float, float], 
                      margin: int = None) -> fitz.Pixmap:
        """
        特定領域をピンポイントで画像化
        
        Args:
            page: PDFページ
            bbox: 切り出し領域 (x0, y0, x1, y1)
            margin: 追加マージン（ピクセル）
            
        Returns:
            切り出された画像のPixmap
        """
        if margin is None:
            margin = self.region_margin
            
        # 切り出し範囲を定義（マージン付き）
        clip_rect = fitz.Rect(
            max(0, bbox[0] - margin),
            max(0, bbox[1] - margin),
            min(page.rect.width, bbox[2] + margin),
            min(page.rect.height, bbox[3] + margin)
        )
        
        # 高解像度で領域を画像化
        mat = fitz.Matrix(self.config.image_dpi_multiplier, self.config.image_dpi_multiplier)
        pix = page.get_pixmap(matrix=mat, clip=clip_rect)
        
        return pix
    
    def detect_figure_regions(self, page: fitz.Page, page_num: int) -> List[FigureRegion]:
        """
        ページ内のすべての図表領域を検出
        
        Args:
            page: PDFページ
            page_num: ページ番号（0ベース）
            
        Returns:
            検出された図表領域のリスト
        """
        regions = []
        
        # 1. 表領域の検出
        try:
            tables = list(page.find_tables())
            for idx, table in enumerate(tables):
                if table.bbox:
                    region = FigureRegion(
                        bbox=table.bbox,
                        type='table',
                        confidence=0.9,
                        page_num=page_num,
                        index=idx
                    )
                    if region.area > self.min_figure_area:
                        regions.append(region)
        except:
            pass
        
        # 2. 埋め込み画像の検出
        try:
            image_list = page.get_images(full=True)
            for idx, img in enumerate(image_list):
                xref = img[0]
                try:
                    # 画像の位置情報を取得
                    img_bbox = page.get_image_bbox(img)
                    if img_bbox:
                        bbox = (img_bbox.x0, img_bbox.y0, img_bbox.x1, img_bbox.y1)
                        region = FigureRegion(
                            bbox=bbox,
                            type='image',
                            confidence=0.95,
                            page_num=page_num,
                            index=idx
                        )
                        if region.area > self.min_figure_area:
                            regions.append(region)
                except:
                    pass
        except:
            pass
        
        # 3. 図形クラスタの検出（フローチャート、ダイアグラム等）
        figure_clusters = self._detect_figure_clusters(page)
        for idx, cluster_bbox in enumerate(figure_clusters):
            region = FigureRegion(
                bbox=cluster_bbox,
                type='figure',
                confidence=0.7,
                page_num=page_num,
                index=idx
            )
            if region.area > self.min_figure_area:
                regions.append(region)
        
        # 4. 重複領域のマージ
        regions = self._merge_overlapping_regions(regions)
        
        # 5. キャプションの検出（オプション）
        regions = self._detect_captions(page, regions)
        
        return regions
    
    def _detect_figure_clusters(self, page: fitz.Page) -> List[Tuple[float, float, float, float]]:
        """
        近接する図形要素をクラスタリングして図表領域を検出
        
        Args:
            page: PDFページ
            
        Returns:
            クラスタのbboxリスト
        """
        clusters = []
        drawings = list(page.get_drawings())
        
        if len(drawings) < 3:  # 図形が少ない場合はスキップ
            return clusters
        
        # 図形要素のbboxを収集
        shape_bboxes = []
        for d in drawings:
            items = d.get('items', [])
            if items:
                # 図形の外接矩形を計算
                xs = []
                ys = []
                for item in items:
                    if item[0] in ['l', 'c']:  # line or curve
                        p1 = item[1]
                        p2 = item[2]
                        xs.extend([p1.x, p2.x])
                        ys.extend([p1.y, p2.y])
                
                if xs and ys:
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    shape_bboxes.append(bbox)
        
        # 近接する図形をクラスタリング（簡易版）
        if shape_bboxes:
            # 最初の図形から開始
            current_cluster = shape_bboxes[0]
            
            for bbox in shape_bboxes[1:]:
                # 現在のクラスタと近接しているか判定
                if self._are_bboxes_close(current_cluster, bbox, self.cluster_threshold):
                    # クラスタを拡張
                    current_cluster = self._merge_bboxes(current_cluster, bbox)
                else:
                    # 新しいクラスタとして追加
                    if self._get_bbox_area(current_cluster) > self.min_figure_area:
                        clusters.append(current_cluster)
                    current_cluster = bbox
            
            # 最後のクラスタを追加
            if self._get_bbox_area(current_cluster) > self.min_figure_area:
                clusters.append(current_cluster)
        
        return clusters
    
    def _are_bboxes_close(self, bbox1: Tuple, bbox2: Tuple, threshold: float) -> bool:
        """2つのbboxが近接しているか判定"""
        # 中心点間の距離で判定
        center1 = ((bbox1[0] + bbox1[2]) / 2, (bbox1[1] + bbox1[3]) / 2)
        center2 = ((bbox2[0] + bbox2[2]) / 2, (bbox2[1] + bbox2[3]) / 2)
        
        distance = ((center1[0] - center2[0]) ** 2 + (center1[1] - center2[1]) ** 2) ** 0.5
        return distance < threshold
    
    def _merge_bboxes(self, bbox1: Tuple, bbox2: Tuple) -> Tuple:
        """2つのbboxをマージ"""
        return (
            min(bbox1[0], bbox2[0]),
            min(bbox1[1], bbox2[1]),
            max(bbox1[2], bbox2[2]),
            max(bbox1[3], bbox2[3])
        )
    
    def _get_bbox_area(self, bbox: Tuple) -> float:
        """bboxの面積を計算"""
        return abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    
    def _merge_overlapping_regions(self, regions: List[FigureRegion]) -> List[FigureRegion]:
        """
        重複する領域をマージ
        
        Args:
            regions: 図表領域のリスト
            
        Returns:
            マージ後の領域リスト
        """
        if len(regions) <= 1:
            return regions
        
        merged = []
        used = set()
        
        for i, region1 in enumerate(regions):
            if i in used:
                continue
                
            merged_bbox = region1.bbox
            merged_type = region1.type
            
            for j, region2 in enumerate(regions[i+1:], i+1):
                if j in used:
                    continue
                    
                # 重複判定
                if self._do_bboxes_overlap(region1.bbox, region2.bbox):
                    merged_bbox = self._merge_bboxes(merged_bbox, region2.bbox)
                    used.add(j)
                    # より信頼度の高いタイプを採用
                    if region2.confidence > region1.confidence:
                        merged_type = region2.type
            
            merged.append(FigureRegion(
                bbox=merged_bbox,
                type=merged_type,
                confidence=region1.confidence,
                page_num=region1.page_num,
                index=len(merged)
            ))
        
        return merged
    
    def _do_bboxes_overlap(self, bbox1: Tuple, bbox2: Tuple) -> bool:
        """2つのbboxが重複しているか判定"""
        return not (bbox1[2] < bbox2[0] or bbox2[2] < bbox1[0] or
                   bbox1[3] < bbox2[1] or bbox2[3] < bbox1[1])
    
    def _detect_captions(self, page: fitz.Page, regions: List[FigureRegion]) -> List[FigureRegion]:
        """
        図表のキャプションを検出（簡易版）
        
        Args:
            page: PDFページ
            regions: 図表領域のリスト
            
        Returns:
            キャプション付きの領域リスト
        """
        import re
        text = page.get_text()
        
        # 図番号パターン
        caption_patterns = [
            r'図\s*\d+[-\.]\d+\s*[：:]\s*(.+)',
            r'図\s*\d+\s*[：:]\s*(.+)',
            r'表\s*\d+[-\.]\d+\s*[：:]\s*(.+)',
            r'Fig\.\s*\d+[-\.]\d+\s*[：:]\s*(.+)',
        ]
        
        for region in regions:
            # 図表の下部付近のテキストを探索
            caption_area = (
                region.bbox[0],
                region.bbox[3],  # 図表の下端から
                region.bbox[2],
                region.bbox[3] + 50  # 50ピクセル下まで
            )
            
            try:
                # 領域内のテキストを取得
                clip_rect = fitz.Rect(caption_area)
                caption_text = page.get_textbox(clip_rect)
                
                # キャプションパターンのマッチング
                for pattern in caption_patterns:
                    match = re.search(pattern, caption_text)
                    if match:
                        region.caption = match.group(0)
                        break
            except:
                pass
        
        return regions
    
    def process_page_with_regions(self, page: fitz.Page, page_num: int, 
                                 output_dir: str = None) -> Dict:
        """
        ページを領域ベースで処理
        
        Args:
            page: PDFページ
            page_num: ページ番号（0ベース）
            output_dir: 出力ディレクトリ
            
        Returns:
            処理結果の辞書
        """
        results = {
            'page_number': page_num + 1,
            'text': '',
            'figures': [],
            'processing_method': 'region_based'
        }
        
        # 図表領域を検出
        regions = self.detect_figure_regions(page, page_num)
        
        # テキスト抽出（図表領域を除外）
        full_text = page.get_text()
        results['text'] = full_text  # 簡易版：全テキストを保持
        
        # 各領域を処理
        for region in regions:
            # 領域を切り出して画像化
            pix = self.extract_region(page, region.bbox)
            
            # ファイル名を生成
            filename = f"p{page_num+1:03d}_{region.type}_{region.index:02d}.png"
            
            if output_dir:
                # 画像を保存
                img_path = os.path.join(output_dir, filename)
                pix.save(img_path)
                
                # 結果に追加
                results['figures'].append({
                    'type': region.type,
                    'bbox': region.bbox,
                    'filename': filename,
                    'path': img_path,
                    'caption': region.caption,
                    'confidence': region.confidence
                })
            else:
                # バイナリデータとして保持
                img_data = pix.tobytes("png")
                results['figures'].append({
                    'type': region.type,
                    'bbox': region.bbox,
                    'filename': filename,
                    'data': base64.b64encode(img_data).decode('utf-8'),
                    'caption': region.caption,
                    'confidence': region.confidence
                })
            
            # メモリ解放
            pix = None
        
        return results
    
    def process_document_with_regions(self, pdf_path: str, output_dir: str = None) -> Dict:
        """
        文書全体を領域ベースで処理
        
        Args:
            pdf_path: PDFファイルパス
            output_dir: 出力ディレクトリ
            
        Returns:
            処理結果の辞書
        """
        doc = fitz.open(pdf_path)
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            figures_dir = os.path.join(output_dir, 'figures')
            os.makedirs(figures_dir, exist_ok=True)
        else:
            figures_dir = None
        
        all_results = {
            'document': pdf_path,
            'total_pages': doc.page_count,
            'pages': [],
            'statistics': {
                'total_figures': 0,
                'total_tables': 0,
                'total_images': 0,
                'total_diagrams': 0
            }
        }
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            # ページを処理
            page_results = self.process_page_with_regions(
                page, page_num, figures_dir
            )
            
            all_results['pages'].append(page_results)
            
            # 統計を更新
            for figure in page_results['figures']:
                all_results['statistics']['total_figures'] += 1
                if figure['type'] == 'table':
                    all_results['statistics']['total_tables'] += 1
                elif figure['type'] == 'image':
                    all_results['statistics']['total_images'] += 1
                elif figure['type'] == 'figure':
                    all_results['statistics']['total_diagrams'] += 1
        
        doc.close()
        
        # 結果を保存
        if output_dir:
            result_path = os.path.join(output_dir, 'region_processing_result.json')
            with open(result_path, 'w', encoding='utf-8') as f:
                # base64データを除外して保存
                save_results = all_results.copy()
                for page in save_results['pages']:
                    for figure in page['figures']:
                        if 'data' in figure:
                            del figure['data']
                json.dump(save_results, f, ensure_ascii=False, indent=2)
        
        return all_results


def main():
    """テスト用のメイン関数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='図表領域をピンポイントで処理')
    parser.add_argument('pdf_path', help='PDFファイルパス')
    parser.add_argument('--output', '-o', default='region_output',
                       help='出力ディレクトリ')
    
    args = parser.parse_args()
    
    # プロセッサを初期化
    processor = RegionBasedProcessor()
    
    # 処理実行
    print(f"Processing: {args.pdf_path}")
    results = processor.process_document_with_regions(args.pdf_path, args.output)
    
    # 結果を表示
    print(f"\n処理完了:")
    print(f"- 総ページ数: {results['total_pages']}")
    print(f"- 検出された図表: {results['statistics']['total_figures']}")
    print(f"  - 表: {results['statistics']['total_tables']}")
    print(f"  - 画像: {results['statistics']['total_images']}")
    print(f"  - 図形: {results['statistics']['total_diagrams']}")
    print(f"\n結果は {args.output} に保存されました。")


if __name__ == "__main__":
    main()