"""
誤検出診断ツール - どこで誤検出が起きているか特定
"""

import os
import sys
from pathlib import Path
import fitz
from typing import Dict, List, Tuple
from enum import Enum

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from config.config import Config
from core.practical_optimizer import PracticalPageAnalyzer, PageType, PracticalConfig
from core.smart_page_analyzer import SmartPageAnalyzer


class DiagnosticResult:
    """診断結果を保持"""
    def __init__(self):
        self.total_pages = 0
        self.disagreements = []
        self.practical_false_positives = 0
        self.practical_false_negatives = 0
        self.smart_false_positives = 0
        self.smart_false_negatives = 0
        

def diagnose_false_positives(pdf_path: str, manual_check: bool = False) -> DiagnosticResult:
    """
    両アナライザーの判定を比較して誤検出を診断
    
    Args:
        pdf_path: 診断するPDFファイル
        manual_check: True の場合、不一致時に人間の判断を求める
    """
    print(f"\n{'='*60}")
    print(f"診断開始: {pdf_path}")
    print(f"{'='*60}\n")
    
    # 設定とアナライザーの初期化
    config = Config()
    practical_config = PracticalConfig()
    practical = PracticalPageAnalyzer(practical_config)
    smart = SmartPageAnalyzer(config)
    
    result = DiagnosticResult()
    
    try:
        doc = fitz.open(pdf_path)
        result.total_pages = doc.page_count
        
        print(f"総ページ数: {doc.page_count}\n")
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            # 両方のアナライザーで解析
            practical_result = practical.analyze_page(page, page_num)
            smart_result = smart.analyze_page_content(page)
            
            # スキップページは除外
            if practical_result.get('skip'):
                continue
            
            # 判定結果を取得
            p_has_figure = practical_result['page_type'] != PageType.PURE_TEXT
            s_has_figure = smart_result['has_figure']
            
            # 詳細情報を収集
            p_confidence = practical_result.get('confidence', 0)
            s_confidence = smart_result.get('confidence', 0)
            
            # 不一致を検出
            if p_has_figure != s_has_figure:
                print(f"⚠️  ページ {page_num + 1}: 判定不一致")
                print(f"   Practical: {'図表あり' if p_has_figure else 'テキストのみ'} (信頼度: {p_confidence:.2f})")
                print(f"   Smart:     {'図表あり' if s_has_figure else 'テキストのみ'} (信頼度: {s_confidence})")
                
                if smart_result.get('reasons'):
                    print(f"   Smart理由: {'; '.join(smart_result['reasons'][:2])}")
                
                # 視覚要素の確認
                visual_check = _check_visual_elements(page)
                print(f"   視覚要素: 図形{visual_check['drawings']}個, "
                      f"画像{visual_check['images']}個, "
                      f"表{visual_check['tables']}個")
                
                # 人間による確認（オプション）
                actual_has_figure = None
                if manual_check:
                    response = input("   実際に図表はありますか？(y/n/s=skip): ").lower()
                    if response == 'y':
                        actual_has_figure = True
                    elif response == 'n':
                        actual_has_figure = False
                    elif response == 's':
                        continue
                else:
                    # 自動判定: 視覚要素があれば図表ありと判定
                    actual_has_figure = visual_check['total'] > 0
                    print(f"   自動判定: {'図表あり' if actual_has_figure else 'テキストのみ'}")
                
                # 誤検出・見逃しをカウント
                if actual_has_figure is not None:
                    if p_has_figure and not actual_has_figure:
                        result.practical_false_positives += 1
                        print("   → Practicalが誤検出")
                    elif not p_has_figure and actual_has_figure:
                        result.practical_false_negatives += 1
                        print("   → Practicalが見逃し")
                    
                    if s_has_figure and not actual_has_figure:
                        result.smart_false_positives += 1
                        print("   → Smartが誤検出")
                    elif not s_has_figure and actual_has_figure:
                        result.smart_false_negatives += 1
                        print("   → Smartが見逃し")
                
                result.disagreements.append({
                    'page': page_num + 1,
                    'practical': p_has_figure,
                    'smart': s_has_figure,
                    'actual': actual_has_figure
                })
                
                print()  # 空行
        
        doc.close()
        
    except Exception as e:
        print(f"エラー: {e}")
        return result
    
    # 診断結果のサマリー
    print(f"\n{'='*60}")
    print("診断結果サマリー")
    print(f"{'='*60}\n")
    
    print(f"総ページ数: {result.total_pages}")
    print(f"判定不一致: {len(result.disagreements)}ページ\n")
    
    if result.disagreements:
        print("【PracticalPageAnalyzer】")
        print(f"  誤検出: {result.practical_false_positives}ページ")
        print(f"  見逃し: {result.practical_false_negatives}ページ")
        
        print("\n【SmartPageAnalyzer】")
        print(f"  誤検出: {result.smart_false_positives}ページ")
        print(f"  見逃し: {result.smart_false_negatives}ページ")
        
        # 推奨される修正
        print(f"\n{'='*60}")
        print("推奨される修正")
        print(f"{'='*60}\n")
        
        if result.smart_false_positives > result.practical_false_positives:
            print("📍 SmartPageAnalyzerが誤検出の主要因です")
            print("   → smart_page_analyzer.py の127-137行目を修正")
            print("   → キーワードのみでの図表判定を無効化")
        elif result.practical_false_positives > result.smart_false_positives:
            print("📍 PracticalPageAnalyzerが誤検出の主要因です")
            print("   → practical_optimizer.py に視覚要素チェックを追加")
        else:
            print("📍 両方のアナライザーに問題があります")
            print("   → 統合アナライザーの実装を検討")
    else:
        print("✅ 判定の不一致はありませんでした")
    
    return result


def _check_visual_elements(page: fitz.Page) -> Dict:
    """ページの視覚要素をカウント"""
    result = {
        'drawings': 0,
        'images': 0,
        'tables': 0,
        'total': 0
    }
    
    try:
        # 図形要素
        drawings = page.get_drawings()
        result['drawings'] = len(list(drawings))
    except:
        pass
    
    try:
        # 画像
        images = page.get_images(full=True)
        result['images'] = len(images)
    except:
        pass
    
    try:
        # テーブル
        tables = page.find_tables()
        result['tables'] = len(list(tables))
    except:
        pass
    
    result['total'] = result['drawings'] + result['images'] + result['tables']
    
    return result


def analyze_pattern(pdf_paths: List[str]):
    """複数のPDFを分析してパターンを発見"""
    
    all_results = []
    
    for pdf_path in pdf_paths:
        if os.path.exists(pdf_path):
            result = diagnose_false_positives(pdf_path, manual_check=False)
            all_results.append((pdf_path, result))
    
    # 統計分析
    total_smart_fp = sum(r.smart_false_positives for _, r in all_results)
    total_practical_fp = sum(r.practical_false_positives for _, r in all_results)
    
    print(f"\n{'='*60}")
    print("全体統計")
    print(f"{'='*60}\n")
    print(f"分析ファイル数: {len(all_results)}")
    print(f"Smart誤検出合計: {total_smart_fp}")
    print(f"Practical誤検出合計: {total_practical_fp}")
    
    if total_smart_fp > total_practical_fp * 1.5:
        print("\n⚠️ SmartPageAnalyzerに系統的な問題があります")
    elif total_practical_fp > total_smart_fp * 1.5:
        print("\n⚠️ PracticalPageAnalyzerに系統的な問題があります")


def main():
    """メイン実行関数"""
    
    # テスト用PDFを検索
    test_pdfs = []
    for root, dirs, files in os.walk("data"):
        for file in files:
            if file.endswith(".pdf"):
                test_pdfs.append(os.path.join(root, file))
    
    if not test_pdfs:
        print("テスト用PDFファイルが見つかりません。")
        print("data/フォルダにPDFファイルを配置してください。")
        
        # ダミーファイルで診断のデモ
        print("\n診断ツールのデモモード")
        print("実際のPDFがないため、仮想的な診断結果を表示します。")
        
        result = DiagnosticResult()
        result.total_pages = 10
        result.smart_false_positives = 3
        result.practical_false_positives = 1
        
        print("\n診断結果（デモ）:")
        print(f"  Smart誤検出: {result.smart_false_positives}ページ")
        print(f"  Practical誤検出: {result.practical_false_positives}ページ")
        print("\n→ SmartPageAnalyzerの修正が推奨されます")
        
        return
    
    # 最初のPDFを診断
    pdf_path = test_pdfs[0]
    
    # 自動診断モード
    print("自動診断モードで実行します")
    diagnose_false_positives(pdf_path, manual_check=False)
    
    # 複数ファイルがある場合はパターン分析
    if len(test_pdfs) > 1:
        print(f"\n\n複数ファイル({len(test_pdfs)}個)のパターン分析...")
        analyze_pattern(test_pdfs[:5])  # 最大5ファイル


if __name__ == "__main__":
    main()