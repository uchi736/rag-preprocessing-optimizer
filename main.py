"""
前処理最適化システム - メインモジュール
日本語技術文書に最適化されたPDF前処理システム
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
import argparse
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

from core.practical_optimizer import (
    PracticalConfig,
    PracticalDocumentProcessor,
    calculate_roi
)
from config.config import Config


class AdvancedRAGPreprocessor:
    """AdvancedRAG用の前処理システム"""
    
    def __init__(self, config: Optional[PracticalConfig] = None):
        """
        Args:
            config: カスタム設定（省略時はデフォルト設定を使用）
        """
        self.config = config or self._get_default_config()
        self.processor = PracticalDocumentProcessor(self.config)
        self.stats = {
            'processed_files': 0,
            'total_pages': 0,
            'image_pages': 0,
            'processing_time': 0
        }
    
    def _get_default_config(self) -> PracticalConfig:
        """日本語技術文書用のデフォルト設定"""
        return PracticalConfig(
            # 日本語文書に最適化された閾値
            quick_text_density_threshold=0.75,
            min_table_cells=8,
            complex_table_cell_threshold=30,
            high_confidence_threshold=0.8,
            
            # 図番号パターン（自動設定済み）
            # 図1-1, 表2-3, Fig.1-1 などを自動検出
        )
    
    def process_pdf(self, pdf_path: str, output_dir: Optional[str] = None, 
                    use_parallel: bool = True) -> Dict:
        """
        PDFファイルを処理
        
        Args:
            pdf_path: PDFファイルのパス
            output_dir: 出力ディレクトリ（省略時は'output'）
            use_parallel: 並列処理を使用するか（デフォルト: True）
            
        Returns:
            処理結果の辞書
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDFファイルが見つかりません: {pdf_path}")
        
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(pdf_path), 'output')
        
        print(f"処理開始: {pdf_path}")
        print(f"出力先: {output_dir}")
        print(f"処理モード: {'並列' if use_parallel else '逐次'}")
        print("-" * 50)
        
        try:
            # 処理実行
            if use_parallel:
                results = self.processor.process_pdf_parallel(pdf_path, output_dir)
            else:
                results = self.processor.process_pdf(pdf_path, output_dir)
        except Exception as e:
            print(f"エラー: PDFの処理中に問題が発生しました - {str(e)}")
            # エラー情報を含む結果を返す
            return {
                'pdf_path': pdf_path,
                'error': str(e),
                'total_pages': 0,
                'processed_pages': [],
                'summary': {
                    'text_pages': 0,
                    'image_pages': 0,
                    'hybrid_pages': 0,
                    'skipped_pages': 0,
                    'total_cost': 0
                },
                'processing_time': 0
            }
        
        # 統計更新
        self.stats['processed_files'] += 1
        self.stats['total_pages'] += results['total_pages']
        self.stats['image_pages'] += results['summary']['image_pages']
        self.stats['processing_time'] += results['processing_time']
        
        # ROI計算
        roi_info = calculate_roi(results)
        
        # サマリー表示
        self._print_summary(results, roi_info)
        
        return results
    
    def process_directory(self, directory: str, output_dir: Optional[str] = None,
                         use_parallel: bool = True) -> List[Dict]:
        """
        ディレクトリ内の全PDFを処理
        
        Args:
            directory: PDFファイルを含むディレクトリ
            output_dir: 出力ディレクトリ
            use_parallel: 並列処理を使用するか
            
        Returns:
            各ファイルの処理結果リスト
        """
        pdf_files = list(Path(directory).glob("*.pdf"))
        if not pdf_files:
            print(f"PDFファイルが見つかりません: {directory}")
            return []
        
        print(f"{len(pdf_files)}個のPDFファイルを処理します")
        
        results = []
        for pdf_path in pdf_files:
            try:
                result = self.process_pdf(str(pdf_path), output_dir, use_parallel=use_parallel)
                results.append(result)
            except Exception as e:
                print(f"エラー: {pdf_path} - {str(e)}")
                results.append({
                    'pdf_path': str(pdf_path),
                    'error': str(e),
                    'total_pages': 0,
                    'processing_time': 0
                })
        
        # 全体統計表示
        self._print_overall_stats()
        
        return results
    
    def _print_summary(self, results: Dict, roi_info: Dict):
        """処理結果のサマリーを表示"""
        summary = results['summary']
        
        print(f"\n処理完了: {results['pdf_path']}")
        print(f"総ページ数: {results['total_pages']}")
        print(f"画像化ページ: {summary['image_pages']} ({summary['image_pages']/results['total_pages']*100:.1f}%)")
        print(f"処理時間: {results['processing_time']:.2f}秒")
        print(f"ROI: {roi_info['roi']:.2%}")
        print("-" * 50)
    
    def _print_overall_stats(self):
        """全体統計を表示"""
        if self.stats['processed_files'] == 0:
            return
        
        print("\n" + "=" * 50)
        print("全体統計")
        print("=" * 50)
        print(f"処理ファイル数: {self.stats['processed_files']}")
        print(f"総ページ数: {self.stats['total_pages']}")
        print(f"画像化ページ数: {self.stats['image_pages']} ({self.stats['image_pages']/self.stats['total_pages']*100:.1f}%)")
        print(f"総処理時間: {self.stats['processing_time']:.2f}秒")
        print(f"平均処理時間: {self.stats['processing_time']/self.stats['processed_files']:.2f}秒/ファイル")


def main():
    """CLI エントリーポイント"""
    parser = argparse.ArgumentParser(
        description="AdvancedRAG前処理システム - 日本語技術文書に最適化されたPDF処理"
    )
    
    parser.add_argument(
        "input",
        help="処理するPDFファイルまたはディレクトリのパス"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="出力ディレクトリ（デフォルト: 入力ファイルと同じ場所）",
        default=None
    )
    
    parser.add_argument(
        "--config",
        help="カスタム設定ファイル（JSON形式）",
        default=None
    )
    
    parser.add_argument(
        "--verbose",
        help="詳細な出力",
        action="store_true"
    )
    
    parser.add_argument(
        "--no-parallel",
        help="並列処理を無効化（デフォルトは有効）",
        action="store_true"
    )
    
    parser.add_argument(
        "--dpi-multiplier",
        help="画像化時のDPI倍率（デフォルト: 2.0）",
        type=float,
        default=2.0
    )
    
    args = parser.parse_args()
    
    # カスタム設定の読み込み
    config = None
    if args.config:
        with open(args.config, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            config = PracticalConfig(**config_data)
    else:
        config = PracticalConfig()
    
    # コマンドライン引数から設定を上書き
    config.image_dpi_multiplier = args.dpi_multiplier
    
    # プロセッサーの初期化
    preprocessor = AdvancedRAGPreprocessor(config)
    
    # 処理実行
    input_path = Path(args.input)
    use_parallel = not args.no_parallel
    
    try:
        if input_path.is_file() and input_path.suffix.lower() == '.pdf':
            # 単一ファイル処理
            preprocessor.process_pdf(str(input_path), args.output, use_parallel=use_parallel)
        elif input_path.is_dir():
            # ディレクトリ処理
            preprocessor.process_directory(str(input_path), args.output, use_parallel=use_parallel)
        else:
            print(f"エラー: 有効なPDFファイルまたはディレクトリを指定してください: {args.input}")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()