import fitz  # PyMuPDF
from PIL import Image
import io
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import re

class SmartPageAnalyzer:
    def __init__(self):
        # フロー図検出用のキーワード
        self.figure_keywords = [
            '図', 'フロー', 'STEP', '→', '工程', 'プロセス', 
            'ステップ', '流れ', '手順', '↓', '⇒', '①', '②', '③'
        ]
        self.min_rects_for_diagram = 3  # 図形と判定する最小矩形数
        self.min_lines_for_diagram = 2  # 図形と判定する最小線数
        
    def analyze_page_content(self, page) -> Dict:
        """ページの内容を分析して、図表の有無を判定"""
        result = {
            'has_table': False,
            'has_figure': False,
            'has_complex_layout': False,
            'text_ratio': 0,
            'confidence': 0,
            'reasons': []
        }
        
        # 1. 表の検出（PyMuPDFの機能を活用）
        try:
            tables = page.find_tables()
            # TableFinderオブジェクトをリストに変換
            table_list = list(tables) if tables else []
            if table_list:
                result['has_table'] = True
                result['reasons'].append(f"表を{len(table_list)}個検出")
                result['confidence'] += 30
        except Exception as e:
            # find_tablesがサポートされていない場合
            pass
        
        # 2. 図形要素の検出
        try:
            drawings = page.get_drawings()
            rect_count = sum(1 for d in drawings if d.get('type') == 'r')  # rectangle
            line_count = sum(1 for d in drawings if d.get('type') == 'l')  # line
            curve_count = sum(1 for d in drawings if d.get('type') == 'c')  # curve
            
            total_shapes = rect_count + line_count + curve_count
            
            if rect_count >= self.min_rects_for_diagram or line_count >= self.min_lines_for_diagram:
                result['has_figure'] = True
                result['reasons'].append(f"図形要素を検出（矩形:{rect_count}, 線:{line_count}, 曲線:{curve_count}）")
                result['confidence'] += 40
        except:
            # get_drawingsがサポートされていない場合
            pass
        
        # 3. テキストパターンから図の可能性を判定
        text = page.get_text()
        detected_keywords = []
        for keyword in self.figure_keywords:
            if keyword in text:
                detected_keywords.append(keyword)
                
        if detected_keywords:
            result['has_figure'] = True
            result['reasons'].append(f"図のキーワードを検出: {', '.join(detected_keywords[:3])}")
            result['confidence'] += 20
        
        # 4. レイアウトの複雑さを判定（テキストブロックの配置）
        blocks = page.get_text("dict")['blocks']
        text_blocks = [b for b in blocks if b.get('type') == 0]
        
        if len(text_blocks) > 5:
            # テキストブロックの位置分散を確認
            x_positions = [b['bbox'][0] for b in text_blocks]
            y_positions = [b['bbox'][1] for b in text_blocks]
            
            if x_positions and y_positions:
                x_variance = max(x_positions) - min(x_positions)
                y_variance = max(y_positions) - min(y_positions)
                
                # 位置が大きく分散している場合は複雑なレイアウト
                if x_variance > 200 or y_variance > 300:
                    result['has_complex_layout'] = True
                    result['reasons'].append("複雑なレイアウトを検出")
                    result['confidence'] += 20
        
        # 5. テキスト比率の計算（画像が多いページの判定）
        page_rect = page.rect
        page_area = abs((page_rect.x1 - page_rect.x0) * (page_rect.y1 - page_rect.y0))
        
        text_area = 0
        for b in text_blocks:
            bbox = b.get('bbox', [0, 0, 0, 0])
            if len(bbox) >= 4:
                text_area += abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
                
        result['text_ratio'] = text_area / page_area if page_area > 0 else 0
        
        # テキスト比率が低い場合は図が含まれる可能性
        if result['text_ratio'] < 0.5:
            result['has_figure'] = True
            result['reasons'].append(f"テキスト比率が低い（{result['text_ratio']:.1%}）")
            result['confidence'] += 15
        
        # 6. 特定のパターン検出（番号付きステップなど）
        step_pattern = re.compile(r'(?:STEP|ステップ|手順)\s*[0-9０-９]+|[①②③④⑤⑥⑦⑧⑨⑩]')
        if step_pattern.search(text):
            result['has_figure'] = True
            result['reasons'].append("ステップ番号パターンを検出")
            result['confidence'] += 25
            
        return result
    
    def extract_page_as_image(self, page, dpi: int = 200) -> Image.Image:
        """ページを画像として抽出"""
        mat = fitz.Matrix(dpi/72.0, dpi/72.0)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        return Image.open(io.BytesIO(img_data))
    
    def extract_pages_with_visuals(self, pdf_path: str, dpi: int = 200, min_confidence: int = 30) -> List[Dict]:
        """図表を含むページのみを画像化"""
        doc = fitz.open(pdf_path)
        pages_to_process = []
        
        print(f"PDFの解析を開始: {pdf_path}")
        print(f"総ページ数: {doc.page_count}")
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            analysis = self.analyze_page_content(page)
            
            # 信頼度が閾値を超える場合、または図表が検出された場合に画像化
            should_process = (
                analysis['confidence'] >= min_confidence or
                analysis['has_table'] or 
                analysis['has_figure'] or 
                analysis['has_complex_layout']
            )
            
            if should_process:
                # ページを画像化
                img = self.extract_page_as_image(page, dpi)
                
                # ページタイプの判定
                page_type = 'mixed'
                if analysis['has_table'] and analysis['has_figure']:
                    page_type = 'mixed'
                elif analysis['has_table']:
                    page_type = 'table'
                elif analysis['has_figure']:
                    page_type = 'figure'
                else:
                    page_type = 'complex_layout'
                
                pages_to_process.append({
                    'page_number': page_num + 1,
                    'image': img,
                    'analysis': analysis,
                    'text_preview': page.get_text()[:200],
                    'type': page_type,
                    'confidence': analysis['confidence']
                })
                
                print(f"ページ {page_num + 1}: 画像化対象 - {', '.join(analysis['reasons'])} (信頼度: {analysis['confidence']})")
            else:
                print(f"ページ {page_num + 1}: スキップ（通常テキスト）")
        
        doc.close()
        print(f"\n画像化対象: {len(pages_to_process)}ページ")
        return pages_to_process
    
    def save_visual_pages(self, pages: List[Dict], output_dir: str = "output/visual_pages"):
        """画像化したページを保存"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        for page_data in pages:
            filename = f"page_{page_data['page_number']:03d}_{page_data['type']}.png"
            filepath = os.path.join(output_dir, filename)
            page_data['image'].save(filepath)
            print(f"保存: {filepath}")
            
        # サマリーを保存
        import json
        summary = {
            "total_pages": len(pages),
            "pages": [
                {
                    "page": p['page_number'],
                    "type": p['type'],
                    "confidence": p['confidence'],
                    "reasons": p['analysis']['reasons']
                }
                for p in pages
            ]
        }
        
        with open(os.path.join(output_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    def create_multimodal_prompt(self, page_data: Dict, custom_prompt: str = None) -> str:
        """ページタイプに応じたプロンプトを生成"""
        if custom_prompt:
            return custom_prompt
            
        base_prompt = "この画像を詳細に分析してください。\n\n"
        
        if page_data['type'] == 'table':
            return base_prompt + """特に以下の点に注目してください：
1. 表の構造（行数、列数、ヘッダー）
2. 表に含まれるデータの種類と内容
3. 重要な数値や項目
4. 表から読み取れる傾向や関係性
5. 表の目的と使用場面"""
            
        elif page_data['type'] == 'figure':
            return base_prompt + """特に以下の点に注目してください：
1. 図の種類（フロー図、ダイアグラム、組織図など）
2. 各要素（ボックス、矢印、テキスト）の内容
3. 要素間の関係性と流れ
4. プロセスの開始点と終了点
5. 重要な分岐や判断ポイント
6. 図全体が表現している概念やプロセス"""
            
        elif page_data['type'] == 'mixed':
            return base_prompt + """このページには図と表の両方が含まれています。以下の点に注目してください：
1. ページ全体の構成とレイアウト
2. 図と表の関係性
3. それぞれの要素が伝える情報
4. 要素間の相互参照や関連
5. ページ全体から理解できる重要な概念"""
            
        else:  # complex_layout
            return base_prompt + """このページは複雑なレイアウトを持っています。以下の点に注目してください：
1. ページの全体的な構造
2. 各セクションの内容と役割
3. 視覚的な要素（箱、線、矢印など）
4. 情報の階層構造
5. 重要なポイントや結論"""