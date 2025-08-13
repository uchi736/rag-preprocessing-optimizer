import fitz  # PyMuPDF
from PIL import Image
import io
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import re

class SmartPageAnalyzer:
    def __init__(self, config=None):
        # 拡張版: フロー図検出用のキーワード
        self.figure_keywords = [
            '図', 'フロー', 'STEP', '→', '工程', 'プロセス', 
            'ステップ', '流れ', '手順', '↓', '⇒', '①', '②', '③',
            'フローチャート', 'ダイアグラム', '処理', '判定', '分岐',
            'START', 'END', '開始', '終了', '↑', '←', '⇦', '⇨', '⇧', '⇩',
            'Phase', 'フェーズ', 'ループ', 'Loop', 'IF', 'THEN', 'ELSE'
        ]
        
        # configから設定を読み込み、なければデフォルト値を使用
        if config:
            self.detection_config = {
                'min_rects_for_diagram': config.min_rects_for_diagram if hasattr(config, 'min_rects_for_diagram') else 5,
                'min_lines_for_diagram': config.min_lines_for_diagram if hasattr(config, 'min_lines_for_diagram') else 4,
                'min_arrows_for_flowchart': config.min_arrows_for_flowchart if hasattr(config, 'min_arrows_for_flowchart') else 2,
                'min_combined_shapes': config.min_combined_shapes if hasattr(config, 'min_combined_shapes') else 8,
                'min_figure_area_ratio': config.min_figure_area_ratio if hasattr(config, 'min_figure_area_ratio') else 0.05,
                'embedded_image_min_size': config.embedded_image_min_size if hasattr(config, 'embedded_image_min_size') else 100,
                'header_footer_margin': 50,
                'flowchart_confidence_boost': config.flowchart_confidence_boost if hasattr(config, 'flowchart_confidence_boost') else 20
            }
        else:
            # デフォルト設定
            self.detection_config = {
                'min_rects_for_diagram': 5,      # 3→5 (誤検出削減)
                'min_lines_for_diagram': 4,      # 2→4 (単純な罫線を除外)
                'min_arrows_for_flowchart': 2,   # フローチャート専用
                'min_combined_shapes': 8,        # 複合図形の判定
                'min_figure_area_ratio': 0.05,   # 小さすぎる要素を除外
                'embedded_image_min_size': 100,  # 埋め込み画像の最小サイズ
                'header_footer_margin': 50,      # ヘッダー/フッター領域
                'flowchart_confidence_boost': 20 # フローチャート検出時の信頼度ブースト
            }
        
        # 後方互換性のため旧変数も保持
        self.min_rects_for_diagram = self.detection_config['min_rects_for_diagram']
        self.min_lines_for_diagram = self.detection_config['min_lines_for_diagram']
        
    def analyze_page_content(self, page) -> Dict:
        """ページの内容を分析して、図表の有無を判定（改良版）"""
        result = {
            'has_table': False,
            'has_figure': False,
            'has_flowchart': False,      # フローチャート専用フラグ
            'has_embedded_image': False,  # 埋め込み画像フラグ
            'has_diagram': False,         # 一般的なダイアグラム
            'has_complex_layout': False,
            'text_ratio': 0,
            'confidence': 0,
            'reasons': [],
            'figure_details': {},         # 図形の詳細情報
            'figure_complexity': 'simple' # simple/medium/complex
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
        
        # 2. 図形要素の詳細検出（改良版）
        try:
            drawings = page.get_drawings()
            rect_count = sum(1 for d in drawings if d.get('type') == 'r')  # rectangle
            line_count = sum(1 for d in drawings if d.get('type') == 'l')  # line
            curve_count = sum(1 for d in drawings if d.get('type') == 'c')  # curve
            
            # 矢印パターンの検出
            arrow_count = self._detect_arrow_patterns(drawings)
            
            total_shapes = rect_count + line_count + curve_count
            
            # フローチャート判定（矩形＋矢印の組み合わせ）
            if rect_count >= 3 and arrow_count >= self.detection_config['min_arrows_for_flowchart']:
                result['has_flowchart'] = True
                result['has_figure'] = True
                result['reasons'].append(f"フローチャートを検出（矩形:{rect_count}, 矢印:{arrow_count}）")
                result['confidence'] += 60 + self.detection_config['flowchart_confidence_boost']
                result['figure_complexity'] = 'complex'
            
            # 一般的な図形判定（厳格化された閾値）
            elif rect_count >= self.detection_config['min_rects_for_diagram'] or \
                 line_count >= self.detection_config['min_lines_for_diagram']:
                result['has_diagram'] = True
                result['has_figure'] = True
                result['reasons'].append(f"図形要素を検出（矩形:{rect_count}, 線:{line_count}, 曲線:{curve_count}）")
                result['confidence'] += 40
                result['figure_complexity'] = 'medium'
            
            # 複合的な判定（総要素数）
            elif total_shapes >= self.detection_config['min_combined_shapes']:
                result['has_diagram'] = True
                result['has_figure'] = True
                result['reasons'].append(f"複合図形を検出（総要素数:{total_shapes}）")
                result['confidence'] += 35
                result['figure_complexity'] = 'medium'
                
            # 詳細情報を保存
            result['figure_details'] = {
                'rectangles': rect_count,
                'lines': line_count,
                'curves': curve_count,
                'arrows': arrow_count,
                'total': total_shapes
            }
        except Exception as e:
            # エラーログを残す
            result['reasons'].append(f"図形検出でエラー: {str(e)[:50]}")
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
        
        # 6. 特定のパターン検出（拡張版）
        step_pattern = re.compile(r'(?:STEP|ステップ|手順|Phase|フェーズ|工程)\s*[0-9０-９]+|[①②③④⑤⑥⑦⑧⑨⑩]')
        arrow_text_pattern = re.compile(r'[→←↑↓⇒⇐⇑⇓➡⬅⬆⬇]')
        
        step_matches = len(step_pattern.findall(text))
        arrow_matches = len(arrow_text_pattern.findall(text))
        
        if step_matches >= 3:  # 3つ以上のステップがある場合
            result['has_figure'] = True
            result['reasons'].append(f"複数のステップパターンを検出（{step_matches}個）")
            result['confidence'] += 30
            
        if arrow_matches >= 3:  # 3つ以上の矢印記号がある場合
            result['has_figure'] = True
            result['reasons'].append(f"矢印記号を複数検出（{arrow_matches}個）")
            result['confidence'] += 20
            
        # 7. 埋め込み画像の検出
        try:
            image_list = page.get_images(full=True)
            if image_list:
                # 小さすぎる画像（アイコンなど）を除外
                significant_images = []
                for img in image_list:
                    xref = img[0]
                    try:
                        base_image = page.parent.extract_image(xref)
                        width = base_image.get("width", 0)
                        height = base_image.get("height", 0)
                        min_size = self.detection_config['embedded_image_min_size']
                        if width > min_size and height > min_size:
                            significant_images.append((width, height))
                    except:
                        pass
                
                if significant_images:
                    result['has_embedded_image'] = True
                    result['has_figure'] = True
                    result['reasons'].append(f"埋め込み画像を検出（{len(significant_images)}個）")
                    result['confidence'] += 50
        except:
            pass
            
        # 8. 信頼度の正規化（100を超えないように）
        result['confidence'] = min(result['confidence'], 100)
            
        return result
    
    def _detect_arrow_patterns(self, drawings) -> int:
        """図形要素から矢印パターンを検出"""
        arrow_count = 0
        lines = [d for d in drawings if d.get('type') == 'l']
        
        # 簡易的な矢印検出：近接する線の組み合わせをチェック
        # V字型やL字型のパターンを探す
        if len(lines) >= 2:
            # 線が多い場合、矢印の可能性を推定
            # 実際の実装では、線の角度と位置関係を詳細に解析する必要がある
            arrow_count = len(lines) // 3  # 3本の線で1つの矢印と推定（簡易版）
                
        return arrow_count
    
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