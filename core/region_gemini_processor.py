"""
図表領域切り出しとGemini解析を統合したプロセッサ
"""

import os
import json
import base64
from typing import Dict, List, Optional
from pathlib import Path
import time

import fitz
import google.generativeai as genai
from PIL import Image
import io

from core.region_based_processor import RegionBasedProcessor, FigureRegion
from core.practical_optimizer import PracticalConfig


class RegionGeminiProcessor(RegionBasedProcessor):
    """
    図表領域を切り出してGeminiで解析するプロセッサ
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
        
        # プロンプトテンプレート
        self.prompts = {
            'table': """この表を詳細に解析してください。

以下の形式で出力してください：
1. 表の構造（行数、列数、ヘッダー）
2. 表の内容を完全にMarkdown形式で再現
3. 重要なデータポイントの要約

必ずMarkdown形式の表として出力してください。""",
            
            'figure': """この図を詳細に解析してください。

以下を含めて説明してください：
1. 図の種類（フローチャート、ブロック図、グラフなど）
2. 図に含まれる要素とその関係性
3. 図が示す主要な情報やプロセス
4. 図中のすべてのテキスト情報

構造化された形式で出力してください。""",
            
            'image': """この画像を詳細に解析してください。

以下を含めて説明してください：
1. 画像の内容と種類
2. 画像に含まれるテキスト情報（すべて抽出）
3. 画像が伝える主要な情報
4. 技術的な詳細があれば記載

すべての情報を漏れなく抽出してください。""",
            
            'chart': """このグラフ/チャートを詳細に解析してください。

以下の形式で出力してください：
1. グラフの種類（棒グラフ、折れ線グラフ、円グラフなど）
2. 軸ラベルと単位
3. データポイントの値（可能な限り正確に）
4. 主要な傾向やパターン

データは可能な限り数値として抽出してください。"""
        }
    
    def analyze_figure_with_gemini(self, image_data: bytes, figure_type: str, 
                                  caption: Optional[str] = None) -> Dict:
        """
        切り出した図表をGeminiで解析
        
        Args:
            image_data: 画像のバイナリデータ
            figure_type: 図表のタイプ
            caption: キャプション（あれば）
            
        Returns:
            解析結果の辞書
        """
        if not self.model:
            return {
                'status': 'error',
                'message': 'Gemini API not configured',
                'type': figure_type
            }
        
        try:
            # 画像をPIL形式に変換
            img = Image.open(io.BytesIO(image_data))
            
            # プロンプトを選択
            prompt = self.prompts.get(figure_type, self.prompts['figure'])
            
            # キャプションがあれば追加
            if caption:
                prompt = f"図のキャプション: {caption}\n\n{prompt}"
            
            # Geminiで解析
            response = self.model.generate_content([prompt, img])
            
            # 結果を構造化
            result = {
                'status': 'success',
                'type': figure_type,
                'caption': caption,
                'analysis': response.text,
                'timestamp': time.time()
            }
            
            # 表の場合、Markdown表を抽出
            if figure_type == 'table':
                result['markdown_table'] = self._extract_markdown_table(response.text)
            
            return result
            
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'type': figure_type
            }
    
    def _extract_markdown_table(self, text: str) -> Optional[str]:
        """Geminiの応答からMarkdown表を抽出"""
        lines = text.split('\n')
        table_lines = []
        in_table = False
        
        for line in lines:
            # Markdown表の開始を検出
            if '|' in line and not in_table:
                in_table = True
                table_lines.append(line)
            elif in_table:
                if '|' in line or line.strip().startswith('-'):
                    table_lines.append(line)
                else:
                    # 表の終了
                    if table_lines:
                        break
        
        return '\n'.join(table_lines) if table_lines else None
    
    def process_page_with_gemini(self, page: fitz.Page, page_num: int, 
                                output_dir: Optional[str] = None) -> Dict:
        """
        ページを処理し、図表をGeminiで解析
        
        Args:
            page: PDFページ
            page_num: ページ番号
            output_dir: 出力ディレクトリ
            
        Returns:
            処理結果
        """
        results = {
            'page_number': page_num + 1,
            'text': '',
            'figures': [],
            'gemini_analyses': []
        }
        
        # 図表領域を検出
        regions = self.detect_figure_regions(page, page_num)
        
        # テキスト抽出
        results['text'] = page.get_text()
        
        # 出力ディレクトリの準備
        if output_dir:
            figures_dir = os.path.join(output_dir, 'figures')
            os.makedirs(figures_dir, exist_ok=True)
            analyses_dir = os.path.join(output_dir, 'gemini_analyses')
            os.makedirs(analyses_dir, exist_ok=True)
        
        # 各領域を処理
        for region in regions:
            # 領域を切り出し
            pix = self.extract_region(page, region.bbox)
            img_data = pix.tobytes("png")
            
            # ファイル名生成
            filename = f"p{page_num+1:03d}_{region.type}_{region.index:02d}"
            
            # 画像保存
            if output_dir:
                img_path = os.path.join(figures_dir, f"{filename}.png")
                pix.save(img_path)
            
            # Gemini解析
            if self.model:
                print(f"  Geminiで{region.type}を解析中...")
                analysis = self.analyze_figure_with_gemini(
                    img_data, region.type, region.caption
                )
                
                # 解析結果を保存
                if output_dir and analysis['status'] == 'success':
                    analysis_path = os.path.join(analyses_dir, f"{filename}_analysis.md")
                    with open(analysis_path, 'w', encoding='utf-8') as f:
                        f.write(f"# {region.type.upper()} Analysis\n\n")
                        if region.caption:
                            f.write(f"**Caption:** {region.caption}\n\n")
                        f.write(analysis['analysis'])
                
                results['gemini_analyses'].append({
                    'filename': filename,
                    'type': region.type,
                    'analysis': analysis
                })
            
            # 図表情報を記録
            results['figures'].append({
                'type': region.type,
                'bbox': region.bbox,
                'filename': f"{filename}.png",
                'caption': region.caption,
                'confidence': region.confidence
            })
            
            # メモリ解放
            pix = None
        
        return results
    
    def process_document_complete(self, pdf_path: str, output_dir: str) -> Dict:
        """
        文書全体を完全処理（領域切り出し＋Gemini解析）
        
        Args:
            pdf_path: PDFファイルパス
            output_dir: 出力ディレクトリ
            
        Returns:
            完全な処理結果
        """
        print(f"\n処理開始: {pdf_path}")
        doc = fitz.open(pdf_path)
        
        # 出力ディレクトリ作成
        os.makedirs(output_dir, exist_ok=True)
        
        # 統合結果を保存
        integrated_md_path = os.path.join(output_dir, 'integrated_document.md')
        
        all_results = {
            'document': pdf_path,
            'total_pages': doc.page_count,
            'pages': [],
            'statistics': {
                'total_figures': 0,
                'tables_analyzed': 0,
                'images_analyzed': 0,
                'figures_analyzed': 0,
                'processing_time': 0
            }
        }
        
        start_time = time.time()
        
        with open(integrated_md_path, 'w', encoding='utf-8') as md_file:
            md_file.write(f"# 文書解析結果: {os.path.basename(pdf_path)}\n\n")
            
            for page_num in range(doc.page_count):
                print(f"\nページ {page_num + 1}/{doc.page_count} を処理中...")
                page = doc[page_num]
                
                # ページを処理
                page_results = self.process_page_with_gemini(page, page_num, output_dir)
                all_results['pages'].append(page_results)
                
                # Markdown出力
                md_file.write(f"\n## ページ {page_num + 1}\n\n")
                
                # テキスト部分
                if page_results['text'].strip():
                    md_file.write("### テキスト\n\n")
                    md_file.write(page_results['text'][:1000])  # 最初の1000文字
                    if len(page_results['text']) > 1000:
                        md_file.write("\n... (省略) ...\n")
                    md_file.write("\n\n")
                
                # 図表解析結果
                if page_results['gemini_analyses']:
                    md_file.write("### 図表解析\n\n")
                    for analysis_info in page_results['gemini_analyses']:
                        if analysis_info['analysis']['status'] == 'success':
                            md_file.write(f"#### {analysis_info['type'].upper()}\n\n")
                            md_file.write(analysis_info['analysis']['analysis'])
                            md_file.write("\n\n")
                            
                            # 統計更新
                            if analysis_info['type'] == 'table':
                                all_results['statistics']['tables_analyzed'] += 1
                            elif analysis_info['type'] == 'image':
                                all_results['statistics']['images_analyzed'] += 1
                            elif analysis_info['type'] == 'figure':
                                all_results['statistics']['figures_analyzed'] += 1
                
                # 統計更新
                all_results['statistics']['total_figures'] += len(page_results['figures'])
        
        doc.close()
        
        # 処理時間
        all_results['statistics']['processing_time'] = time.time() - start_time
        
        # 結果をJSON保存
        result_path = os.path.join(output_dir, 'complete_processing_result.json')
        with open(result_path, 'w', encoding='utf-8') as f:
            # Gemini解析テキストを短縮して保存
            save_results = all_results.copy()
            for page in save_results['pages']:
                for analysis in page.get('gemini_analyses', []):
                    if 'analysis' in analysis and 'analysis' in analysis['analysis']:
                        # 長いテキストは最初の500文字のみ保存
                        text = analysis['analysis']['analysis']
                        if len(text) > 500:
                            analysis['analysis']['analysis'] = text[:500] + '...'
            
            json.dump(save_results, f, ensure_ascii=False, indent=2)
        
        # 処理完了メッセージ
        print(f"\n処理完了:")
        print(f"- 処理時間: {all_results['statistics']['processing_time']:.2f}秒")
        print(f"- 総ページ数: {all_results['total_pages']}")
        print(f"- 検出された図表: {all_results['statistics']['total_figures']}")
        print(f"  - 解析された表: {all_results['statistics']['tables_analyzed']}")
        print(f"  - 解析された画像: {all_results['statistics']['images_analyzed']}")
        print(f"  - 解析された図形: {all_results['statistics']['figures_analyzed']}")
        print(f"\n結果は {output_dir} に保存されました。")
        
        return all_results


def main():
    """メイン処理"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='図表領域を切り出してGeminiで解析'
    )
    parser.add_argument('pdf_path', help='PDFファイルパス')
    parser.add_argument('--output', '-o', default='region_gemini_output',
                       help='出力ディレクトリ')
    parser.add_argument('--api-key', help='Gemini APIキー（環境変数より優先）')
    parser.add_argument('--no-gemini', action='store_true',
                       help='Gemini解析をスキップ')
    
    args = parser.parse_args()
    
    # プロセッサを初期化
    if args.no_gemini:
        # Gemini解析なし（領域切り出しのみ）
        processor = RegionBasedProcessor()
        results = processor.process_document_with_regions(args.pdf_path, args.output)
    else:
        # Gemini解析あり
        processor = RegionGeminiProcessor(api_key=args.api_key)
        results = processor.process_document_complete(args.pdf_path, args.output)
    
    return results


if __name__ == "__main__":
    main()