"""
PDFからテキストを抽出して保存するツール
処理済みのprocessing_summary.jsonまたは直接PDFから抽出可能
"""

import json
import os
import sys
from pathlib import Path
import fitz
import argparse
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from config.config import Config
from core.practical_optimizer import PracticalDocumentProcessor, PracticalConfig


def extract_text_from_summary(summary_path: str, output_path: Optional[str] = None) -> str:
    """
    processing_summary.jsonからテキストを抽出
    
    Args:
        summary_path: processing_summary.jsonのパス
        output_path: 出力テキストファイルのパス（省略時は同じディレクトリ）
    
    Returns:
        抽出されたテキスト
    """
    with open(summary_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # テキストを結合
    all_text = []
    all_text.append(f"# {Path(data['pdf_path']).name}\n")
    all_text.append(f"総ページ数: {data['total_pages']}\n")
    all_text.append("="*60 + "\n\n")
    
    for page_info in data['processed_pages']:
        page_num = page_info['page_number']
        
        # スキップページは除外
        if page_info.get('skip'):
            all_text.append(f"\n[ページ {page_num}] スキップ - {page_info.get('reason', '')}\n")
            continue
        
        all_text.append(f"\n[ページ {page_num}]\n")
        all_text.append("-"*40 + "\n")
        
        # テキストコンテンツ
        if 'text' in page_info and page_info['text']:
            all_text.append(page_info['text'])
            all_text.append("\n")
        
        # 構造化データ（表）
        if 'structured_data' in page_info:
            for table_data in page_info['structured_data']:
                if table_data['type'] == 'table':
                    all_text.append("\n[表データ]\n")
                    # 表をテキスト形式で表現
                    for row in table_data['data']:
                        all_text.append(" | ".join(str(v) for v in row.values()))
                        all_text.append("\n")
        
        # 画像の場合はパスを記載
        if 'image_path' in page_info:
            all_text.append(f"\n[画像: {page_info['image_path']}]\n")
            if page_info['processing_method'] == 'image_with_ocr':
                all_text.append("（OCR処理が必要）\n")
            elif page_info['processing_method'] == 'image_with_analysis':
                all_text.append("（AI画像解析が必要）\n")
            
            # Gemini解析結果があれば追加
            if 'gemini_analysis' in page_info:
                all_text.append("\n[Gemini 2.0 Flash解析結果]\n")
                all_text.append(page_info['gemini_analysis'])
                all_text.append("\n")
    
    # 結合
    full_text = "".join(all_text)
    
    # ファイルに保存
    if output_path is None:
        output_dir = Path(summary_path).parent
        output_path = output_dir / "extracted_text.txt"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    
    print(f"テキストを保存しました: {output_path}")
    return full_text


def extract_text_from_pdf(pdf_path: str, output_path: Optional[str] = None, 
                          use_optimizer: bool = True) -> str:
    """
    PDFから直接テキストを抽出
    
    Args:
        pdf_path: PDFファイルのパス
        output_path: 出力テキストファイルのパス
        use_optimizer: 最適化処理を使用するか
    
    Returns:
        抽出されたテキスト
    """
    if output_path is None:
        output_path = Path(pdf_path).with_suffix('.txt')
    
    all_text = []
    all_text.append(f"# {Path(pdf_path).name}\n")
    all_text.append("="*60 + "\n\n")
    
    if use_optimizer:
        # 最適化処理を使用
        print("最適化処理でテキスト抽出中...")
        config = PracticalConfig()
        processor = PracticalDocumentProcessor(config)
        
        # 処理実行（出力ディレクトリなし = メモリ内処理）
        results = processor.process_pdf(pdf_path, output_dir=None)
        
        for page_info in results['processed_pages']:
            page_num = page_info['page_number']
            
            if page_info.get('skip'):
                all_text.append(f"\n[ページ {page_num}] スキップ\n")
                continue
            
            all_text.append(f"\n[ページ {page_num}]\n")
            all_text.append("-"*40 + "\n")
            
            # テキストコンテンツ
            if 'text' in page_info and page_info['text']:
                all_text.append(page_info['text'])
                all_text.append("\n")
            
            # 構造化データ
            if 'structured_data' in page_info:
                for table_data in page_info['structured_data']:
                    if table_data['type'] == 'table':
                        all_text.append("\n[表]\n")
                        for row in table_data['data']:
                            all_text.append(" | ".join(str(v) for v in row.values()))
                            all_text.append("\n")
            
            # 画像ページの場合
            if page_info['processing_method'] in ['image_with_ocr', 'image_with_analysis']:
                all_text.append(f"\n[注: ページ{page_num}は画像処理が必要です]\n")
        
        print(f"処理完了: {len(results['processed_pages'])}ページ")
    else:
        # シンプルな抽出
        print("シンプルなテキスト抽出中...")
        doc = fitz.open(pdf_path)
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            all_text.append(f"\n[ページ {page_num + 1}]\n")
            all_text.append("-"*40 + "\n")
            
            text = page.get_text()
            all_text.append(text)
            all_text.append("\n")
        
        doc.close()
        print(f"抽出完了: {doc.page_count}ページ")
    
    # 結合して保存
    full_text = "".join(all_text)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    
    print(f"テキストを保存しました: {output_path}")
    print(f"ファイルサイズ: {len(full_text):,} 文字")
    
    return full_text


def main():
    parser = argparse.ArgumentParser(
        description="PDFからテキストを抽出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # PDFから直接抽出（最適化あり）
  python extract_text.py input.pdf
  
  # PDFから直接抽出（シンプル）
  python extract_text.py input.pdf --simple
  
  # processing_summary.jsonから抽出
  python extract_text.py output/processing_summary.json --from-summary
  
  # 出力先を指定
  python extract_text.py input.pdf -o extracted.txt
"""
    )
    
    parser.add_argument('input', help='入力ファイル（PDFまたはprocessing_summary.json）')
    parser.add_argument('-o', '--output', help='出力テキストファイル')
    parser.add_argument('--from-summary', action='store_true', 
                       help='processing_summary.jsonから抽出')
    parser.add_argument('--simple', action='store_true',
                       help='シンプルな抽出（最適化なし）')
    
    args = parser.parse_args()
    
    # 入力ファイルの確認
    if not os.path.exists(args.input):
        print(f"エラー: ファイルが見つかりません: {args.input}")
        sys.exit(1)
    
    # 処理実行
    if args.from_summary or args.input.endswith('.json'):
        # JSONから抽出
        extract_text_from_summary(args.input, args.output)
    else:
        # PDFから抽出
        extract_text_from_pdf(args.input, args.output, use_optimizer=not args.simple)


if __name__ == "__main__":
    main()