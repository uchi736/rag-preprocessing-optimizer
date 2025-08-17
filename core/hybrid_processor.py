"""
ハイブリッド処理プロセッサ
埋め込み画像はピンポイント抽出、その他の図表を含むページは全体画像化
"""

import os
import json
import base64
import time
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from dataclasses import dataclass

import fitz
import google.generativeai as genai
from PIL import Image
import io

from core.region_based_processor import RegionBasedProcessor, FigureRegion
from core.practical_optimizer import PracticalConfig, ProcessingMethod, PageType


@dataclass
class PageProcessingDecision:
    """ページの処理方法の決定"""
    method: str  # 'text_only', 'extract_images', 'full_page', 'hybrid'
    embedded_images: List[FigureRegion]  # 埋め込み画像
    has_tables: bool  # 表の有無
    has_figures: bool  # 図形の有無
    confidence: float
    reason: str


class HybridProcessor(RegionBasedProcessor):
    """
    ハイブリッド処理プロセッサ
    - 埋め込み画像: ピンポイント抽出
    - フローチャート・表・複雑な図: ページ全体画像化
    """
    
    def __init__(self, config: Optional[PracticalConfig] = None,
                 api_key: Optional[str] = None):
        super().__init__(config)
        
        # Gemini API設定
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None
            print("警告: GEMINI_API_KEYが設定されていません")
        
        # 処理統計
        self.stats = {
            'text_only_pages': 0,
            'image_extraction_pages': 0,
            'full_page_pages': 0,
            'hybrid_pages': 0,
            'total_images_extracted': 0,
            'total_figures': 0,  # 追加
            'cost_saved_percentage': 0
        }
    
    def analyze_page_content(self, page: fitz.Page, page_num: int) -> PageProcessingDecision:
        """
        ページ内容を分析して処理方法を決定
        
        Args:
            page: PDFページ
            page_num: ページ番号
            
        Returns:
            処理方法の決定
        """
        decision = PageProcessingDecision(
            method='text_only',
            embedded_images=[],
            has_tables=False,
            has_figures=False,
            confidence=1.0,
            reason='デフォルト'
        )
        
        # 1. 埋め込み画像の検出
        embedded_images = self._detect_embedded_images(page, page_num)
        decision.embedded_images = embedded_images
        
        # 2. 表の検出
        try:
            tables = list(page.find_tables())
            decision.has_tables = len(tables) > 0
        except Exception as e:
            print(f"    表検出エラー: {e}")
            decision.has_tables = False
        
        # 3. テキスト内のキーワード検出で図表の存在を判定
        text = page.get_text()
        import re
        
        # フローチャートや図の存在を示すキーワード
        figure_keywords = [
            r'図\s*\d+', r'フロー', r'チャート', r'ブロック図',
            r'Fig\.', r'Figure', r'表\s*\d+', r'Table',
            r'グラフ', r'ダイアグラム', r'配線図', r'回路図'
        ]
        
        has_figure_text = any(re.search(kw, text) for kw in figure_keywords)
        
        # 図形要素は検出しない（get_drawings()を使わない）
        # キーワードがある場合は図表ありと判定
        decision.has_figures = has_figure_text
        
        # 4. 処理方法の決定
        if not embedded_images and not decision.has_tables and not decision.has_figures:
            # テキストのみ
            decision.method = 'text_only'
            decision.reason = 'テキストのみのページ'
            decision.confidence = 0.95
            
        elif embedded_images and not decision.has_tables and not decision.has_figures:
            # 埋め込み画像のみ → 画像を個別抽出
            decision.method = 'extract_images'
            decision.reason = f'{len(embedded_images)}個の埋め込み画像を個別抽出'
            decision.confidence = 0.9
            
        elif (decision.has_tables or decision.has_figures) and not embedded_images:
            # 表や図形のみ → ページ全体を画像化
            decision.method = 'full_page'
            decision.reason = '表・フローチャート・図形を含むため全体画像化'
            decision.confidence = 0.85
            
        else:
            # 混在 → ハイブリッド処理
            decision.method = 'hybrid'
            decision.reason = '画像は個別抽出、ページ全体も画像化'
            decision.confidence = 0.8
        
        return decision
    
    def _detect_embedded_images(self, page: fitz.Page, page_num: int) -> List[FigureRegion]:
        """
        埋め込み画像のみを検出（高精度）
        
        Args:
            page: PDFページ
            page_num: ページ番号
            
        Returns:
            埋め込み画像のリスト
        """
        images = []
        
        try:
            image_list = page.get_images(full=True)
            for idx, img in enumerate(image_list):
                xref = img[0]
                try:
                    # 画像のメタデータを取得
                    base_image = page.parent.extract_image(xref)
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    
                    # 意味のある大きさの画像のみ
                    if width > 100 and height > 100:
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
                            images.append(region)
                except:
                    pass
        except:
            pass
        
        return images
    
    def process_page_hybrid(self, page: fitz.Page, page_num: int,
                           output_dir: Optional[str] = None) -> Dict:
        """
        ハイブリッド方式でページを処理
        
        Args:
            page: PDFページ
            page_num: ページ番号
            output_dir: 出力ディレクトリ
            
        Returns:
            処理結果
        """
        results = {
            'page_number': page_num + 1,
            'processing_method': 'hybrid',
            'text': '',
            'extracted_images': [],
            'full_page_image': None,
            'gemini_analysis': {}
        }
        
        # ページ内容を分析
        decision = self.analyze_page_content(page, page_num)
        results['processing_decision'] = {
            'method': decision.method,
            'reason': decision.reason,
            'confidence': decision.confidence
        }
        
        # 出力ディレクトリの準備
        if output_dir:
            images_dir = os.path.join(output_dir, 'images')
            pages_dir = os.path.join(output_dir, 'pages')
            os.makedirs(images_dir, exist_ok=True)
            os.makedirs(pages_dir, exist_ok=True)
        
        # テキスト抽出（常に実行）
        results['text'] = page.get_text()
        
        # 処理方法に応じた処理
        if decision.method == 'text_only':
            # テキストのみ
            self.stats['text_only_pages'] += 1
            print(f"  ページ {page_num + 1}: テキストのみ")
            
        elif decision.method == 'extract_images':
            # 埋め込み画像を個別抽出
            self.stats['image_extraction_pages'] += 1
            print(f"  ページ {page_num + 1}: {len(decision.embedded_images)}個の画像を抽出")
            
            for img_region in decision.embedded_images:
                # 画像を切り出し
                pix = self.extract_region(page, img_region.bbox, margin=5)
                img_data = pix.tobytes("png")
                
                filename = f"p{page_num+1:03d}_img_{img_region.index:02d}.png"
                
                if output_dir:
                    img_path = os.path.join(images_dir, filename)
                    pix.save(img_path)
                
                # Gemini解析
                if self.model:
                    analysis = self._analyze_with_gemini(img_data, 'image')
                    results['gemini_analysis'][filename] = analysis
                
                results['extracted_images'].append({
                    'filename': filename,
                    'bbox': img_region.bbox,
                    'size': (pix.width, pix.height)
                })
                
                self.stats['total_images_extracted'] += 1
                pix = None
                
        elif decision.method == 'full_page':
            # ページ全体を画像化
            self.stats['full_page_pages'] += 1
            print(f"  ページ {page_num + 1}: 全体画像化（{decision.reason}）")
            
            # ページ全体を高解像度で画像化
            mat = fitz.Matrix(self.config.image_dpi_multiplier, self.config.image_dpi_multiplier)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            filename = f"p{page_num+1:03d}_full.png"
            
            if output_dir:
                img_path = os.path.join(pages_dir, filename)
                pix.save(img_path)
            
            # Gemini解析
            if self.model:
                analysis = self._analyze_with_gemini(img_data, 'full_page', decision.reason)
                results['gemini_analysis']['full_page'] = analysis
            
            results['full_page_image'] = {
                'filename': filename,
                'size': (pix.width, pix.height),
                'reason': decision.reason
            }
            pix = None
            
        else:  # hybrid
            # ハイブリッド処理
            self.stats['hybrid_pages'] += 1
            print(f"  ページ {page_num + 1}: ハイブリッド処理")
            
            # 1. 埋め込み画像を個別抽出
            for img_region in decision.embedded_images:
                pix = self.extract_region(page, img_region.bbox, margin=5)
                img_data = pix.tobytes("png")
                
                filename = f"p{page_num+1:03d}_img_{img_region.index:02d}.png"
                
                if output_dir:
                    img_path = os.path.join(images_dir, filename)
                    pix.save(img_path)
                
                if self.model:
                    analysis = self._analyze_with_gemini(img_data, 'image')
                    results['gemini_analysis'][filename] = analysis
                
                results['extracted_images'].append({
                    'filename': filename,
                    'bbox': img_region.bbox,
                    'size': (pix.width, pix.height)
                })
                
                self.stats['total_images_extracted'] += 1
                pix = None
            
            # 2. ページ全体も画像化
            mat = fitz.Matrix(self.config.image_dpi_multiplier, self.config.image_dpi_multiplier)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            filename = f"p{page_num+1:03d}_full.png"
            
            if output_dir:
                img_path = os.path.join(pages_dir, filename)
                pix.save(img_path)
            
            if self.model:
                analysis = self._analyze_with_gemini(img_data, 'full_page_with_figures', 
                                                    '表やフローチャートを重点的に解析')
                results['gemini_analysis']['full_page'] = analysis
            
            results['full_page_image'] = {
                'filename': filename,
                'size': (pix.width, pix.height),
                'reason': 'ハイブリッド処理（画像抽出後の図表解析）'
            }
            pix = None
        
        return results
    
    def _analyze_with_gemini(self, img_data: bytes, content_type: str, 
                           context: str = '') -> Dict:
        """
        Geminiで画像を解析
        
        Args:
            img_data: 画像データ
            content_type: コンテンツタイプ
            context: 追加コンテキスト
            
        Returns:
            解析結果
        """
        if not self.model:
            return {'status': 'skipped', 'reason': 'No API key'}
        
        try:
            img = Image.open(io.BytesIO(img_data))
            
            # プロンプトの選択
            prompts = {
                'image': '埋め込み画像を解析してください。画像内のすべてのテキストと情報を抽出してください。',
                'full_page': 'このページを詳細に解析してください。表、フローチャート、図形、テキストをすべて構造化して出力してください。',
                'full_page_with_figures': 'このページの表やフローチャートを重点的に解析してください。構造と関係性を明確に説明してください。'
            }
            
            prompt = prompts.get(content_type, prompts['full_page'])
            if context:
                prompt = f"{context}\n\n{prompt}"
            
            response = self.model.generate_content([prompt, img])
            
            return {
                'status': 'success',
                'type': content_type,
                'analysis': response.text
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def process_document(self, pdf_path: str, output_dir: str) -> Dict:
        """
        文書全体をハイブリッド処理
        
        Args:
            pdf_path: PDFファイルパス
            output_dir: 出力ディレクトリ
            
        Returns:
            処理結果
        """
        print(f"\nハイブリッド処理開始: {pdf_path}")
        doc = fitz.open(pdf_path)
        total_pages = doc.page_count  # doc.close()の前に取得
        
        os.makedirs(output_dir, exist_ok=True)
        
        all_results = {
            'document': pdf_path,
            'total_pages': total_pages,
            'pages': [],
            'statistics': self.stats,
            'processing_time': 0
        }
        
        start_time = time.time()
        
        # 統合Markdownファイル
        md_path = os.path.join(output_dir, 'hybrid_result.md')
        
        with open(md_path, 'w', encoding='utf-8') as md_file:
            md_file.write(f"# ハイブリッド処理結果\n\n")
            md_file.write(f"文書: {os.path.basename(pdf_path)}\n\n")
            
            for page_num in range(total_pages):
                print(f"\nページ {page_num + 1}/{total_pages} を処理中...")
                page = doc[page_num]
                
                # ページを処理
                page_results = self.process_page_hybrid(page, page_num, output_dir)
                all_results['pages'].append(page_results)
                
                # Markdown出力
                md_file.write(f"\n## ページ {page_num + 1}\n\n")
                md_file.write(f"**処理方法:** {page_results['processing_decision']['method']}\n")
                md_file.write(f"**理由:** {page_results['processing_decision']['reason']}\n\n")
                
                # Gemini解析結果
                if page_results['gemini_analysis']:
                    md_file.write("### 解析結果\n\n")
                    for key, analysis in page_results['gemini_analysis'].items():
                        if analysis.get('status') == 'success':
                            md_file.write(f"#### {key}\n\n")
                            md_file.write(analysis['analysis'][:1000])  # 最初の1000文字
                            if len(analysis['analysis']) > 1000:
                                md_file.write("\n...(省略)...")
                            md_file.write("\n\n")
                            
                
                # 統計更新
                all_results['statistics']['total_figures'] += len(page_results.get('extracted_images', []))
                all_results['statistics']['total_figures'] += (1 if page_results.get('full_page_image') else 0)
        
        doc.close()
        
        # 統計計算
        all_results['statistics']['processing_time'] = time.time() - start_time
        
        # コスト削減率の推定
        saved_pages = self.stats['text_only_pages'] + self.stats['image_extraction_pages'] * 0.7
        if total_pages > 0:
            self.stats['cost_saved_percentage'] = (saved_pages / total_pages) * 100
        
        # 結果をJSON保存
        json_path = os.path.join(output_dir, 'hybrid_result.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            # Gemini解析を短縮して保存
            save_results = all_results.copy()
            for page in save_results['pages']:
                for key in page.get('gemini_analysis', {}):
                    if 'analysis' in page['gemini_analysis'][key]:
                        text = page['gemini_analysis'][key]['analysis']
                        if len(text) > 200:
                            page['gemini_analysis'][key]['analysis'] = text[:200] + '...'
            
            json.dump(save_results, f, ensure_ascii=False, indent=2)
        
        # 完了メッセージ
        print(f"\n処理完了:")
        print(f"- 処理時間: {all_results['statistics']['processing_time']:.2f}秒")
        print(f"- テキストのみ: {self.stats['text_only_pages']}ページ")
        print(f"- 画像抽出: {self.stats['image_extraction_pages']}ページ")
        print(f"- 全体画像化: {self.stats['full_page_pages']}ページ")
        print(f"- ハイブリッド: {self.stats['hybrid_pages']}ページ")
        print(f"- 抽出画像数: {self.stats['total_images_extracted']}")
        print(f"- 推定コスト削減: {self.stats['cost_saved_percentage']:.1f}%")
        print(f"\n結果: {output_dir}")
        
        return all_results


def main():
    """メイン処理"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ハイブリッド処理（画像は個別抽出、図表ページは全体画像化）'
    )
    parser.add_argument('pdf_path', help='PDFファイルパス')
    parser.add_argument('--output', '-o', default='hybrid_output',
                       help='出力ディレクトリ')
    parser.add_argument('--api-key', help='Gemini APIキー')
    
    args = parser.parse_args()
    
    # プロセッサを初期化
    processor = HybridProcessor(api_key=args.api_key)
    
    # 処理実行
    results = processor.process_document(args.pdf_path, args.output)
    
    return results


if __name__ == "__main__":
    main()