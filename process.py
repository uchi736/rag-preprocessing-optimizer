#!/usr/bin/env python
"""
統一PDFプロセッサー - すべての機能を1つのコマンドで実行
Gemini 2.0 Flash対応
"""

import os
import sys
import argparse
from pathlib import Path
import json
import shutil
from typing import Optional, Dict
import google.generativeai as genai
from dotenv import load_dotenv

# .envファイルを読み込み
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from core.practical_optimizer import PracticalDocumentProcessor, PracticalConfig
from export_separated import SeparatedExporter
from extract_text import extract_text_from_summary


class UnifiedProcessor:
    """統一プロセッサー - すべての処理を一括実行"""
    
    def __init__(self, output_format: str = "all", use_gemini: bool = True):
        """
        Args:
            output_format: 出力形式 (all/text/image/separated)
            use_gemini: Gemini 2.0 Flashを使用するか
        """
        self.output_format = output_format
        self.use_gemini = use_gemini
        
        # Gemini設定
        if use_gemini:
            self._setup_gemini()
    
    def _setup_gemini(self):
        """Gemini 2.0 Flash設定"""
        gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            # Gemini 2.0 Flash Experimental（最新版）
            self.gemini_model = genai.GenerativeModel('gemini-2.0-flash-exp')
            print("[OK] Gemini 2.0 Flash準備完了")
        else:
            print("[WARNING] GEMINI_API_KEY未設定 - 画像のAI解析は利用できません")
            self.gemini_model = None
    
    def process(self, pdf_path: str, output_dir: str = None, 
                parallel: bool = True, keep_intermediate: bool = False) -> Dict:
        """
        PDFを処理してすべての形式で出力
        
        Args:
            pdf_path: 入力PDFパス
            output_dir: 出力ディレクトリ（デフォルト: PDFと同じ場所/output）
            parallel: 並列処理を使用
            keep_intermediate: 中間ファイルを保持
            
        Returns:
            処理結果の統計情報
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"[ERROR] ファイルが見つかりません: {pdf_path}")
            sys.exit(1)
        
        # 出力ディレクトリ設定
        if output_dir is None:
            output_dir = pdf_path.parent / f"{pdf_path.stem}_output"
        else:
            output_dir = Path(output_dir)
        
        print(f"\n[INPUT] {pdf_path}")
        print(f"[OUTPUT] {output_dir}")
        print(f"[FORMAT] {self.output_format}")
        print("="*60)
        
        # メイン出力ディレクトリ作成
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ステップ1: PDFを処理
        print("\n[1/3] PDF解析中...")
        config = PracticalConfig()
        processor = PracticalDocumentProcessor(config)
        
        # 一時ディレクトリに画像を保存
        temp_img_dir = output_dir / "_temp_images"
        temp_img_dir.mkdir(exist_ok=True)
        
        if parallel:
            results = processor.process_pdf_parallel(str(pdf_path), str(temp_img_dir))
        else:
            results = processor.process_pdf(str(pdf_path), str(temp_img_dir))
        
        # processing_summary.jsonを保存
        summary_path = output_dir / "processing_summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"  [OK] 解析完了: {results['total_pages']}ページ")
        
        stats = {
            'total_pages': results['total_pages'],
            'text_pages': results['summary']['text_pages'],
            'image_pages': results['summary']['image_pages'],
            'table_pages': 0,
            'output_files': {}
        }
        
        # ステップ2: Gemini解析（画像ページがある場合）
        if self.use_gemini and self.gemini_model and results['summary']['image_pages'] > 0:
            print(f"\n[2/3] Gemini 2.0 Flashで画像解析中...")
            self._analyze_images_with_gemini(results, temp_img_dir)
            print(f"  [OK] 画像解析完了: {results['summary']['image_pages']}ページ")
        else:
            print("\n[2/3] 画像解析スキップ")
        
        # ステップ3: 出力形式に応じた処理
        print(f"\n[3/3] データ出力中...")
        
        if self.output_format in ["all", "text"]:
            # テキスト出力
            text_file = output_dir / "extracted_text.txt"
            extract_text_from_summary(str(summary_path), str(text_file))
            stats['output_files']['text'] = str(text_file)
            print(f"  [OK] テキスト: {text_file.name}")
        
        if self.output_format in ["all", "separated"]:
            # タイプ別分離出力
            separated_dir = output_dir / "separated"
            exporter = SeparatedExporter(str(separated_dir))
            sep_stats = exporter.export_from_summary(str(summary_path))
            stats['table_pages'] = sep_stats['table_files']
            stats['output_files']['separated'] = str(separated_dir)
            print(f"  [OK] 分離出力: {separated_dir.name}/")
            print(f"     - テキスト: {sep_stats['text_pages']}ページ")
            print(f"     - 表: {sep_stats['table_files']}ファイル")
            print(f"     - 画像: {sep_stats['image_files']}ファイル")
        
        if self.output_format in ["all", "image"]:
            # 画像を正式な場所に移動
            images_dir = output_dir / "images"
            if temp_img_dir.exists():
                if images_dir.exists():
                    shutil.rmtree(images_dir)
                shutil.move(str(temp_img_dir), str(images_dir))
                stats['output_files']['images'] = str(images_dir)
                print(f"  [OK] 画像: {images_dir.name}/")
        
        # 中間ファイルのクリーンアップ
        if not keep_intermediate:
            if temp_img_dir.exists():
                shutil.rmtree(temp_img_dir)
        
        # 最終サマリー
        self._print_summary(stats, output_dir)
        
        return stats
    
    def _analyze_images_with_gemini(self, results: Dict, img_dir: Path):
        """Gemini 2.0 Flashで画像を解析"""
        if not self.gemini_model:
            return
        
        from PIL import Image
        
        for page_info in results['processed_pages']:
            if 'image_path' in page_info:
                img_path = Path(page_info['image_path'])
                if img_path.exists():
                    try:
                        # 画像を読み込み
                        image = Image.open(img_path)
                        
                        # ページタイプに応じたプロンプト
                        page_type = page_info.get('page_type', 'unknown')
                        
                        if page_type == 'flowchart':
                            prompt = """この画像はフローチャートです。以下を分析してください：
1. プロセスの流れを順番に説明
2. 各ステップの内容
3. 分岐条件があれば説明
4. 全体の目的

簡潔に日本語で説明してください。"""
                        elif page_type == 'complex_table':
                            prompt = """この画像は表です。以下を抽出してください：
1. 表のヘッダー（列名）
2. 主要なデータ項目
3. 表が示す内容の要約

構造化された形式で日本語で記述してください。"""
                        else:
                            prompt = """この画像の内容を詳細に説明してください。
図表、テキスト、データなどすべての要素を含めて日本語で記述してください。"""
                        
                        # Gemini解析
                        response = self.gemini_model.generate_content([prompt, image])
                        
                        # 結果を保存
                        page_info['gemini_analysis'] = response.text
                        
                    except Exception as e:
                        print(f"    [WARNING] ページ{page_info['page_number']}の解析エラー: {e}")
                        page_info['gemini_analysis'] = f"解析エラー: {str(e)}"
    
    def _print_summary(self, stats: Dict, output_dir: Path):
        """処理結果のサマリー表示"""
        print("\n" + "="*60)
        print("処理完了！")
        print("="*60)
        print(f"統計:")
        print(f"  - 総ページ数: {stats['total_pages']}")
        print(f"  - テキストページ: {stats['text_pages']}")
        print(f"  - 画像ページ: {stats['image_pages']}")
        print(f"  - 表ファイル: {stats['table_pages']}")
        
        print(f"\n出力先: {output_dir}")
        for file_type, file_path in stats['output_files'].items():
            print(f"  - {file_type}: {Path(file_path).name}")


def main():
    parser = argparse.ArgumentParser(
        description="統一PDFプロセッサー (Gemini 2.0 Flash対応)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # すべての形式で出力（デフォルト）
  python process.py input.pdf
  
  # テキストのみ抽出
  python process.py input.pdf --format text
  
  # タイプ別に分離
  python process.py input.pdf --format separated
  
  # 出力先を指定
  python process.py input.pdf -o my_output
  
  # Geminiを使わない（高速）
  python process.py input.pdf --no-gemini
  
  # シーケンシャル処理（メモリ節約）
  python process.py input.pdf --sequential

環境変数:
  GEMINI_API_KEY または GOOGLE_API_KEY を設定してください
"""
    )
    
    parser.add_argument('pdf', help='入力PDFファイル')
    parser.add_argument('-o', '--output', help='出力ディレクトリ')
    parser.add_argument(
        '-f', '--format',
        choices=['all', 'text', 'image', 'separated'],
        default='all',
        help='出力形式 (デフォルト: all)'
    )
    parser.add_argument(
        '--no-gemini',
        action='store_true',
        help='Gemini解析を無効化（高速処理）'
    )
    parser.add_argument(
        '--sequential',
        action='store_true',
        help='シーケンシャル処理（並列処理を無効化）'
    )
    parser.add_argument(
        '--keep-intermediate',
        action='store_true',
        help='中間ファイルを保持'
    )
    
    args = parser.parse_args()
    
    # プロセッサー作成
    processor = UnifiedProcessor(
        output_format=args.format,
        use_gemini=not args.no_gemini
    )
    
    # 処理実行
    processor.process(
        args.pdf,
        args.output,
        parallel=not args.sequential,
        keep_intermediate=args.keep_intermediate
    )


if __name__ == "__main__":
    main()