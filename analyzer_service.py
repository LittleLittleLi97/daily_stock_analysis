# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析服务层
===================================

职责：
1. 封装核心分析逻辑，支持多调用方（CLI、WebUI、Bot）
2. 提供清晰的API接口，不依赖于命令行参数
3. 支持依赖注入，便于测试和扩展
4. 统一管理分析流程和配置
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

logger = logging.getLogger(__name__)

from src.analyzer import AnalysisResult
from src.config import get_config, Config
from src.notification import NotificationService
from src.enums import ReportType
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review



def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None
) -> Optional[AnalysisResult]:
    """
    分析单只股票
    
    Args:
        stock_code: 股票代码
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选）
        
    Returns:
        分析结果对象
    """
    if config is None:
        config = get_config()
    
    # 创建分析流水线
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )
    
    # 使用通知服务（如果提供）
    if notifier:
        pipeline.notifier = notifier
    
    # 根据full_report参数设置报告类型
    report_type = ReportType.FULL if full_report else ReportType.SIMPLE
    
    # 运行单只股票分析
    result = pipeline.process_single_stock(
        code=stock_code,
        skip_analysis=False,
        single_stock_notify=notifier is not None,
        report_type=report_type
    )
    
    return result

def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
    max_workers: Optional[int] = None,
) -> List[AnalysisResult]:
    """
    分析多只股票（并行执行，缩短总耗时）。

    使用线程池并发调用 analyze_stock，并发数由 max_workers 或配置 MAX_WORKERS 决定。
    单只股票约 1~2 分钟时，多只股票总耗时可近似为 ceil(N / max_workers) * 单只耗时。

    Args:
        stock_codes: 股票代码列表
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选）
        max_workers: 最大并发数（可选，默认使用 config.max_workers，建议 2~5 以免触发 API 限流）

    Returns:
        分析结果列表（与 stock_codes 顺序一致，失败或跳过的不在此列表中）
    """
    if config is None:
        config = get_config()

    workers = max(1, max_workers if max_workers is not None else config.max_workers)
    if len(stock_codes) <= 1:
        # Single or empty: no need for thread pool
        results = []
        for code in stock_codes:
            r = analyze_stock(code, config, full_report, notifier)
            if r:
                results.append(r)
        return results

    logger.info("analyze_stocks: 并行分析 %d 只股票, max_workers=%d", len(stock_codes), workers)
    # Preserve order: submit all, then collect by original code order
    code_to_future = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for code in stock_codes:
            fut = executor.submit(analyze_stock, code, config, full_report, notifier)
            code_to_future[code] = fut
        results = []
        for code in stock_codes:
            try:
                r = code_to_future[code].result()
                if r:
                    results.append(r)
            except Exception as e:
                logger.warning("analyze_stocks: %s 分析异常: %s", code, e)
    return results

def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None
) -> Optional[str]:
    """
    执行大盘复盘
    
    Args:
        config: 配置对象（可选，默认使用单例）
        notifier: 通知服务（可选）
        
    Returns:
        复盘报告内容
    """
    if config is None:
        config = get_config()
    
    # 创建分析流水线以获取analyzer和search_service
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )
    
    # 使用提供的通知服务或创建新的
    review_notifier = notifier or pipeline.notifier
    
    # 调用大盘复盘函数
    return run_market_review(
        notifier=review_notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service
    )


