# Preprocessing Optimizer アルゴリズム擬似コード

## 1. メインアルゴリズム

```pseudo
ALGORITHM ProcessPDF(pdf_path, output_dir, use_parallel)
    START_TIME ← current_time()
    doc ← open_pdf(pdf_path)
    results ← initialize_results_structure()
    
    IF use_parallel THEN
        results ← process_parallel(doc, output_dir)
    ELSE
        results ← process_sequential(doc, output_dir)
    END IF
    
    results.processing_time ← current_time() - START_TIME
    save_json(results, output_dir)
    RETURN results
END ALGORITHM
```

## 2. ページ分析アルゴリズム

```pseudo
ALGORITHM AnalyzePage(page, page_num)
    // 段階1: 高速スクリーニング
    quick_result ← QuickScreening(page, page_num)
    
    IF quick_result.skip THEN
        RETURN create_skip_result(quick_result.reason)
    END IF
    
    IF quick_result.is_pure_text THEN
        RETURN create_text_result(quick_result)
    END IF
    
    // 段階2: 詳細分析
    detailed_result ← DetailedAnalysis(page)
    
    // 段階3: 処理方法決定
    page_type, method, confidence ← DetermineProcessing(quick_result, detailed_result)
    
    RETURN create_analysis_result(page_type, method, confidence)
END ALGORITHM
```

## 3. 高速スクリーニングアルゴリズム

```pseudo
ALGORITHM QuickScreening(page, page_num)
    text ← page.get_text()
    page_area ← page.width × page.height
    
    // スキップパターンチェック
    FOR pattern IN skip_patterns DO
        IF pattern IN text[0:200] THEN
            RETURN {skip: true, reason: pattern}
        END IF
    END FOR
    
    // テキスト密度計算
    text_blocks ← get_text_blocks(page)
    text_area ← 0
    FOR block IN text_blocks DO
        text_area ← text_area + block.area
    END FOR
    text_density ← text_area / page_area
    
    // 大型画像検出
    large_images ← []
    images ← page.get_images()
    FOR image IN images DO
        pix ← create_pixmap(image)
        IF pix.width × pix.height > IMAGE_SIZE_THRESHOLD THEN
            large_images.append((pix.width, pix.height))
        END IF
        release_pixmap(pix)
    END FOR
    
    // 図番号検出
    has_figure_number ← check_figure_patterns(text)
    has_reference ← check_reference_patterns(text)
    actual_figure ← determine_actual_figure(text, has_figure_number, has_reference)
    
    // 判定
    is_pure_text ← (text_density > 0.8 AND 
                    len(large_images) = 0 AND 
                    NOT has_force_keywords AND 
                    NOT actual_figure)
    
    RETURN {
        skip: false,
        is_pure_text: is_pure_text,
        confidence: IF is_pure_text THEN 0.9 ELSE 0.5,
        features: collected_features
    }
END ALGORITHM
```

## 4. 図番号検出アルゴリズム

```pseudo
ALGORITHM DetermineActualFigure(text, has_figure_number, has_reference)
    IF NOT has_figure_number THEN
        RETURN false
    END IF
    
    IF has_reference THEN
        RETURN false
    END IF
    
    // 実際の図番号パターンチェック
    figure_patterns ← [
        r'(?:^|\n)\s*図\d+[\s　:]',      // 行頭の図番号
        r'(?:^|\n)\s*図\d+\s*(?:\n|$)',  // 独立行の図番号
        r'(?:^|\n)\s{3,}図\d+(?:\s|$)'   // 中央揃えの図番号
    ]
    
    FOR pattern IN figure_patterns DO
        IF regex_match(pattern, text) THEN
            RETURN true
        END IF
    END FOR
    
    RETURN false
END ALGORITHM
```

## 5. 処理方法決定アルゴリズム

```pseudo
ALGORITHM DetermineProcessing(quick_result, detailed_result)
    features ← quick_result.features
    
    // 優先度1: 実際の図がある場合
    IF features.actual_figure THEN
        IF detailed_result.table_count > 0 THEN
            RETURN (COMPLEX_TABLE, IMAGE_WITH_OCR, 0.85)
        ELSE IF detailed_result.rect_count > 0 OR features.large_images_count > 0 THEN
            RETURN (FLOWCHART, IMAGE_WITH_ANALYSIS, 0.8)
        ELSE
            RETURN (DIAGRAM, IMAGE_WITH_ANALYSIS, 0.75)
        END IF
    END IF
    
    // 優先度2: 純粋なテキスト
    IF features.text_density > 0.7 AND 
       detailed_result.table_count = 0 AND 
       detailed_result.rect_count < 2 THEN
        RETURN (PURE_TEXT, TEXT_ONLY, 0.9)
    END IF
    
    // 優先度3: 表の処理
    IF detailed_result.table_count > 0 THEN
        IF detailed_result.total_cells > COMPLEX_TABLE_THRESHOLD THEN
            RETURN (COMPLEX_TABLE, IMAGE_WITH_OCR, 0.85)
        ELSE
            RETURN (SIMPLE_TABLE, STRUCTURED_EXTRACTION, 0.8)
        END IF
    END IF
    
    // 優先度4: フロー図
    IF detailed_result.rect_count >= MIN_FLOW_NODES AND
       (detailed_result.has_step_pattern OR detailed_result.line_count > 5) THEN
        RETURN (FLOWCHART, IMAGE_WITH_ANALYSIS, 0.75)
    END IF
    
    // 優先度5: その他の図
    IF features.large_images_count > 0 THEN
        RETURN (DIAGRAM, IMAGE_WITH_ANALYSIS, 0.8)
    END IF
    
    // 優先度6: 混在型
    IF detailed_result.rect_count > 0 OR detailed_result.line_count > 10 THEN
        RETURN (MIXED, HYBRID, 0.6)
    END IF
    
    // デフォルト
    RETURN (PURE_TEXT, TEXT_ONLY, 0.5)
END ALGORITHM
```

## 6. 並列処理アルゴリズム

```pseudo
ALGORITHM ProcessParallel(pdf_path, output_dir)
    doc ← open_pdf(pdf_path)
    results ← initialize_results()
    
    // スレッドプール作成
    executor ← ThreadPoolExecutor(max_workers = min(CPU_COUNT, 8))
    futures ← []
    
    // タスク投入
    FOR page_num FROM 0 TO doc.page_count - 1 DO
        future ← executor.submit(ProcessPageParallel, pdf_path, page_num, output_dir)
        futures.append((future, page_num))
    END FOR
    
    // 結果収集
    FOR future, page_num IN as_completed(futures) DO
        TRY
            page_result ← future.result()
            IF page_result NOT NULL THEN
                results.processed_pages.append(page_result)
                update_summary(results.summary, page_result)
            END IF
        CATCH exception AS e
            print_error("Page", page_num + 1, e)
        END TRY
    END FOR
    
    // ソート
    results.processed_pages ← sort_by_page_number(results.processed_pages)
    
    doc.close()
    executor.shutdown()
    RETURN results
END ALGORITHM
```

## 7. ページ処理アルゴリズム（並列版）

```pseudo
ALGORITHM ProcessPageParallel(pdf_path, page_num, output_dir)
    TRY
        // 各スレッドで独立してドキュメントを開く
        doc ← open_pdf(pdf_path)
        page ← doc.get_page(page_num)
        
        // ページ分析
        analysis ← AnalyzePage(page, page_num)
        
        IF analysis.skip THEN
            doc.close()
            RETURN create_skip_result(page_num, analysis.reason)
        END IF
        
        // 処理実行
        result ← ProcessPageContent(page, page_num, analysis, output_dir)
        
        doc.close()
        RETURN result
        
    CATCH exception AS e
        print_error("Page processing error", page_num + 1, e)
        RETURN NULL
    END TRY
END ALGORITHM
```

## 8. 画像処理アルゴリズム

```pseudo
ALGORITHM ProcessImageContent(page, page_num, analysis, output_dir)
    // 解像度設定
    dpi_multiplier ← config.image_dpi_multiplier
    matrix ← create_matrix(dpi_multiplier, dpi_multiplier)
    
    // 画像生成
    pixmap ← page.get_pixmap(matrix)
    image_data ← pixmap.to_bytes("png")
    
    TRY
        // メモリ効率的な画像処理
        WITH image ← open_image(image_data) DO
            result.image_size ← image.size
            
            IF output_dir NOT NULL THEN
                filename ← format_filename(page_num, analysis.page_type)
                filepath ← join_path(output_dir, filename)
                image.save(filepath)
                result.image_path ← filepath
            END IF
        END WITH
    FINALLY
        // メモリ解放
        pixmap ← NULL
    END TRY
    
    RETURN result
END ALGORITHM
```

## 9. コスト計算アルゴリズム

```pseudo
ALGORITHM CalculateROI(results)
    summary ← results.summary
    
    // 精度の仮定値
    TEXT_ACCURACY ← 0.8
    IMAGE_ACCURACY ← 0.95
    
    // 価値計算
    text_value ← summary.text_pages × TEXT_ACCURACY
    image_value ← summary.image_pages × IMAGE_ACCURACY
    hybrid_value ← summary.hybrid_pages × 0.9
    
    total_value ← text_value + image_value + hybrid_value
    total_cost ← summary.total_cost
    
    // ROI計算
    IF total_cost > 0 THEN
        roi ← (total_value - total_cost) / total_cost
    ELSE
        roi ← 0
    END IF
    
    RETURN {
        total_value: total_value,
        total_cost: total_cost,
        roi: roi,
        cost_per_page: total_cost / results.total_pages
    }
END ALGORITHM
```