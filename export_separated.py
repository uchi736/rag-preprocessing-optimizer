"""
PDFから抽出したコンテンツをタイプ別に分離して保存
- テキスト → text/
- 表 → tables/
- 画像 → images/
"""

import json
import os
import sys
from pathlib import Path
import fitz
import pandas as pd
import argparse
from typing import Dict, List, Optional
import shutil

sys.path.insert(0, str(Path(__file__).parent))

from config.config import Config
from core.practical_optimizer import PracticalDocumentProcessor, PracticalConfig


class SeparatedExporter:
    """コンテンツをタイプ別に分離してエクスポート"""
    
    def __init__(self, base_output_dir: str = "output_separated"):
        self.base_output_dir = Path(base_output_dir)
        self.text_dir = self.base_output_dir / "text"
        self.tables_dir = self.base_output_dir / "tables"
        self.images_dir = self.base_output_dir / "images"
        
        # ディレクトリ作成
        for dir_path in [self.text_dir, self.tables_dir, self.images_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def export_from_summary(self, summary_path: str) -> Dict[str, int]:
        """
        processing_summary.jsonから分離エクスポート
        
        Returns:
            各タイプのファイル数
        """
        with open(summary_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        stats = {
            'text_pages': 0,
            'table_files': 0,
            'image_files': 0
        }
        
        # メインテキストファイル（テキストのみのページ）
        main_text = []
        
        # ページごとに処理
        for page_info in data['processed_pages']:
            page_num = page_info['page_number']
            
            # スキップページは除外
            if page_info.get('skip'):
                continue
            
            # 1. テキストの処理
            if 'text' in page_info and page_info['text'].strip():
                # ページごとのテキストファイル
                text_file = self.text_dir / f"page_{page_num:03d}.txt"
                with open(text_file, 'w', encoding='utf-8') as f:
                    f.write(f"# ページ {page_num}\n")
                    f.write("="*40 + "\n\n")
                    f.write(page_info['text'])
                
                # メインテキストにも追加（画像ページ以外）
                if page_info['processing_method'] == 'text_only':
                    main_text.append(f"\n[ページ {page_num}]\n")
                    main_text.append(page_info['text'])
                    stats['text_pages'] += 1
            
            # 2. 表の処理
            if 'structured_data' in page_info:
                for idx, table_data in enumerate(page_info['structured_data']):
                    if table_data['type'] == 'table' and table_data.get('data'):
                        # CSV形式で保存
                        table_file = self.tables_dir / f"page_{page_num:03d}_table_{idx+1}.csv"
                        df = pd.DataFrame(table_data['data'])
                        df.to_csv(table_file, index=False, encoding='utf-8-sig')
                        
                        # Excel形式でも保存（openpyxlが利用可能な場合のみ）
                        try:
                            excel_file = self.tables_dir / f"page_{page_num:03d}_table_{idx+1}.xlsx"
                            df.to_excel(excel_file, index=False, engine='openpyxl')
                        except ImportError:
                            pass  # openpyxlがない場合はスキップ
                        
                        stats['table_files'] += 1
            
            # 3. 画像の処理（既存の画像をコピー）
            if 'image_path' in page_info:
                src_path = Path(page_info['image_path'])
                if src_path.exists():
                    # 画像タイプごとにサブフォルダ作成
                    page_type = page_info.get('page_type', 'unknown')
                    type_dir = self.images_dir / page_type
                    type_dir.mkdir(exist_ok=True)
                    
                    dst_path = type_dir / src_path.name
                    shutil.copy2(src_path, dst_path)
                    stats['image_files'] += 1
                    
                    # Gemini解析結果があればテキストファイルとして保存
                    if 'gemini_analysis' in page_info:
                        analysis_file = type_dir / f"{src_path.stem}_analysis.txt"
                        with open(analysis_file, 'w', encoding='utf-8') as f:
                            f.write(f"# ページ {page_num} - Gemini 2.0 Flash解析\n")
                            f.write(f"画像ファイル: {src_path.name}\n")
                            f.write("="*60 + "\n\n")
                            f.write(page_info['gemini_analysis'])
        
        # メインテキストファイルを保存
        if main_text:
            main_text_file = self.text_dir / "all_text_pages.txt"
            with open(main_text_file, 'w', encoding='utf-8') as f:
                f.write("".join(main_text))
        
        # インデックスファイルを作成
        self._create_index(data, stats)
        
        return stats
    
    def export_from_pdf(self, pdf_path: str, use_parallel: bool = True) -> Dict[str, int]:
        """
        PDFから直接分離エクスポート
        
        Args:
            pdf_path: PDFファイルのパス
            use_parallel: 並列処理を使用するか
            
        Returns:
            各タイプのファイル数
        """
        print(f"PDFを処理中: {pdf_path}")
        
        # 一時的な出力ディレクトリ
        temp_output = self.base_output_dir / "temp"
        temp_output.mkdir(exist_ok=True)
        
        # PDFを処理
        config = PracticalConfig()
        processor = PracticalDocumentProcessor(config)
        
        if use_parallel:
            results = processor.process_pdf_parallel(pdf_path, str(temp_output))
        else:
            results = processor.process_pdf(pdf_path, str(temp_output))
        
        stats = {
            'text_pages': 0,
            'table_files': 0,
            'image_files': 0
        }
        
        # メインテキストファイル
        main_text = []
        
        # ページごとに処理
        for page_info in results['processed_pages']:
            page_num = page_info['page_number']
            
            # スキップページは除外
            if page_info.get('skip'):
                continue
            
            # 1. テキストの処理
            if 'text' in page_info and page_info['text'].strip():
                # ページごとのテキストファイル
                text_file = self.text_dir / f"page_{page_num:03d}.txt"
                with open(text_file, 'w', encoding='utf-8') as f:
                    f.write(f"# ページ {page_num}\n")
                    f.write("="*40 + "\n\n")
                    f.write(page_info['text'])
                
                # テキストのみのページはメインテキストに追加
                if page_info['processing_method'] == 'text_only':
                    main_text.append(f"\n[ページ {page_num}]\n")
                    main_text.append("-"*40 + "\n")
                    main_text.append(page_info['text'])
                    main_text.append("\n")
                    stats['text_pages'] += 1
            
            # 2. 表の処理
            if 'structured_data' in page_info:
                for idx, table_data in enumerate(page_info['structured_data']):
                    if table_data['type'] == 'table' and table_data.get('data'):
                        # CSV形式で保存
                        table_file = self.tables_dir / f"page_{page_num:03d}_table_{idx+1}.csv"
                        df = pd.DataFrame(table_data['data'])
                        df.to_csv(table_file, index=False, encoding='utf-8-sig')
                        
                        # Excel形式でも保存（openpyxlが利用可能な場合のみ）
                        try:
                            excel_file = self.tables_dir / f"page_{page_num:03d}_table_{idx+1}.xlsx"
                            df.to_excel(excel_file, index=False, engine='openpyxl')
                        except ImportError:
                            pass  # openpyxlがない場合はスキップ
                        
                        # Markdown形式でも保存（tabulateが利用可能な場合のみ）
                        try:
                            md_file = self.tables_dir / f"page_{page_num:03d}_table_{idx+1}.md"
                            with open(md_file, 'w', encoding='utf-8') as f:
                                f.write(f"# ページ {page_num} - 表 {idx+1}\n\n")
                                f.write(df.to_markdown(index=False))
                        except ImportError:
                            # tabulateがない場合は簡易形式で保存
                            md_file = self.tables_dir / f"page_{page_num:03d}_table_{idx+1}.md"
                            with open(md_file, 'w', encoding='utf-8') as f:
                                f.write(f"# ページ {page_num} - 表 {idx+1}\n\n")
                                f.write(df.to_string())
                        
                        stats['table_files'] += 1
            
            # 3. 画像の処理
            if 'image_path' in page_info:
                src_path = Path(page_info['image_path'])
                if src_path.exists():
                    # 画像タイプごとにサブフォルダ作成
                    page_type = page_info.get('page_type', 'unknown')
                    type_dir = self.images_dir / page_type
                    type_dir.mkdir(exist_ok=True)
                    
                    dst_path = type_dir / src_path.name
                    shutil.move(str(src_path), str(dst_path))
                    stats['image_files'] += 1
        
        # メインテキストファイルを保存
        if main_text:
            main_text_file = self.text_dir / "all_text_pages.txt"
            with open(main_text_file, 'w', encoding='utf-8') as f:
                f.write("".join(main_text))
            print(f"メインテキスト保存: {main_text_file}")
        
        # 処理サマリーも保存
        summary_file = self.base_output_dir / "processing_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        
        # インデックスファイルを作成
        self._create_index(results, stats)
        
        # 一時ディレクトリをクリーンアップ
        if temp_output.exists():
            shutil.rmtree(temp_output)
        
        return stats
    
    def _create_index(self, data: Dict, stats: Dict):
        """インデックスファイルを作成"""
        index_file = self.base_output_dir / "index.md"
        
        # Gemini解析済みページ数をカウント
        gemini_analyzed = sum(1 for page in data['processed_pages'] 
                            if 'gemini_analysis' in page)
        
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write("# 抽出コンテンツインデックス\n\n")
            
            # 統計情報
            f.write("## 統計\n")
            f.write(f"- 総ページ数: {data['total_pages']}\n")
            f.write(f"- テキストページ: {stats['text_pages']}\n")
            f.write(f"- 表ファイル: {stats['table_files']}\n")
            f.write(f"- 画像ファイル: {stats['image_files']}\n")
            if gemini_analyzed > 0:
                f.write(f"- Gemini解析済み: {gemini_analyzed}ページ\n")
            f.write("\n")
            
            # ディレクトリ構造
            f.write("## ディレクトリ構造\n")
            f.write("```\n")
            f.write(f"{self.base_output_dir.name}/\n")
            f.write("├── text/          # テキストファイル\n")
            f.write("│   ├── all_text_pages.txt  # メインテキスト\n")
            f.write("│   └── page_XXX.txt        # ページごとのテキスト\n")
            f.write("├── tables/        # 表データ\n")
            f.write("│   ├── *.csv      # CSV形式\n")
            f.write("│   ├── *.xlsx     # Excel形式\n")
            f.write("│   └── *.md       # Markdown形式\n")
            f.write("└── images/        # 画像ファイル\n")
            f.write("    ├── flowchart/ # フローチャート\n")
            f.write("    ├── diagram/   # ダイアグラム\n")
            f.write("    └── table/     # 複雑な表\n")
            f.write("```\n\n")
            
            # ファイルリスト
            f.write("## ファイルリスト\n\n")
            
            # テキストファイル
            f.write("### テキストファイル\n")
            for text_file in sorted(self.text_dir.glob("*.txt")):
                f.write(f"- {text_file.name}\n")
            f.write("\n")
            
            # 表ファイル
            if list(self.tables_dir.glob("*.csv")):
                f.write("### 表ファイル\n")
                for table_file in sorted(self.tables_dir.glob("*.csv")):
                    f.write(f"- {table_file.name}\n")
                f.write("\n")
            
            # 画像ファイル
            if list(self.images_dir.rglob("*.png")):
                f.write("### 画像ファイル\n")
                for img_dir in sorted(self.images_dir.iterdir()):
                    if img_dir.is_dir():
                        f.write(f"\n#### {img_dir.name}\n")
                        for img_file in sorted(img_dir.glob("*.png")):
                            f.write(f"- {img_file.name}\n")
        
        print(f"インデックス作成: {index_file}")


def main():
    parser = argparse.ArgumentParser(
        description="PDFコンテンツをタイプ別に分離して保存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # PDFから直接エクスポート
  python export_separated.py input.pdf
  
  # 出力先を指定
  python export_separated.py input.pdf -o my_output
  
  # processing_summary.jsonからエクスポート
  python export_separated.py output/processing_summary.json --from-summary
  
  # シーケンシャル処理（メモリ節約）
  python export_separated.py input.pdf --sequential
"""
    )
    
    parser.add_argument('input', help='入力ファイル（PDFまたはprocessing_summary.json）')
    parser.add_argument('-o', '--output', default='output_separated',
                       help='出力ディレクトリ（デフォルト: output_separated）')
    parser.add_argument('--from-summary', action='store_true',
                       help='processing_summary.jsonから処理')
    parser.add_argument('--sequential', action='store_true',
                       help='シーケンシャル処理（並列処理を無効化）')
    
    args = parser.parse_args()
    
    # 入力ファイルの確認
    if not os.path.exists(args.input):
        print(f"エラー: ファイルが見つかりません: {args.input}")
        sys.exit(1)
    
    # エクスポーター作成
    exporter = SeparatedExporter(args.output)
    
    print(f"出力先: {exporter.base_output_dir}")
    print("="*60)
    
    # 処理実行
    if args.from_summary or args.input.endswith('.json'):
        # JSONから処理
        stats = exporter.export_from_summary(args.input)
    else:
        # PDFから処理
        stats = exporter.export_from_pdf(args.input, use_parallel=not args.sequential)
    
    # 結果表示
    print("\n" + "="*60)
    print("処理完了！")
    print(f"  テキストページ: {stats['text_pages']}")
    print(f"  表ファイル: {stats['table_files']}")
    print(f"  画像ファイル: {stats['image_files']}")
    print(f"\n出力先: {exporter.base_output_dir}")
    print(f"  テキスト: {exporter.text_dir}")
    print(f"  表: {exporter.tables_dir}")
    print(f"  画像: {exporter.images_dir}")


if __name__ == "__main__":
    main()