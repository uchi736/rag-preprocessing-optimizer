"""
プロンプトテンプレート管理モジュール
"""

from .gemini_prompts import (
    get_prompt,
    TABLE_PROMPT,
    FIGURE_PROMPT,
    IMAGE_PROMPT,
    FULL_PAGE_PROMPT,
    HYBRID_PAGE_PROMPT,
)

__all__ = [
    'get_prompt',
    'TABLE_PROMPT',
    'FIGURE_PROMPT',
    'IMAGE_PROMPT',
    'FULL_PAGE_PROMPT',
    'HYBRID_PAGE_PROMPT',
]